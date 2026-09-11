import asyncio
import gc
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from swarm.domain import *
from swarm.events import EventDraft, EventType
from swarm.persistence import SQLiteRepository, StorageError
from swarm.contracts import ModelResponse, ExecutionError
from swarm.orchestration import WorkController
from swarm.policies import BudgetPolicy


CRITERIA = (Criterion(id='c1', description='coordination produces a correct answer'),)
"""A run without acceptance criteria is refused at RECEIVED from Stage 7 on; these tests
exercise scheduling, so they declare one criterion and leave coverage to the Stage-7 suite."""


def result(summary='done', **extra):
    return ModelResponse(content=json.dumps({'status': 'SUCCEEDED', 'summary': summary, **extra}))


def seed(repo, *records):
    repo.commit('r', records, [EventDraft(type=EventType.RECORD_CHANGED, record_id=r.id, record_revision=r.revision) for r in records])


def setup(repo, tasks=None, run=None):
    seed(repo, run or Run(id='r', objective='coordinate', acceptance_criteria=CRITERIA), Role(id='e', name=RoleName.EXPLORER),
         Agent(id='a', run_id='r', group_id='g'), Agent(id='b', run_id='r', group_id='g'),
         AgentGroup(id='g', run_id='r', agent_ids=('a', 'b'), task_ids=tuple(t.id for t in tasks or ())),
         *(tasks or ()))


