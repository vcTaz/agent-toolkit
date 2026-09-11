"""The run state machine, terminal outcomes, and budget/reviewer reservation."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from stage5_support import TOOLS, agent, explore
from stage7_support import (CompletingProvider, TWO_CRITERIA, one_branch_run, report_of,
                            results_of, run_with, setup_completing_run, two_branch_run)
from test_stage7_gate import GateFixture
from swarm.completion import evaluate_gate
from swarm.domain import (ACTIVE_RUN_STATES, Agent, AgentGroup, BranchStop, DomainError, Finding,
                          FindingStatus, GateStatus, GroupStatus, RUN_TRANSITIONS, Result,
                          ResultStatus, RunState, TERMINAL_RUN_STATES, Task, TaskStatus,
                          transition, validate_records)
from swarm.engine import WorkEngine
from swarm.events import EventType
from swarm.orchestration import WorkController
from swarm.persistence import SQLiteRepository, StorageError
from swarm.policies import (BudgetPolicy, COMPLETION_REQUESTS, completion_imminent,
                            completion_reserve, outstanding_reviews, reserved_for_review)
from swarm.workflow import Guard, check, configured, decomposed, reviews_settled, wave_settled


class TransitionTests(unittest.TestCase):
    """Every legal step is legal, every other step is refused, terminals absorb."""

    def run_in(self, state, **fields):
        record = GateFixture(**fields).records['r']
        for step in {RunState.RECEIVED: (),
                     RunState.DECOMPOSING: (RunState.DECOMPOSING,),
                     RunState.EXPLORING: (RunState.DECOMPOSING, RunState.EXPLORING),
                     RunState.EVALUATING: (RunState.DECOMPOSING, RunState.EXPLORING,
                                           RunState.EVALUATING),
                     RunState.CONSOLIDATING: (RunState.DECOMPOSING, RunState.EXPLORING,
                                              RunState.EVALUATING, RunState.CONSOLIDATING),
                     RunState.SYNTHESIZING: (RunState.DECOMPOSING, RunState.EXPLORING,
                                             RunState.EVALUATING, RunState.CONSOLIDATING,
                                             RunState.SYNTHESIZING),
                     RunState.FINAL_REVIEW: (RunState.DECOMPOSING, RunState.EXPLORING,
                                             RunState.EVALUATING, RunState.CONSOLIDATING,
                                             RunState.SYNTHESIZING, RunState.FINAL_REVIEW)}[state]:
            record = transition(record, step)
        return record

    def test_every_declared_transition_is_taken(self):
        for state, targets in RUN_TRANSITIONS.items():
            for target in targets:
                with self.subTest(step=f'{state}->{target}'):
                    self.assertEqual(transition(self.run_in(state), target).state, target)

    def test_every_undeclared_transition_is_refused(self):
        for state in ACTIVE_RUN_STATES:
            for target in RunState:
                if target in RUN_TRANSITIONS[state]:
                    continue
                with self.subTest(step=f'{state}->{target}'), self.assertRaises(DomainError):
                    transition(self.run_in(state), target)

    def test_terminal_states_are_absorbing(self):
        for state in TERMINAL_RUN_STATES:
            run = replace(self.run_in(RunState.FINAL_REVIEW), state=state)
            for target in RunState:
                with self.subTest(state=state, target=target), self.assertRaises(DomainError):
                    transition(run, target)

    def test_completed_is_reachable_only_through_final_review(self):
        self.assertEqual([s for s, t in RUN_TRANSITIONS.items() if RunState.COMPLETED in t],
                         [RunState.FINAL_REVIEW])

    def test_a_transition_bumps_the_revision_and_leaves_the_original(self):
        run = self.run_in(RunState.RECEIVED)
        moved = transition(run, RunState.DECOMPOSING)
        self.assertEqual((run.state, run.revision), (RunState.RECEIVED, 1))
        self.assertEqual(moved.revision, 2)


class GuardTests(unittest.TestCase):
    def test_a_run_without_a_required_criterion_is_not_configured(self):
        from swarm.domain import Criterion
        optional = (Criterion(id='c1', description='x', required=False),)
        f = GateFixture(criteria=optional)
        self.assertEqual(configured(f.project(), 'r').reason, 'NO_REQUIRED_CRITERION')

    def test_a_run_with_no_task_graph_is_not_decomposed(self):
        from swarm.domain import Run, Role
        from swarm.roles import default_roles
        records = {'r': run_with()}
        self.assertEqual(decomposed(records, 'r').reason, 'NO_TASKS')

    def test_open_exploration_work_blocks_the_evaluating_step(self):
        f = GateFixture()
        settled = f.covered()
        self.assertTrue(wave_settled(settled, 'r').allowed)
        f.task('tc', group_id='ga', acceptance_criterion_ids=('c1',))
        guard = wave_settled(f.project(), 'r')
        self.assertFalse(guard.allowed)
        self.assertEqual(guard.reason, 'EXPLORATION_WORK_OPEN: tc')

    def test_open_review_work_blocks_the_consolidating_step(self):
        f = GateFixture()
        settled = f.covered()
        self.assertTrue(reviews_settled(settled, 'r').allowed)
        f.task('tv', kind='validation', target_finding_id='f1', acceptance_criterion_ids=('c1',))
        guard = reviews_settled(f.project(), 'r')
        self.assertFalse(guard.allowed)
        self.assertEqual(guard.reason, 'REVIEW_WORK_OPEN: tv')

    def test_an_assignment_in_flight_blocks_both_settle_steps(self):
        f = GateFixture()
        f.covered()
        from swarm.domain import Assignment, AssignmentStatus
        f.add(Assignment(id='live', run_id='r', task_id='ta', agent_id='free',
                         role_id='role:EXPLORER', status=AssignmentStatus.CREATED))
        s = f.project()
        self.assertEqual(wave_settled(s, 'r').reason, 'ASSIGNMENTS_IN_FLIGHT')
        self.assertEqual(reviews_settled(s, 'r').reason, 'ASSIGNMENTS_IN_FLIGHT')

    def test_a_run_with_a_candidate_result_is_ready_for_final_review(self):
        from swarm.workflow import candidate_ready
        f = GateFixture()
        s = f.covered()
        self.assertEqual(candidate_ready(s, 'r').reason, 'NO_CANDIDATE_RESULT')

    def test_the_synthesis_attempt_limit_is_a_guard(self):
        from swarm.workflow import synthesis_dispatchable
        f = GateFixture(synthesis_attempts=1, synthesis_attempt_limit=1)
        s = f.covered()
        gate = evaluate_gate(s, 'r')
        self.assertEqual(gate.status, GateStatus.READY)
        self.assertEqual(synthesis_dispatchable(s, 'r', gate).reason, 'SYNTHESIS_ATTEMPT_LIMIT')

    def test_a_completed_run_must_name_its_accepted_result(self):
        f = GateFixture()
        s = f.covered()
        f.records['r'] = replace(s['r'], state=RunState.COMPLETED, revision=2)
        with self.assertRaises(DomainError):
            validate_records(f.project().values())

    def test_a_guard_refusal_names_the_illegal_step(self):
        f = GateFixture()
        s = f.covered()
        self.assertIn('ILLEGAL_TRANSITION', check(s, 'r', RunState.COMPLETED).reason)


class StoredTransitionTests(unittest.TestCase):
    """Storage applies the machine too: a hand-built successor cannot skip a phase."""

    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)
        from swarm.events import EventDraft, EventType
        self.event = lambda r: EventDraft(type=EventType.RECORD_CHANGED, record_id=r.id,
                                          record_revision=r.revision)
        self.run = run_with()
        self.repo.commit('r', [self.run], [self.event(self.run)])

    def commit(self, record):
        self.repo.commit('r', [record], [self.event(record)])

    def test_a_legal_step_is_stored(self):
        self.commit(transition(self.run, RunState.DECOMPOSING))
        self.assertEqual(self.repo.get('r', 'r').state, RunState.DECOMPOSING)

    def test_a_skipped_phase_is_refused_by_storage(self):
        skipped = replace(self.run, state=RunState.EXPLORING, revision=2)
        with self.assertRaises(DomainError):
            self.commit(skipped)

    def test_a_terminal_state_stays_terminal_in_storage(self):
        self.commit(transition(self.run, RunState.EXHAUSTED))
        revived = replace(self.repo.get('r', 'r'), state=RunState.EXPLORING, revision=3)
        with self.assertRaises(DomainError):
            self.commit(revived)

    def test_acceptance_criteria_cannot_change_inside_a_run(self):
        rewritten = replace(self.run, acceptance_criteria=(TWO_CRITERIA[0],), revision=2)
        with self.assertRaises(DomainError):
            self.commit(rewritten)


class RunOutcomeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def controller(self, provider=None, **kwargs):
        return WorkController(self.repo, 'r', {'fake': provider or CompletingProvider()},
                              TOOLS, **kwargs)

    def events(self, kind):
        import json
        return [json.loads(e.detail_json) for e in self.repo.inspect('r').events if e.type == kind]

    async def test_the_synthesis_attempt_limit_stops_the_run(self):
        two_branch_run(self.repo, run=replace(run_with(), synthesis_attempt_limit=0))
        s = await self.controller().run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertEqual(s['r'].stop_reason, 'SYNTHESIS_ATTEMPT_LIMIT')
        self.assertEqual(results_of(s), [])

    async def test_a_clean_run_completes_with_an_accepted_result(self):
        two_branch_run(self.repo)
        s = await self.controller().run_until_idle()
        self.assertEqual(s['r'].state, RunState.COMPLETED)
        accepted = [r for r in results_of(s) if r.status == ResultStatus.ACCEPTED]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(s['r'].result_id, accepted[0].id)
        self.assertEqual(report_of(s).state, RunState.COMPLETED)

    async def test_a_required_criterion_that_cannot_be_verified_exhausts(self):
        two_branch_run(self.repo)
        s = await self.controller(CompletingProvider(wrong={'tb': 99})).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertIsNone(s['r'].result_id)
        report = report_of(s)
        self.assertEqual([g.criterion_id for g in report.gaps], ['c2'])
        self.assertEqual(report.validated_finding_ids, tuple(
            sorted(f.id for f in s.values() if isinstance(f, Finding)
                   and f.status == FindingStatus.VALIDATED)))

    async def test_an_unusable_configuration_fails_rather_than_exhausts(self):
        task = replace(explore('ta', [1, 2, 3], group_id='ga'), acceptance_criterion_ids=())
        setup_completing_run(self.repo, [task], [agent('a', 'ga'), agent('judge')],
                             run=replace(run_with(), acceptance_criteria=()),
                             groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',),
                                                task_ids=('ta',))])
        s = await self.controller().run_until_idle()
        self.assertEqual(s['r'].state, RunState.FAILED)
        self.assertIn('NO_ACCEPTANCE_CRITERIA', s['r'].stop_reason)
        self.assertEqual(report_of(s).state, RunState.FAILED)

    async def test_a_deadline_with_unresolved_work_exhausts(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        two_branch_run(self.repo, run=replace(run_with(), deadline_at=past))
        s = await self.controller().run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertEqual(s['r'].stop_reason, 'DEADLINE')

    async def test_cancellation_is_its_own_terminal_state(self):
        two_branch_run(self.repo)
        controller = self.controller()
        controller.cancel('OPERATOR_STOP')
        s = await controller.run_until_idle()
        self.assertEqual(s['r'].state, RunState.CANCELLED)
        self.assertEqual(report_of(s).stop_reason, 'OPERATOR_STOP')

    async def test_a_storage_failure_is_failed_and_never_exhausted(self):
        two_branch_run(self.repo)
        controller = self.controller()
        original = self.repo.commit
        calls = []
        def failing(run_id, records, events):
            calls.append(1)
            if len(calls) > 6:
                raise StorageError('disk gone')
            return original(run_id, records, events)
        self.repo.commit = failing
        with self.assertRaises(StorageError):
            await controller.run_until_idle()
        self.repo.commit = original
        self.assertNotEqual(self.repo.get('r', 'r').state, RunState.EXHAUSTED)

    async def test_a_branch_that_contributes_nothing_does_not_terminate_the_run(self):
        """Branch B's claim is rejected; branch A cleanly covers the only required criterion."""
        criteria = (TWO_CRITERIA[0], replace(TWO_CRITERIA[1], required=False))
        two_branch_run(self.repo, run=replace(run_with(criteria), concurrency_limit=2))
        s = await self.controller(CompletingProvider(wrong={'tb': 99})).run_until_idle()
        self.assertEqual(s['r'].state, RunState.COMPLETED)
        rejected = [f for f in s.values() if isinstance(f, Finding)
                    and f.status == FindingStatus.REJECTED]
        self.assertTrue(rejected)
        self.assertEqual([e.criterion_id for e in
                          s[s['r'].result_id].coverage if e.finding_ids], ['c1'])

    async def test_the_terminal_report_carries_the_branch_stop_reasons(self):
        """Branch B's prerequisite cannot run, so the branch closes with a recorded reason."""
        blocked = replace(explore('tb0', [10, 20], group_id='gb'), required_tools=('absent',))
        dependent = replace(explore('tb', [10, 20], group_id='gb'), dependency_ids=('tb0',),
                            acceptance_criterion_ids=('c2',))
        setup_completing_run(self.repo, [explore('ta', [1, 2, 3], group_id='ga'), blocked, dependent],
                             [agent('a', 'ga'), agent('b', 'gb'), agent('critic'),
                              agent('validator'), agent('writer'), agent('judge')],
                             groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',)),
                                     AgentGroup(id='gb', run_id='r', agent_ids=('b',),
                                                task_ids=('tb0', 'tb'))])
        s = await self.controller().run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        closed = [g for g in s.values() if isinstance(g, AgentGroup)
                  and g.status == GroupStatus.CLOSED]
        self.assertEqual([g.stop_reason for g in closed], [str(BranchStop.DEPENDENCY_FAILED)])
        self.assertEqual(report_of(s).branch_stops, ('gb: DEPENDENCY_FAILED',))

    async def test_a_required_gap_exhausts_despite_a_successful_branch(self):
        two_branch_run(self.repo)
        s = await self.controller(CompletingProvider(wrong={'tb': 99})).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        report = report_of(s)
        # Branch A's knowledge survives the run; it is simply not reported as an answer.
        self.assertEqual(len(report.validated_finding_ids), 1)
        self.assertEqual([g.criterion_id for g in report.gaps], ['c2'])

    async def test_the_state_changes_are_recorded_in_order(self):
        two_branch_run(self.repo)
        await self.controller().run_until_idle()
        steps = [(d['from'], d['to']) for d in self.events(EventType.RUN_STATE_CHANGED)]
        self.assertEqual(steps[:4], [('RECEIVED', 'DECOMPOSING'), ('DECOMPOSING', 'EXPLORING'),
                                     ('EXPLORING', 'EVALUATING'), ('EVALUATING', 'CONSOLIDATING')])
        self.assertEqual(steps[-1], ('FINAL_REVIEW', 'COMPLETED'))

    async def test_the_terminal_report_is_written_once(self):
        two_branch_run(self.repo)
        controller = self.controller()
        await controller.run_until_idle()
        self.assertFalse(controller._terminate(RunState.EXHAUSTED, 'again').allowed)


class ReservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def test_the_completion_reserve_covers_synthesis_review_and_owed_reviews(self):
        f = GateFixture()
        s = f.covered()
        self.assertEqual(completion_reserve(s, s['r']), COMPLETION_REQUESTS)
        f.finding('f3', 'ta', 'sum([7]) = 7', numbers=(7,), total=7, criterion_ids=('c1',),
                  status=FindingStatus.PROPOSED)
        s = f.project()
        self.assertEqual(outstanding_reviews(s, s['r']), 1)
        self.assertEqual(completion_reserve(s, s['r']), COMPLETION_REQUESTS + 1)

    def test_optional_work_cannot_consume_the_completion_reserve(self):
        f = GateFixture(provider_request_limit=6, provider_requests=4)
        s = f.covered()
        optional = f.add(replace(f.task('topt', group_id='ga', acceptance_criterion_ids=('c1',)),
                                 required=False))
        required = f.task('treq', group_id='ga', acceptance_criterion_ids=('c1',))
        s = f.project()
        policy = BudgetPolicy()
        self.assertEqual(policy.admit(s['topt'], s).reason, 'BUDGET_RESERVED_OR_EXHAUSTED')
        self.assertTrue(policy.admit(s['treq'], s).allowed)

    def test_a_stopped_run_reserves_nothing(self):
        f = GateFixture(work_stop_reason='CANCELLED')
        s = f.covered()
        self.assertEqual(completion_reserve(s, s['r']), 0)

    def test_completion_is_imminent_once_a_candidate_exists(self):
        f = GateFixture()
        s = f.covered()
        self.assertFalse(completion_imminent(s, s['r']))
        f.records['r'] = replace(s['r'], state=RunState.SYNTHESIZING, revision=2)
        self.assertTrue(completion_imminent(f.project(), f.records['r']))

    def test_the_last_independent_final_reviewer_is_held_back_from_optional_work(self):
        f = GateFixture()
        s = f.covered()
        f.records['r'] = replace(s['r'], state=RunState.SYNTHESIZING, revision=2)
        optional = f.add(replace(f.task('topt', group_id=None, acceptance_criterion_ids=('c1',)),
                                 required=False))
        s = f.project()
        self.assertIn('free', reserved_for_review(s['topt'], s, ('arithmetic',), ('fake',)))

    async def test_the_final_review_still_dispatches_at_the_reserved_capacity(self):
        """The run has room for exactly the synthesis and the final review it needs."""
        two_branch_run(self.repo, run=replace(run_with(), provider_request_limit=12))
        s = await WorkController(self.repo, 'r', {'fake': CompletingProvider()},
                                 TOOLS).run_until_idle()
        self.assertEqual(s['r'].state, RunState.COMPLETED)
        self.assertEqual(s['r'].provider_requests, 12)

    async def test_a_run_without_budget_for_completion_never_claims_ready(self):
        two_branch_run(self.repo, run=replace(run_with(), provider_request_limit=9))
        s = await WorkController(self.repo, 'r', {'fake': CompletingProvider()},
                                 TOOLS).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertEqual(results_of(s), [])


if __name__ == '__main__':
    unittest.main()
