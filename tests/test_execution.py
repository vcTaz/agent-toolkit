import asyncio
import json
import unittest
from dataclasses import replace
from swarm.domain import Role, RoleName
from swarm.contracts import (ModelResponse, ToolCall, ExecutionContext, Budget,
                             ProviderError, ProviderErrorCode, ExecutionError)
from swarm.providers.fake import ScriptedProvider, Delay
from swarm.tools.arithmetic import ArithmeticTool
from swarm.execution import execute
from swarm.output import parse_output
from swarm.events import EventType


def response(**extra):
    return ModelResponse(content=json.dumps({'status': 'SUCCEEDED', 'summary': 'done', **extra}))


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = ExecutionContext(run_id='r', assignment_id='x', agent_id='a',
                                        task_id='t', objective='verify 1 + 2 = 3',
                                        run_tools=('arithmetic',), agent_tools=('arithmetic',))
        self.role = Role(id='validator', name=RoleName.VALIDATOR, allowed_tools=('arithmetic',),
                         output_fields=('findings', 'review'))
        self.events = []

    async def run_provider(self, steps, **kwargs):
        return await execute(self.context, self.role, ScriptedProvider(steps),
                             {'arithmetic': ArithmeticTool()},
                             audit=self.events.append, **kwargs)

    async def test_valid_result_is_proposal_only(self):
        output = await self.run_provider([response(findings=[{'claim': '3'}])])
        self.assertEqual(output.findings[0].claim, '3')
        self.assertFalse(hasattr(output.findings[0], 'status'))
        self.assertEqual(output.assignment_id, 'x')
        self.assertEqual(self.events[-1].type, EventType.EXECUTION_COMPLETED)

    async def test_malformed_response_repaired_with_accounting(self):
        budget = Budget(request_limit=3)
        output = await self.run_provider([ModelResponse(content='{'), response()], budget=budget)
        self.assertEqual(output.status, 'SUCCEEDED')
        self.assertEqual(budget.requests, 2)
        self.assertEqual(sum(e.type == EventType.OUTPUT_REJECTED for e in self.events), 1)

    async def test_refused_dispatch_releases_its_reservation(self):
        call = ModelResponse(tool_calls=(ToolCall(id='c', name='arithmetic',
                             arguments_json='{"numbers":[1],"expected":1}'),))
        # A refused dispatch never happened, so it must not consume run capacity; the
        # provider request that did happen before a refused tool call still counts.
        cases = [([response()], EventType.PROVIDER_REQUESTED, (0, 0)),
                 ([call], EventType.TOOL_STARTED, (1, 0))]
        for steps, refused, expected in cases:
            with self.subTest(refused=refused):
                budget = Budget(request_limit=2, tool_limit=2)
                def refuse(event, refused=refused):
                    self.events.append(event)
                    if event.type == refused:
                        raise ExecutionError('host refused this dispatch')
                with self.assertRaises(ExecutionError):
                    await execute(self.context, self.role, ScriptedProvider(steps),
                                  {'arithmetic': ArithmeticTool()}, audit=refuse, budget=budget)
                self.assertEqual((budget.requests, budget.tool_calls), expected)

    async def test_repair_and_request_limits(self):
        for options in ({'repair_limit': 1}, {'budget': Budget(request_limit=1)}):
            with self.subTest(options=options):
                with self.assertRaises(ExecutionError):
                    await self.run_provider([ModelResponse(content='{')] * 4, **options)

    async def test_tool_result_is_host_attributed(self):
        def after_tool(request):
            tool_message = json.loads(request.messages[-1].content)
            self.assertEqual(tool_message['value']['actual'], 3)
            self.assertTrue(tool_message['value']['matches'])
            return response(findings=[{'claim': '3', 'evidence_ids': [tool_message['id']]}])
        output = await self.run_provider([
            ModelResponse(tool_calls=(ToolCall(id='c', name='arithmetic',
                arguments_json='{"numbers":[1,2],"expected":3}'),)), after_tool])
        self.assertEqual(output.findings[0].evidence_ids, (output.tool_results[0].id,))
        self.assertEqual(output.tool_results[0].assignment_id, 'x')

    async def test_wrong_claim_does_not_become_validation(self):
        def wrong(request):
            value = json.loads(request.messages[-1].content)['value']
            self.assertFalse(value['matches'])
            return response(findings=[{'claim': 'sum is 4'}])
        output = await self.run_provider([ModelResponse(tool_calls=(ToolCall(id='c', name='arithmetic',
            arguments_json='{"numbers":[1,2],"expected":4}'),)), wrong])
        self.assertEqual(output.findings[0].claim, 'sum is 4')
        self.assertFalse(hasattr(output.findings[0], 'status'))

    async def test_forbidden_tool_never_executes(self):
        class Trap(ArithmeticTool):
            async def execute(self, arguments, context):
                self.fail_if_called = True
                raise AssertionError('must not execute')
        trap = Trap()
        with self.assertRaises(ExecutionError):
            await execute(replace(self.context, run_tools=()), self.role,
                          ScriptedProvider([ModelResponse(tool_calls=(ToolCall(
                              id='c', name='arithmetic', arguments_json='{}'),))]),
                          {'arithmetic': trap}, audit=self.events.append)
        self.assertFalse(hasattr(trap, 'fail_if_called'))
        self.assertFalse(any(e.type == EventType.TOOL_STARTED for e in self.events))

    async def test_timeout_is_bounded_and_recorded(self):
        budget = Budget()
        with self.assertRaises(ExecutionError):
            await self.run_provider([Delay(1, response())], timeout=0.01, budget=budget)
        self.assertEqual(budget.requests, 1)
        self.assertEqual(self.events[-1].type, EventType.EXECUTION_FAILED)

    async def test_provider_error_is_normalized(self):
        with self.assertRaises(ExecutionError):
            await self.run_provider([ProviderError(ProviderErrorCode.AUTHENTICATION, 'denied')])
        self.assertTrue(any(e.type == EventType.PROVIDER_FAILED for e in self.events))

    async def test_disagreement_stays_two_distinct_proposals(self):
        first = await self.run_provider([response(findings=[{'claim': '3'}])])
        second = await self.run_provider([response(findings=[{'claim': '4'}])])
        self.assertNotEqual(first.findings, second.findings)

    async def test_storage_failure_prevents_provider_dispatch(self):
        def broken(event):
            raise OSError('disk unavailable')
        provider = ScriptedProvider([response()])
        with self.assertRaises(OSError):
            await execute(self.context, self.role, provider, {}, audit=broken)
        self.assertEqual(provider.requests, [])

    def test_authority_and_fabricated_evidence_rejected(self):
        for extra in [{'run_state': 'COMPLETED'}, {'findings': [{'claim': '3', 'status': 'VALIDATED'}]},
                      {'findings': [{'claim': '3', 'evidence_ids': ['invented']}]},
                      {'tool_results': []}, {'agent_id': 'other'},
                      {'messages': [{'recipient': 'agent:other', 'summary': 'hi'}]}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse_output(json.dumps({'status': 'SUCCEEDED', 'summary': 'x', **extra}),
                             self.role, ())

    async def test_huge_integer_is_rejected_with_terminal_event(self):
        call = ToolCall(id='c', name='arithmetic', arguments_json=json.dumps({'numbers': [10**400], 'expected': 3}))
        with self.assertRaises(ExecutionError):
            await self.run_provider([ModelResponse(tool_calls=(call,))])
        self.assertEqual(self.events[-1].type, EventType.EXECUTION_FAILED)

    async def test_unexpected_provider_failure_is_normalized_and_audited(self):
        with self.assertRaises(ExecutionError):
            await self.run_provider([RuntimeError('adapter bug')])
        self.assertTrue(any(e.type == EventType.PROVIDER_FAILED for e in self.events))
        self.assertEqual(self.events[-1].type, EventType.EXECUTION_FAILED)

    async def test_provider_timeout_has_matching_failure_event(self):
        with self.assertRaises(ExecutionError):
            await self.run_provider([Delay(1, response())], timeout=0.01)
        self.assertTrue(any(e.type == EventType.PROVIDER_FAILED for e in self.events))

    async def test_tool_exception_has_matching_failure_event(self):
        class BrokenTool(ArithmeticTool):
            async def execute(self, arguments, execution_context):
                raise RuntimeError('broken tool')
        with self.assertRaises(ExecutionError):
            await execute(self.context, self.role, ScriptedProvider([ModelResponse(tool_calls=(ToolCall(
                id='c', name='arithmetic', arguments_json='{"numbers":[1],"expected":1}'),))]),
                {'arithmetic': BrokenTool()}, audit=self.events.append)
        self.assertTrue(any(e.type == EventType.TOOL_FAILED for e in self.events))

    def test_huge_confidence_and_duplicate_keys_fail_closed(self):
        for payload in ['{"status":"FAILED","status":"SUCCEEDED","summary":"x"}',
                        json.dumps({'status': 'SUCCEEDED', 'summary': 'x', 'confidence': 10**400})]:
            with self.assertRaises(ValueError):
                parse_output(payload, self.role, ())

    async def test_invalid_normalized_tool_call_rejected(self):
        with self.assertRaises(ExecutionError):
            await self.run_provider([ModelResponse(tool_calls=('not a call',))])
        self.assertEqual(self.events[-1].type, EventType.EXECUTION_FAILED)

    async def test_tool_budget_and_role_allowlist_are_enforced(self):
        call = ModelResponse(tool_calls=(ToolCall(id='c', name='arithmetic',
                             arguments_json='{"numbers":[1],"expected":1}'),))
        with self.assertRaises(ExecutionError):
            await self.run_provider([call], budget=Budget(tool_limit=0))
        self.assertFalse(any(e.type == EventType.TOOL_STARTED for e in self.events))
        with self.assertRaises(ExecutionError):
            await execute(self.context, replace(self.role, allowed_tools=()), ScriptedProvider([call]),
                          {'arithmetic': ArithmeticTool()}, audit=self.events.append)

    async def test_cancellation_is_propagated_and_audited(self):
        task = asyncio.create_task(self.run_provider([Delay(10, response())]))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.events[-1].type, EventType.EXECUTION_CANCELLED)

    def test_nested_review_and_result_proposals_are_typed(self):
        role = replace(self.role, output_fields=('review', 'result', 'task_requests', 'messages'))
        output = parse_output(json.dumps({'status': 'SUCCEEDED', 'summary': 'draft',
            'review': {'target_id': 'f', 'target_revision': 2, 'decision': 'CHALLENGE', 'summary': 'check'},
            'result': {'answer': '3', 'finding_ids': ['f']},
            'task_requests': [{'objective': 'check arithmetic'}],
            'messages': [{'recipient': 'orchestrator', 'summary': 'check'}]}), role, ())
        self.assertEqual(output.review.decision, 'CHALLENGE')
        self.assertEqual(output.result.finding_ids, ('f',))
        self.assertEqual(output.task_requests[0].objective, 'check arithmetic')