def task(identity, **kwargs):
    return Task(id=identity, run_id='r', objective=identity, group_id='g', role_id='e', **kwargs)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def test_concurrent_integration_with_dependencies_message_and_candidate(self):
        tasks = [task('first'), task('second'), task('dependent', dependency_ids=('first', 'second'), allow_dependency_candidates=True)]
        setup(self.repo, tasks)
        both_started = asyncio.Event()
        active, peak, starts = 0, 0, []
        class Provider:
            async def generate(_, request):
                nonlocal active, peak
                wire = json.loads(request.messages[1].content)
                context = json.loads(wire['context'])
                identity = context['task']['id']
                starts.append(identity)
                active += 1
                peak = max(peak, active)
                if identity in ('first', 'second'):
                    if active == 2:
                        both_started.set()
                    await asyncio.wait_for(both_started.wait(), 1)
                active -= 1
                if identity == 'first':
                    return result(findings=[{'claim': 'candidate fact'}], messages=[{'recipient': 'group:g', 'summary': 'shared insight'}])
                if identity == 'dependent':
                    self.assertIn('candidate fact', wire['context'])
                    self.assertIn('shared insight', wire['context'])
                return result()
        controller = WorkController(self.repo, 'r', {'fake': Provider()})
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        self.assertEqual(peak, 2)
        self.assertEqual(starts[-1], 'dependent')
        self.assertTrue(all(s[t.id].status == TaskStatus.COMPLETED for t in tasks))
        self.assertEqual([f.status for f in s.values() if isinstance(f, Finding)], [FindingStatus.PROPOSED])
        self.assertTrue(all(a.status == AgentStatus.IDLE for a in s.values() if isinstance(a, Agent)))
        validate_records(s.values())
        self.assertTrue(any(e.type == EventType.CONTEXT_SELECTED for e in self.repo.inspect('r').events))

    async def test_private_message_and_peer_transcript_never_reach_another_assignment(self):
        setup(self.repo, [task('alpha'), task('beta')])
        # Every attempt is recorded: a retry must not be able to hide a leak from an earlier one.
        contexts = []
        class Provider:
            async def generate(_, request):
                await asyncio.sleep(0)
                wire = json.loads(request.messages[1].content)
                identity = json.loads(wire['context'])['task']['id']
                contexts.append((identity, request.messages[0].content + wire['context']))
                return result(summary=f'ALPHA_ONLY_TRANSCRIPT_{identity}')
        controller = WorkController(self.repo, 'r', {'fake': Provider()})
        controller.send_message(Message(id='m', run_id='r', sender='system', recipient='agent:a',
                                        kind='SYSTEM', summary='PRIVATE_TO_ALPHA_AGENT'))
        await controller.run_until_idle()
        self.assertEqual([identity for identity, _ in contexts], ['alpha', 'beta'])
        for identity, payload in contexts:
            self.assertEqual('PRIVATE_TO_ALPHA_AGENT' in payload, identity == 'alpha')
            self.assertNotIn('ALPHA_ONLY_TRANSCRIPT', payload)
        assignments = {a.task_id: a for a in self.repo.snapshot('r').values() if isinstance(a, Assignment)}
        self.assertEqual(assignments['alpha'].message_ids, ('m',))
        self.assertEqual(assignments['beta'].message_ids, ())

    async def test_priority_cap_and_failed_dependency(self):
        setup(self.repo, [task('low', priority=1), task('high', priority=3), task('downstream', dependency_ids=('high',))],
              Run(id='r', objective='x', acceptance_criteria=CRITERIA, concurrency_limit=1, assignment_attempt_limit=1))
        starts = []
        class Provider:
            async def generate(_, request):
                identity = json.loads(request.messages[1].content)['objective']
                starts.append(identity)
                if identity == 'high':
                    return ModelResponse(content='{"status":"FAILED","summary":"cannot"}')
                return result()
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(starts, ['high', 'low'])
        self.assertEqual(self.repo.get('r', 'downstream').status, TaskStatus.CANCELLED)

    async def test_concurrency_cap_bounds_parallel_executions(self):
        tasks = [task('one'), task('two'), task('three')]
        agents = [Agent(id=name, run_id='r', group_id='g') for name in ('a', 'b', 'c')]
        seed(self.repo, Run(id='r', objective='x', acceptance_criteria=CRITERIA, concurrency_limit=2), Role(id='e', name=RoleName.EXPLORER),
             *agents, AgentGroup(id='g', run_id='r', agent_ids=('a', 'b', 'c'),
                                 task_ids=tuple(t.id for t in tasks)), *tasks)
        active = peak = 0
        class Provider:
            async def generate(_, request):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1
                return result()
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(peak, 2)
        self.assertTrue(all(t.status == TaskStatus.COMPLETED
                            for t in self.repo.snapshot('r').values() if isinstance(t, Task)))

    async def test_incompatible_permissions_never_dispatch(self):
        setup(self.repo, [task('t', required_tools=('shell',))])
        class Provider:
            async def generate(_, request):
                raise AssertionError('forbidden dispatch')
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.FAILED)
        self.assertEqual(self.repo.get('r', 'r').provider_requests, 0)

    async def test_needs_input_retry_is_bounded(self):
        setup(self.repo, [task('t')])
        class Provider:
            async def generate(_, request):
                return ModelResponse(content='{"status":"NEEDS_INPUT","summary":"need data"}')
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.FAILED)
        assignments = [r for r in self.repo.snapshot('r').values() if isinstance(r, Assignment)]
        self.assertEqual([a.attempt for a in assignments], [1, 2])

    async def test_retry_keeps_the_targeted_messages_the_failed_attempt_had(self):
        setup(self.repo, [task('t')], Run(id='r', objective='x', acceptance_criteria=CRITERIA, assignment_attempt_limit=2))
        seen = []
        class Provider:
            async def generate(_, request):
                context = json.loads(json.loads(request.messages[1].content)['context'])
                seen.append([m['summary'] for m in context['messages']])
                if len(seen) == 1:
                    return ModelResponse(content='{"status":"FAILED","summary":"transient"}')
                return result()
        controller = WorkController(self.repo, 'r', {'fake': Provider()})
        controller.send_message(Message(id='m', run_id='r', sender='system', recipient='agent:a',
                                        kind='SYSTEM', summary='prerequisite detail'))
        await controller.run_until_idle()
        self.assertEqual(seen, [['prerequisite detail'], ['prerequisite detail']])
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.COMPLETED)
        # The receipt is recorded once the work that consumed it actually succeeded.
        self.assertEqual(self.repo.get('r', 'm').read_by, ('a',))

    async def test_concurrent_receipts_for_one_group_message_serialize(self):
        setup(self.repo, [task('one'), task('two')])
        class Provider:
            async def generate(_, request):
                await asyncio.sleep(0)
                return result()
        controller = WorkController(self.repo, 'r', {'fake': Provider()})
        controller.send_message(Message(id='m', run_id='r', sender='system', recipient='group:g',
                                        kind='SYSTEM', summary='group notice'))
        await controller.run_until_idle()
        message = self.repo.get('r', 'm')
        self.assertEqual(message.delivered_to, ('a', 'b'))
        self.assertEqual(tuple(sorted(message.read_by)), ('a', 'b'))
        # created, delivered, then one receipt per agent, each in its own serialized commit.
        self.assertEqual(message.revision, 4)
        validate_records(self.repo.snapshot('r').values())

    async def test_durable_budget_shared_no_reset(self):
        setup(self.repo, [task('one'), task('two'), task('three')], Run(id='r', objective='x', acceptance_criteria=CRITERIA, provider_request_limit=2))
        class Provider:
            async def generate(_, request):
                await asyncio.sleep(0)
                return result()
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 'r').provider_requests, 2)
        self.assertEqual(sum(t.status == TaskStatus.COMPLETED for t in self.repo.snapshot('r').values() if isinstance(t, Task)), 2)

    async def test_reserved_budget_refusal_does_not_drift_from_the_durable_ledger(self):
        setup(self.repo, [task('one'), task('two')],
              Run(id='r', objective='x', acceptance_criteria=CRITERIA, provider_request_limit=3, assignment_attempt_limit=1))
        class Provider:
            async def generate(_, request):
                return ModelResponse(content='not json')  # forces a repair round
        controller = WorkController(self.repo, 'r', {'fake': Provider()},
                                    budget_policy=BudgetPolicy(reserved_requests=1))
        await controller.run_until_idle()
        # The in-process mirror must never claim more of the run than the durable ledger records.
        self.assertEqual(controller.budget.requests, self.repo.get('r', 'r').provider_requests)

    async def test_stale_required_task_revision_rejects_output(self):
        setup(self.repo, [task('t')], Run(id='r', objective='x', acceptance_criteria=CRITERIA, assignment_attempt_limit=1))
        class Provider:
            async def generate(_, request):
                current = self.repo.get('r', 't')
                seed(self.repo, replace(current, description='changed', revision=current.revision + 1))
                return result(findings=[{'claim': 'must not enter state'}])
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertFalse(any(isinstance(r, Finding) for r in self.repo.snapshot('r').values()))
        events = self.repo.inspect('r').events
        self.assertTrue(any(e.type == EventType.OUTPUT_REJECTED and 'TASK_REVISION_CHANGED' in e.detail_json for e in events))

    async def test_unrelated_state_change_does_not_reject(self):
        setup(self.repo, [task('t')])
        seed(self.repo, SwarmState(id='state', run_id='r'))
        class Provider:
            async def generate(_, request):
                state = self.repo.get('r', 'state')
                seed(self.repo, replace(state, priorities=('unrelated',), revision=state.revision + 1))
                return result()
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.COMPLETED)

    async def test_cancelled_late_result_never_admitted(self):
        setup(self.repo, [task('t')])
        controller = None
        class Provider:
            async def generate(_, request):
                controller.cancel('user cancelled')
                # Return without yielding to reproduce a result racing with cancellation.
                return result(findings=[{'claim': 'late'}])
        controller = WorkController(self.repo, 'r', {'fake': Provider()})
        await controller.run_until_idle()
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.CANCELLED)
        self.assertFalse(any(isinstance(r, Finding) for r in self.repo.snapshot('r').values()))

    async def test_deadline_prevents_dispatch(self):
        deadline = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        setup(self.repo, [task('t')], Run(id='r', objective='x', acceptance_criteria=CRITERIA, deadline_at=deadline))
        class Provider:
            async def generate(_, request):
                raise AssertionError('deadline dispatch')
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 'r').provider_requests, 0)
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.CANCELLED)
        # The stop is durable, so a later controller cannot restart the same work.
        self.assertEqual(self.repo.get('r', 'r').work_stop_reason, 'DEADLINE')

    async def test_task_requests_remain_proposals(self):
        setup(self.repo, [task('t')])
        class Provider:
            async def generate(_, request):
                return result(task_requests=[{'objective': 'follow up'}, {'objective': 'follow up'}])
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        s = self.repo.snapshot('r')
        self.assertEqual(sum(isinstance(r, Task) for r in s.values()), 1)
        self.assertEqual(sum(isinstance(r, TaskRequest) for r in s.values()), 1)

    async def test_storage_failure_stops_work(self):
        setup(self.repo, [task('t')])
        self.repo.close()
        with self.assertRaises(StorageError):
            await WorkController(self.repo, 'r', {}).run_until_idle()

    async def test_timeout_attempts_are_bounded(self):
        setup(self.repo, [task('t')], Run(id='r', objective='x', acceptance_criteria=CRITERIA, assignment_attempt_limit=1, execution_timeout=0.01))
        class Provider:
            async def generate(_, request):
                await asyncio.sleep(1)
                return result()
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.FAILED)
        self.assertIn('timeout', self.repo.get('r', 't').outcome)

    async def test_optional_priority_does_not_consume_required_reserve(self):
        setup(self.repo, [task('optional', required=False, priority=100), task('required')],
              Run(id='r', objective='x', acceptance_criteria=CRITERIA, provider_request_limit=1))
        starts = []
        class Provider:
            async def generate(_, request):
                starts.append(json.loads(request.messages[1].content)['objective'])
                return result()
        await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(starts, ['required'])

    async def test_context_overflow_fails_without_provider_request(self):
        setup(self.repo, [task('t', description='x' * 25000)])
        await WorkController(self.repo, 'r', {'fake': object()}).run_until_idle()
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.FAILED)
        self.assertIn('OVERFLOW', self.repo.get('r', 't').outcome)
        self.assertEqual(self.repo.get('r', 'r').provider_requests, 0)

    async def test_completion_order_does_not_violate_invariants(self):
        for delays in ((0.01, 0), (0, 0.01)):
            with self.subTest(delays=delays):
                repo = SQLiteRepository(':memory:')
                self.addCleanup(repo.close)
                setup(repo, [task('a-task'), task('b-task')])
                class Provider:
                    async def generate(_, request):
                        identity = json.loads(request.messages[1].content)['objective']
                        await asyncio.sleep(delays[identity == 'b-task'])
                        return result(findings=[{'claim': identity}])
                await WorkController(repo, 'r', {'fake': Provider()}).run_until_idle()
                s = repo.snapshot('r')
                validate_records(s.values())
                self.assertEqual(sorted(f.claim for f in s.values() if isinstance(f, Finding)), ['a-task', 'b-task'])
                self.assertTrue(all(t.status == TaskStatus.COMPLETED for t in s.values() if isinstance(t, Task)))

    async def test_storage_failure_during_execution_prevents_later_dispatch(self):
        setup(self.repo, [task('first'), task('later', dependency_ids=('first',))], Run(id='r', objective='x', acceptance_criteria=CRITERIA, concurrency_limit=1))
        starts = []
        class Provider:
            async def generate(_, request):
                starts.append(request.request_id)
                self.repo.close()
                return result()
        with self.assertRaises(StorageError):
            await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        self.assertEqual(len(starts), 1)

    async def test_storage_failure_leaves_no_unretrieved_execution_exception(self):
        setup(self.repo, [task('first')])
        class Provider:
            async def generate(_, request):
                self.repo.close()
                return result()
        unhandled = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: unhandled.append(context))
        with self.assertRaises(StorageError):
            await WorkController(self.repo, 'r', {'fake': Provider()}).run_until_idle()
        gc.collect()
        await asyncio.sleep(0)
        self.assertEqual([c.get('message') for c in unhandled], [])

    async def test_no_new_work_after_persisted_cancellation(self):
        setup(self.repo, [task('t')])
        controller = WorkController(self.repo, 'r', {})
        controller.cancel('stop')
        await WorkController(self.repo, 'r', {}).run_until_idle()
        self.assertEqual(self.repo.get('r', 'r').provider_requests, 0)
        self.assertEqual(self.repo.get('r', 't').status, TaskStatus.CANCELLED)
