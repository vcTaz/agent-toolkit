"""Delivery semantics, context provenance, reconsideration outcomes and follow-up authority."""
import json
import unittest
from dataclasses import replace
from stage5_support import (TOOLS, agent, done, explore, findings, run_record, seed, setup_run,
                            state_of)
from stage6_support import ReconsideringProvider, cycles, propagations, tasks_of
from swarm.admission import check_assignment_admissibility
from swarm.context import ContextBuilder
from swarm.domain import (Agent, AgentGroup, Assignment, PropagationStatus, ReconsiderationOutcome,
                          Task, TaskStatus, validate_records)
from swarm.events import EventType
# The Stage-5/6 subject is the work engine: these tests drive admitted work, review
# and circulation to quiescence. Whether the run is then finished is the Stage-7 run
# workflow, exercised in the Stage-7 suite against ``WorkController`` above this layer.
from swarm.engine import WorkEngine
from swarm.output import ReconsiderationDraft, parse_output
from swarm.persistence import SQLiteRepository
from swarm.propagation import deliverable, for_task
from swarm.roles import default_roles


class ReconsiderationCase(unittest.IsolatedAsyncioTestCase):
    """Branch A validates a fact in one run; branch B is then opened and receives it."""

    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def controller(self, provider, **kwargs):
        return WorkEngine(self.repo, 'r', {'fake': provider}, TOOLS, **kwargs)

    async def validated_branch(self, *, run=None, provider=None):
        setup_run(self.repo, [explore('ta', [1, 2, 3], group_id='ga')],
                  [agent('a', 'ga'), agent('critic'), agent('validator')], run=run,
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',))])
        await self.controller(provider or ReconsideringProvider()).run_until_idle()
        return next(f for f in findings(self.repo.snapshot('r')) if f.status.value == 'VALIDATED')

    def open_branch_b(self, *tasks):
        seed(self.repo, 'r', Agent(id='b', run_id='r', group_id='gb', permissions=('arithmetic',)),
             AgentGroup(id='gb', run_id='r', agent_ids=('b',),
                        task_ids=tuple(t.id for t in tasks)), *tasks)

    async def deliver_to_b(self, provider=None, *, task=None):
        base = await self.validated_branch()
        self.open_branch_b(task or explore('tb', [10, 20], group_id='gb'))
        controller = self.controller(provider or ReconsideringProvider())
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r'), base


class DeliveryTests(ReconsiderationCase):
    async def test_a_pending_target_consumes_the_delivery_in_its_next_assignment(self):
        controller, s, base = await self.deliver_to_b()
        propagation = propagations(s)[0]
        self.assertEqual(propagation.target_task_id, 'tb')
        self.assertEqual(propagation.canonical_finding_id, base.id)
        self.assertEqual(propagation.status, PropagationStatus.CONSUMED)
        # No extra task was needed: the delivery reached the task that was already waiting.
        self.assertIsNone(propagation.reconsideration_task_id)
        assignment = s[propagation.outcome_assignment_id]
        self.assertEqual(assignment.task_id, 'tb')
        self.assertIn(propagation.id, assignment.propagation_ids)
        validate_records(s.values())

    async def test_a_running_target_is_never_given_something_it_did_not_start_with(self):
        controller, s, base = await self.deliver_to_b()
        running = replace(s['tb'], status=TaskStatus.RUNNING, revision=s['tb'].revision + 1)
        self.assertFalse(deliverable(propagations(s)[0], dict(s, tb=running)))
        # Every recorded outcome came from an assignment that had the delivery pinned from
        # the start, so no in-flight snapshot was ever amended.
        for propagation in propagations(s):
            if propagation.outcome_assignment_id:
                self.assertIn(propagation.id, s[propagation.outcome_assignment_id].propagation_ids)

    async def test_a_delivery_that_arrives_after_its_target_finished_becomes_bounded_work(self):
        await self.validated_branch()
        # Branch B finishes early; branch A validates a second fact while it is already done.
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        seed(self.repo, 'r', explore('ta2', [4, 4], group_id='ga'),
             replace(self.repo.get('r', 'ga'), task_ids=('ta', 'ta2'),
                     revision=self.repo.get('r', 'ga').revision + 1))
        controller = self.controller(ReconsideringProvider())
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        late = [p for p in propagations(s) if p.reconsideration_task_id]
        self.assertTrue(late, 'a delivery to a finished target becomes reconsideration work')
        for propagation in late:
            carrier = s[propagation.reconsideration_task_id]
            self.assertEqual((carrier.kind, carrier.parent_task_id, carrier.required),
                             ('reconsideration', propagation.target_task_id, False))
            self.assertEqual(carrier.source_propagation_id, propagation.id)
        validate_records(s.values())

    async def test_a_delivery_whose_target_is_cancelled_is_closed_with_a_reason(self):
        base = await self.validated_branch()
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        controller = self.controller(ReconsideringProvider())
        controller.propagate()
        s = self.repo.snapshot('r')
        self.assertEqual(propagations(s)[0].status, PropagationStatus.DELIVERED)
        controller.close_group('gb', 'FIXTURE')
        controller._deliver_propagations()
        propagation = propagations(self.repo.snapshot('r'))[0]
        self.assertEqual(propagation.status, PropagationStatus.SKIPPED)
        self.assertEqual(propagation.status_reason, 'TARGET_BRANCH_CLOSED')


class ContextTests(ReconsiderationCase):
    async def test_the_context_entry_answers_why_this_assignment_received_this_discovery(self):
        controller, s, base = await self.deliver_to_b()
        propagation = propagations(s)[0]
        assignment = s[propagation.outcome_assignment_id]
        entry = next(e for e in json.loads(assignment.context_json)['propagations']
                     if e['id'] == propagation.id)
        self.assertEqual(entry['action'], 'RECONSIDER')
        self.assertEqual(entry['finding_id'], base.id)
        self.assertEqual(entry['finding_revision'], base.revision)
        self.assertEqual(entry['matched_features'], ['CRITERION:c1'])
        self.assertEqual(entry['score'], 2)
        self.assertEqual(entry['target_task_id'], 'tb')
        self.assertTrue(entry['consumable'])
        self.assertIn(base.claim, entry['insight'])

    async def test_the_delivery_carries_the_insight_and_not_the_other_branch_evidence(self):
        controller, s, base = await self.deliver_to_b()
        assignment = s[propagations(s)[0].outcome_assignment_id]
        context = json.loads(assignment.context_json)
        # Cross-branch knowledge arrives only as the bounded insight the decision recorded.
        self.assertEqual([f['id'] for f in context['findings']], [])
        payload = json.dumps(context['propagations'])
        self.assertNotIn('tool_result', payload)
        self.assertNotIn('arguments_json', payload)

    async def test_validated_knowledge_is_never_injected_without_a_delivery_record(self):
        base = await self.validated_branch()
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        s = self.repo.snapshot('r')
        context = ContextBuilder().build(s, s['tb'], s['b'], s['role:EXPLORER'], (),
                                         assignment_id='probe')
        self.assertNotIn(base.id, context.finding_ids)
        self.assertEqual(context.propagation_ids, ())

    async def test_the_propagation_cap_bounds_what_one_assignment_receives(self):
        await self.validated_branch()
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        self.controller(ReconsideringProvider()).propagate()
        s = self.repo.snapshot('r')
        delivery = propagations(s)[0]
        self.assertEqual(delivery.status, PropagationStatus.DELIVERED)
        full = ContextBuilder().build(s, s['tb'], s['b'], s['role:EXPLORER'], (), assignment_id='p1')
        self.assertEqual(full.propagation_ids, (delivery.id,))
        capped = ContextBuilder(max_propagations=0).build(s, s['tb'], s['b'], s['role:EXPLORER'], (),
                                                          assignment_id='p2')
        self.assertEqual(capped.propagation_ids, ())
        self.assertIn(f'{delivery.id}:COUNT_LIMIT', capped.reasons)


class OutcomeTests(ReconsiderationCase):
    async def outcome(self, value):
        controller, s, base = await self.deliver_to_b(ReconsideringProvider(
            outcome=value, reason=f'branch B says {value}'))
        return s, propagations(s)[0]

    async def test_no_change_is_recorded_with_its_reason(self):
        s, propagation = await self.outcome('NO_CHANGE')
        self.assertEqual(propagation.outcome, ReconsiderationOutcome.NO_CHANGE)
        self.assertEqual(propagation.outcome_reason, 'branch B says NO_CHANGE')
        self.assertIsNone(propagation.follow_up_task_id)

    async def test_applied_is_recorded_with_its_reason(self):
        s, propagation = await self.outcome('APPLIED')
        self.assertEqual(propagation.outcome, ReconsiderationOutcome.APPLIED)
        self.assertIsNone(propagation.follow_up_task_id)

    async def test_follow_up_requested_creates_exactly_one_bounded_controller_task(self):
        s, propagation = await self.outcome('FOLLOW_UP_REQUESTED')
        self.assertEqual(propagation.outcome, ReconsiderationOutcome.FOLLOW_UP_REQUESTED)
        follow = s[propagation.follow_up_task_id]
        self.assertEqual((follow.kind, follow.parent_task_id, follow.required, follow.group_id),
                         ('follow_up', 'tb', False, 'gb'))
        self.assertEqual(follow.source_propagation_id, propagation.id)
        self.assertEqual(len([t for t in tasks_of(s, 'follow_up')]), 1)
        self.assertIn('branch B says FOLLOW_UP_REQUESTED', follow.description)
        validate_records(s.values())

    async def test_silence_is_recorded_as_unreported_and_never_as_agreement(self):
        controller, s, base = await self.deliver_to_b(ReconsideringProvider(silent=True))
        propagation = propagations(s)[0]
        self.assertEqual(propagation.outcome, ReconsiderationOutcome.UNREPORTED)
        self.assertNotEqual(propagation.outcome, ReconsiderationOutcome.NO_CHANGE)
        self.assertIsNone(propagation.follow_up_task_id)
        recorded = [json.loads(e.detail_json) for e in self.repo.inspect('r').events
                    if e.type == EventType.RECONSIDERATION_COMPLETED]
        self.assertTrue(recorded)
        self.assertEqual({r['outcome'] for r in recorded}, {'UNREPORTED'})

    async def test_a_failed_assignment_consumes_nothing(self):
        def refuse(context, tool):
            return done(summary='could not do the work', status='FAILED')
        controller, s, base = await self.deliver_to_b(ReconsideringProvider(explorer=refuse))
        delivery = propagations(s)[0]
        self.assertIsNone(delivery.outcome)
        self.assertEqual((delivery.status, delivery.status_reason),
                         (PropagationStatus.SKIPPED, 'TARGET_FAILED'))


class FollowUpAuthorityTests(ReconsiderationCase):
    async def test_equivalent_follow_up_work_is_not_created_twice(self):
        s, _ = None, None
        base = await self.validated_branch()
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        controller = self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED'))
        await controller.run_until_idle()
        first = self.repo.snapshot('r')
        created = len(tasks_of(first, 'follow_up'))
        self.assertEqual(created, 1)
        # A second settled pass admits nothing further: the knowledge already reached tb.
        await self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED')).run_until_idle()
        self.assertEqual(len(tasks_of(self.repo.snapshot('r'), 'follow_up')), created)

    async def test_the_task_limit_bounds_controller_authored_work(self):
        base = await self.validated_branch(run=run_record(task_limit=6))
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        controller = self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED'))
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        self.assertLessEqual(len(tasks_of(s)), 6)
        self.assertEqual(tasks_of(s, 'follow_up'), [])
        skipped = [json.loads(e.detail_json) for e in self.repo.inspect('r').events
                   if e.type == EventType.PROPAGATION_SKIPPED]
        self.assertIn('TASK_LIMIT', [entry.get('reason') for entry in skipped])
        self.assertTrue([c for c in cycles(s) if c.unresolved])

    async def test_the_cycle_limit_stops_further_reconsideration_work(self):
        # Run one is wave one; opening branch B is wave two; the follow-up wave is refused.
        base = await self.validated_branch(run=run_record(cycle_limit=2))
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        controller = self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED'))
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        self.assertEqual(tasks_of(s, 'follow_up'), [])
        self.assertEqual(s['r'].cycle, 2)
        self.assertTrue([c for c in cycles(s) if c.unresolved],
                        'the unadmitted trigger is recorded against the wave')
        skipped = [json.loads(e.detail_json) for e in self.repo.inspect('r').events
                   if e.type == EventType.PROPAGATION_SKIPPED]
        self.assertIn('CYCLE_LIMIT', [entry.get('reason') for entry in skipped])

    async def test_a_worker_cannot_author_reconsideration_work_through_a_task_request(self):
        base = await self.validated_branch()
        self.open_branch_b(explore('tb', [10, 20], group_id='gb'))
        def request(context, tool):
            payload = {'status': 'SUCCEEDED', 'summary': 'ok', 'task_requests': [
                {'objective': 'reconsider everything', 'description': 'let me schedule this'}]}
            return done(**{k: v for k, v in payload.items() if k not in ('status', 'summary')})
        await self.controller(ReconsideringProvider(explorer=request)).run_until_idle()
        s = self.repo.snapshot('r')
        for task in tasks_of(s):
            self.assertNotEqual(task.objective, 'reconsider everything')
            if task.source_propagation_id:
                self.assertIn(task.kind, ('reconsideration', 'follow_up'))


class AdmissionTests(ReconsiderationCase):
    def test_the_parser_refuses_an_invented_or_host_only_outcome(self):
        role = next(r for r in default_roles() if r.name.value == 'COLLABORATOR')
        for outcome in ('UNREPORTED', 'MAYBE', ''):
            payload = json.dumps({'status': 'SUCCEEDED', 'summary': 'ok', 'reconsiderations': [
                {'propagation_id': 'p1', 'outcome': outcome, 'reason': 'x'}]})
            with self.assertRaises(ValueError):
                parse_output(payload, role, ())

    def test_the_parser_refuses_two_answers_for_one_delivery(self):
        role = next(r for r in default_roles() if r.name.value == 'COLLABORATOR')
        payload = json.dumps({'status': 'SUCCEEDED', 'summary': 'ok', 'reconsiderations': [
            {'propagation_id': 'p1', 'outcome': 'APPLIED', 'reason': 'a'},
            {'propagation_id': 'p1', 'outcome': 'NO_CHANGE', 'reason': 'b'}]})
        with self.assertRaises(ValueError):
            parse_output(payload, role, ())

    def test_a_reviewer_envelope_cannot_carry_a_reconsideration_at_all(self):
        role = next(r for r in default_roles() if r.name.value == 'CRITIC')
        payload = json.dumps({'status': 'SUCCEEDED', 'summary': 'ok', 'reconsiderations': [
            {'propagation_id': 'p1', 'outcome': 'APPLIED', 'reason': 'x'}]})
        with self.assertRaises(ValueError):
            parse_output(payload, role, ())

    async def test_an_answer_to_a_delivery_this_assignment_never_received_is_refused(self):
        controller, s, base = await self.deliver_to_b()
        propagation = propagations(s)[0]
        assignment = s[propagation.outcome_assignment_id]
        result = _envelope([ReconsiderationDraft('r:propagation:999999', 'APPLIED', 'invented')],
                           assignment.id)
        decision = check_assignment_admissibility(assignment, result, s,
                                                  tuple(t.spec for t in TOOLS.values()))
        self.assertFalse(decision.allowed)

    async def test_an_answer_naming_another_branch_delivery_is_refused(self):
        controller, s, base = await self.deliver_to_b()
        propagation = propagations(s)[0]
        assignment = s[propagation.outcome_assignment_id]
        # Pretend the assignment pinned a delivery that belongs to no task of its own.
        forged = replace(assignment, propagation_ids=(), propagation_revisions=())
        result = _envelope([ReconsiderationDraft(propagation.id, 'APPLIED', 'not mine')], forged.id)
        decision = check_assignment_admissibility(forged, result, s,
                                                  tuple(t.spec for t in TOOLS.values()))
        self.assertFalse(decision.allowed)


def _envelope(reconsiderations, assignment_id):
    from swarm.output import ExecutionResult
    return ExecutionResult('SUCCEEDED', 'ok', (), (), (), tuple(reconsiderations), None, None,
                           None, assignment_id, ())


if __name__ == '__main__':
    unittest.main()
