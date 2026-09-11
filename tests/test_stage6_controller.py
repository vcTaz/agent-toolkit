"""Targeted retraction, cycle accounting, branch stopping, resource integrity, integration."""
import json
import unittest
from dataclasses import replace
from stage5_support import TOOLS, agent, explore, findings, run_record, seed, setup_run, state_of
from stage6_support import (Fixture, ReconsideringProvider, cycles, groups_of, propagations,
                            retractions_of, tasks_of)
from swarm.cycles import (branch_stop_reason, coverage_gaps, cycle_triggers, measure_branch,
                          progress_records)
from swarm.domain import (Agent, AgentGroup, BranchStop, Conflict, ConflictKind, ConflictStatus,
                          FindingStatus, GroupStatus, Propagation, PropagationKind,
                          PropagationStatus, ReconsiderationOutcome, ReviewDecision, ReviewKind,
                          ReviewRecord, Task, TaskStatus, validate_records)
from swarm.events import EventType
# The Stage-5/6 subject is the work engine: these tests drive admitted work, review
# and circulation to quiescence. Whether the run is then finished is the Stage-7 run
# workflow, exercised in the Stage-7 suite against ``WorkController`` above this layer.
from swarm.engine import WorkEngine
from swarm.persistence import SQLiteRepository
from swarm.policies import reserved_for_review
from swarm.propagation import PropagationPolicy


class ControllerCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def controller(self, provider=None, **kwargs):
        return WorkEngine(self.repo, 'r', {'fake': provider or ReconsideringProvider()},
                              TOOLS, **kwargs)

    async def validated_branch(self, *, run=None, provider=None, task=None):
        setup_run(self.repo, [task or explore('ta', [1, 2, 3], group_id='ga')],
                  [agent('a', 'ga'), agent('critic'), agent('validator')], run=run,
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',))])
        await self.controller(provider).run_until_idle()
        return next(f for f in findings(self.repo.snapshot('r'))
                    if f.status == FindingStatus.VALIDATED)

    def open_branch(self, group_id, agent_id, *tasks):
        seed(self.repo, 'r',
             Agent(id=agent_id, run_id='r', group_id=group_id, permissions=('arithmetic',)),
             AgentGroup(id=group_id, run_id='r', agent_ids=(agent_id,),
                        task_ids=tuple(t.id for t in tasks)), *tasks)

    def events(self, kind):
        return [json.loads(e.detail_json) for e in self.repo.inspect('r').events if e.type == kind]


class RetractionTests(ControllerCase):
    async def delivered_run(self, *, unrelated=False):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        if unrelated:
            # No shared criterion and no shared tag: nothing is ever routed here.
            self.open_branch('gc', 'c', Task(id='tc', run_id='r', objective='unrelated work',
                                             description=json.dumps([7, 7]), group_id='gc',
                                             tags=('other',), required_tools=('arithmetic',)))
        controller = self.controller()
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r'), base

    async def test_only_the_targets_that_received_the_knowledge_are_told(self):
        controller, s, base = await self.delivered_run(unrelated=True)
        carried = [p for p in propagations(s) if p.canonical_finding_id == base.id]
        self.assertTrue(carried)
        self.assertEqual({p.target_task_id for p in carried}, {'tb'})
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        notices = [p for p in retractions_of(after) if p.canonical_finding_id == base.id]
        self.assertEqual([p.target_task_id for p in notices], ['tb'])
        self.assertNotIn('tc', [p.target_task_id for p in retractions_of(after)])
        validate_records(after.values())

    async def test_the_retraction_identifies_the_claim_the_revision_and_the_delivery(self):
        controller, s, base = await self.delivered_run()
        original = next(p for p in propagations(s) if p.canonical_finding_id == base.id)
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        notice = next(p for p in retractions_of(after) if p.retracts_id == original.id)
        self.assertEqual(notice.canonical_finding_id, base.id)
        self.assertEqual(notice.knowledge_revision, original.knowledge_revision)
        self.assertEqual(notice.target_task_id, original.target_task_id)
        self.assertIn('FIXTURE_CORRECTION', notice.insight)
        self.assertIn('INVALIDATED', notice.insight)
        self.assertIn(original.id, notice.insight)
        self.assertEqual(after[original.id].status, PropagationStatus.RETRACTED)
        self.assertEqual(after[original.id].status_reason, 'FIXTURE_CORRECTION')

    async def test_a_retraction_is_authored_by_the_controller_and_never_by_a_worker(self):
        controller, s, base = await self.delivered_run()
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        for notice in retractions_of(after):
            self.assertIsNone(notice.outcome_assignment_id)
            self.assertEqual(notice.kind, PropagationKind.RETRACTION)
        self.assertTrue(self.events(EventType.PROPAGATION_RETRACTED))

    async def test_repeating_the_retraction_creates_nothing_further(self):
        controller, s, base = await self.delivered_run()
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        first = len(propagations(self.repo.snapshot('r')))
        self.assertEqual(controller.retract('AGAIN'), ())
        controller.retract('AND_AGAIN')
        self.assertEqual(len(propagations(self.repo.snapshot('r'))), first)

    async def test_retracting_one_fact_leaves_other_valid_knowledge_delivered(self):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        seed(self.repo, 'r', explore('ta2', [4, 4], group_id='ga'),
             replace(self.repo.get('r', 'ga'), task_ids=('ta', 'ta2'),
                     revision=self.repo.get('r', 'ga').revision + 1))
        controller = self.controller()
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        other = next(f for f in findings(s) if f.status == FindingStatus.VALIDATED
                     and f.id != base.id and f.task_id == 'ta2')
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        for propagation in propagations(after):
            if propagation.canonical_finding_id == other.id:
                self.assertNotEqual(propagation.status, PropagationStatus.RETRACTED)
        self.assertEqual(after[other.id].status, FindingStatus.VALIDATED)

    def test_retracting_an_old_revision_leaves_a_newer_delivery_of_the_same_fact_alone(self):
        """The same fact, revalidated at a higher revision, is a different delivery."""
        from swarm.propagation import delivery_key, retractions
        f = Fixture()
        f.group('ga', 'a')
        f.group('gb', 'b')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.task('tb', group_id='gb')
        current = f.finding('fa', 'ta', 'sum([1, 2]) = 3', revision=5)
        for identity, revision in (('old', 3), ('new', 5)):
            f.add(Propagation(id=identity, run_id='r', kind=PropagationKind.INSIGHT,
                              knowledge_key='k', knowledge_revision=revision,
                              canonical_finding_id='fa', target_task_id='tb', target_group_id='gb',
                              delivery_key=delivery_key(PropagationKind.INSIGHT, 'k', revision, 'tb'),
                              status=PropagationStatus.DELIVERED))
        records, _ = retractions(f.project(), 'r', lambda kind: 'notice', 1)
        changed = {r.id: r for r in records}
        self.assertIn('old', changed)
        self.assertEqual(changed['old'].status, PropagationStatus.RETRACTED)
        self.assertNotIn('new', changed)
        self.assertEqual([r.retracts_id for r in records if r.retracts_id], ['old'])

    async def test_an_in_flight_assignment_holding_a_retracted_delivery_is_stale(self):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        controller = self.controller()
        fired = []
        def before(role, context):
            if context['task']['id'] != 'tb' or fired:
                return
            fired.append(True)
            controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        controller.providers['fake'] = ReconsideringProvider(before=before)
        await controller.run_until_idle()
        rejected = [entry.get('reason') for entry in self.events(EventType.OUTPUT_REJECTED)]
        self.assertIn('PROPAGATION_CHANGED', rejected)

    async def test_invalidated_knowledge_leaves_future_context_and_reopens_the_gap(self):
        controller, s, base = await self.delivered_run()
        self.assertTrue(state_of(s).validated_findings)
        for finding in findings(s):
            if finding.status == FindingStatus.VALIDATED:
                controller.invalidate_finding(finding.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        self.assertEqual(state_of(after).validated_findings, ())
        gaps = coverage_gaps(after, 'r')
        self.assertEqual([g['criterion_id'] for g in gaps], ['c1'])
        self.assertEqual(gaps[0]['reason'], 'COVERAGE_LOST')
        self.assertTrue(gaps[0]['invalidated_support'])
        controller._final_settle()
        self.assertTrue(self.events(EventType.COVERAGE_GAP))

    async def test_a_downstream_dependent_is_still_invalidated_transitively(self):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        seed(self.repo, 'r', explore('tdep', [3, 4], group_id='ga', required_finding_ids=(base.id,),
                                     dependency_ids=('ta',)),
             replace(self.repo.get('r', 'ga'), task_ids=('ta', 'tdep'),
                     revision=self.repo.get('r', 'ga').revision + 1))
        controller = self.controller()
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        dependent = next(f for f in findings(s) if base.id in f.dependency_finding_ids)
        removed = controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        self.assertIn(dependent.id, removed)
        self.assertEqual(self.repo.get('r', dependent.id).status, FindingStatus.INVALIDATED)


class BranchProgressTests(unittest.TestCase):
    """Progress is measured from what a branch changed, not from what it said."""

    def branch(self):
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fa', 'ta', 'sum([1, 2]) = 3')
        return f

    def signature(self, fixture):
        return measure_branch(fixture.project(), 'r', fixture.records['ga']).signature

    def test_a_new_nonduplicate_candidate_counts_as_progress(self):
        f = self.branch()
        before = self.signature(f)
        f.task('ta2', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fb', 'ta2', 'sum([9, 9]) = 18', numbers=(9, 9), total=18,
                  status=FindingStatus.PROPOSED)
        self.assertNotEqual(self.signature(f), before)

    def test_an_exact_duplicate_is_not_progress(self):
        f = self.branch()
        before = self.signature(f)
        f.task('ta2', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fdup', 'ta2', 'sum([1, 2]) = 3', status=FindingStatus.PROPOSED)
        self.assertEqual(self.signature(f), before)

    def test_rewording_within_the_deterministic_duplicate_signature_is_not_progress(self):
        f = self.branch()
        before = self.signature(f)
        f.task('ta2', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fword', 'ta2', '  SUM([1, 2])   =   3 ', status=FindingStatus.PROPOSED)
        self.assertEqual(self.signature(f), before)

    def test_a_repeated_no_change_answer_is_not_progress(self):
        f = self.branch()
        before = self.signature(f)
        f.task('tb', group_id='ga')
        for index in range(3):
            f.add(Propagation(id=f'p{index}', run_id='r', kind=PropagationKind.INSIGHT,
                              knowledge_key='k', knowledge_revision=1, canonical_finding_id='fa',
                              target_task_id='tb', target_group_id='ga', delivery_key=f'key{index}',
                              status=PropagationStatus.CONSUMED,
                              outcome=ReconsiderationOutcome.NO_CHANGE,
                              outcome_reason='still fine'))
        self.assertEqual(self.signature(f), before)

    def test_newly_verified_evidence_counts_as_progress(self):
        f = self.branch()
        before = self.signature(f)
        f.add(ReviewRecord(id='rev1', run_id='r', assignment_id='as-1', target_id='fa',
                           target_revision=1, decision=ReviewDecision.PASS, kind=ReviewKind.VALIDATION,
                           evidence=(replace(f.records['fa'].evidence[0], verified=True),)))
        self.assertNotEqual(self.signature(f), before)

    def test_a_resolved_conflict_counts_as_progress(self):
        f = self.branch()
        f.group('gb', 'b')
        f.task('tb', group_id='gb', status=TaskStatus.COMPLETED)
        f.finding('fb', 'tb', 'sum([2, 1]) = 3', numbers=(2, 1))
        f.add(Conflict(id='k1', run_id='r', finding_ids=('fa', 'fb'), finding_revisions=(1, 1),
                       kind=ConflictKind.DECLARED_CONTRADICTION, signature='s', reason='fixture'))
        before = self.signature(f)
        f.records['k1'] = replace(f.records['k1'], status=ConflictStatus.RESOLVED,
                                  resolution='FIXTURE', resolved_at='2026-09-09T00:00:00+00:00',
                                  revision=2)
        self.assertNotEqual(self.signature(f), before)

    def test_idle_cycles_accumulate_only_while_nothing_changes(self):
        f = self.branch()
        snapshot = f.project()
        group = snapshot['ga']
        for expected in (0, 1, 2):
            group, event, _ = progress_records(snapshot, 'r', group, 1)
            snapshot = dict(snapshot, ga=group)
            self.assertEqual(group.idle_cycles, expected)
            self.assertEqual(json.loads(event.detail_json)['progress'], expected == 0)
        f.records['ga'] = group
        f.task('ta2', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fnew', 'ta2', 'sum([5, 5]) = 10', numbers=(5, 5), total=10)
        moved, _, _ = progress_records(f.project(), 'r', f.records['ga'], 2)
        self.assertEqual(moved.idle_cycles, 0)


class BranchStopTests(ControllerCase):
    def stopped_branch(self, idle):
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga')
        f.records['ga'] = replace(f.records['ga'], idle_cycles=idle, revision=2)
        return f

    def test_two_idle_cycles_stop_the_branch_and_one_does_not(self):
        for idle, expected in ((1, None), (2, BranchStop.NO_PROGRESS)):
            f = self.stopped_branch(idle)
            snapshot = f.project()
            reason = branch_stop_reason(snapshot, 'r', snapshot['ga'],
                                        measure_branch(snapshot, 'r', snapshot['ga']))
            self.assertEqual(reason, expected)

    def test_a_branch_with_open_work_is_kept_while_it_may_still_contribute(self):
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga')
        snapshot = f.project()
        self.assertIsNone(branch_stop_reason(snapshot, 'r', snapshot['ga'],
                                             measure_branch(snapshot, 'r', snapshot['ga'])))

    def test_covered_criteria_stop_redundant_open_work(self):
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.task('ta2', group_id='ga')
        f.finding('fa', 'ta', 'sum([1, 2]) = 3')
        snapshot = f.project()
        self.assertEqual(branch_stop_reason(snapshot, 'r', snapshot['ga'],
                                            measure_branch(snapshot, 'r', snapshot['ga'])),
                         BranchStop.CRITERION_COVERED)

    async def test_stopping_one_branch_cancels_only_its_own_work(self):
        setup_run(self.repo, [explore('ta', [1, 2], group_id='ga'),
                              explore('tb', [3, 4], group_id='gb')],
                  [agent('a', 'ga'), agent('b', 'gb'), agent('critic'), agent('validator')],
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',)),
                          AgentGroup(id='gb', run_id='r', agent_ids=('b',), task_ids=('tb',))])
        controller = self.controller()
        s = self.repo.snapshot('r')
        controller._stop_branch(s['ga'], BranchStop.NO_PROGRESS)
        after = self.repo.snapshot('r')
        self.assertEqual(after['ga'].status, GroupStatus.CLOSED)
        self.assertEqual(after['ga'].stop_reason, 'NO_PROGRESS')
        self.assertEqual(after['ta'].status, TaskStatus.CANCELLED)
        self.assertIn('NO_PROGRESS', after['ta'].outcome)
        # The independent branch is untouched.
        self.assertEqual(after['gb'].status, GroupStatus.ACTIVE)
        self.assertEqual(after['tb'].status, TaskStatus.PENDING)
        validate_records(after.values())

    async def test_a_stopped_branch_keeps_the_knowledge_it_established(self):
        base = await self.validated_branch()
        controller = self.controller()
        controller._stop_branch(self.repo.snapshot('r')['ga'], BranchStop.NO_PROGRESS)
        after = self.repo.snapshot('r')
        self.assertEqual(after[base.id].status, FindingStatus.VALIDATED)
        self.assertIn(base.id, state_of(after).validated_findings)
        terminated = self.events(EventType.BRANCH_TERMINATED)
        self.assertEqual(terminated[0]['reason'], 'NO_PROGRESS')
        self.assertIn(base.id, terminated[0]['validated_findings'])

    async def test_waves_that_add_nothing_end_the_branch_on_the_no_progress_rule(self):
        # A generous cycle limit, so the branches stop on measured progress rather than on
        # the wave count. Follow-up work is done, but it establishes no new knowledge.
        base = await self.validated_branch(run=run_record(cycle_limit=5))
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        await self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED')).run_until_idle()
        s = self.repo.snapshot('r')
        stopped = [g for g in groups_of(s) if g.status == GroupStatus.CLOSED]
        self.assertTrue(stopped, 'a branch that stops contributing is closed, not left dormant')
        self.assertEqual({g.stop_reason for g in stopped}, {'NO_PROGRESS'})
        self.assertEqual({g.idle_cycles for g in stopped}, {s['r'].no_progress_limit})
        idle = [e for e in self.events(EventType.BRANCH_PROGRESS) if not e['progress']]
        self.assertTrue(idle, 'the idle waves are recorded with the measurement that decided it')
        self.assertLess(s['r'].cycle, s['r'].cycle_limit)


class CycleTests(ControllerCase):
    async def test_the_initial_wave_is_cycle_one_and_is_recorded_and_closed(self):
        await self.validated_branch()
        s = self.repo.snapshot('r')
        recorded = cycles(s)
        self.assertEqual(recorded[0].number, 1)
        self.assertEqual(recorded[0].trigger, 'INITIAL')
        self.assertEqual(recorded[0].status.value, 'CLOSED')
        self.assertIsNotNone(recorded[0].ended_at)
        self.assertEqual(s['r'].cycle, 1)

    async def test_a_reconsideration_wave_records_its_trigger_and_admitted_work(self):
        await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        await self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED')).run_until_idle()
        s = self.repo.snapshot('r')
        waves = [c for c in cycles(s) if c.trigger != 'INITIAL']
        self.assertTrue(waves)
        for wave in waves:
            self.assertTrue(wave.trigger_ids)
            self.assertTrue(wave.reason)
            self.assertTrue(wave.task_ids)
            for identity in wave.task_ids:
                self.assertIn(s[identity].kind, ('reconsideration', 'follow_up'))
                self.assertIn(s[identity].source_propagation_id, wave.trigger_ids)
        follow_wave = next(c for c in waves
                           if any(s[i].kind == 'follow_up' for i in c.task_ids))
        self.assertIn('FOLLOW_UP_REQUESTED', follow_wave.reason)
        self.assertTrue(self.events(EventType.CYCLE_STARTED))
        self.assertTrue(self.events(EventType.CYCLE_COMPLETED))

    async def test_a_wave_never_opens_without_admissible_work(self):
        await self.validated_branch()
        s = self.repo.snapshot('r')
        self.assertEqual(cycle_triggers(s, 'r'), ())
        self.assertEqual(s['r'].cycle, 1)

    async def test_cycle_numbers_are_unique_and_only_one_wave_is_open_at_a_time(self):
        await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        await self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED')).run_until_idle()
        s = self.repo.snapshot('r')
        numbers = [c.number for c in cycles(s)]
        self.assertEqual(numbers, sorted(set(numbers)))
        self.assertLessEqual(len([c for c in cycles(s) if c.status.value == 'OPEN']), 1)
        validate_records(s.values())


class ResourceTests(ControllerCase):
    def reservation_fixture(self, *, ready=True):
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fa', 'ta', 'sum([1, 2]) = 3', status=FindingStatus.CRITIQUED)
        f.task('review', kind='validation', target_finding_id='fa', required=True,
               required_finding_ids=('fa',), priority=5,
               dependency_ids=() if ready else ('blocker',))
        if not ready:
            f.task('blocker', group_id='ga')
        f.task('optional', kind='reconsideration', required=False, priority=1)
        f.add(Agent(id='reviewer', run_id='r', permissions=('arithmetic',)))
        return f

    def test_a_due_review_reserves_the_identity_optional_work_would_have_taken(self):
        f = self.reservation_fixture()
        snapshot = f.project()
        reserved = reserved_for_review(snapshot['optional'], snapshot, ('arithmetic',), ('fake',))
        self.assertTrue(reserved, 'optional work must not consume the last independent reviewer')
        # Required work and review work are never deprioritized by the reservation.
        self.assertEqual(reserved_for_review(snapshot['ta'], snapshot, ('arithmetic',), ('fake',)),
                         frozenset())
        self.assertEqual(reserved_for_review(snapshot['review'], snapshot, ('arithmetic',), ('fake',)),
                         frozenset())

    def test_a_review_that_cannot_run_reserves_nobody(self):
        """Otherwise optional work would deadlock behind a review that never dispatches."""
        f = self.reservation_fixture(ready=False)
        snapshot = f.project()
        self.assertEqual(reserved_for_review(snapshot['optional'], snapshot, ('arithmetic',), ('fake',)),
                         frozenset())

    async def test_routing_makes_no_provider_request(self):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        before = self.repo.get('r', 'r').provider_requests
        class Refuse:
            async def generate(self, request):
                raise AssertionError('routing must not call a provider')
        controller = WorkEngine(self.repo, 'r', {'fake': Refuse()}, TOOLS)
        decisions = controller.propagate()
        controller.retract('probe')
        self.assertTrue(decisions)
        self.assertEqual(self.repo.get('r', 'r').provider_requests, before)

    async def test_budgets_stay_run_level_authoritative_across_a_propagating_run(self):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        controller = self.controller()
        await controller.run_until_idle()
        run = self.repo.get('r', 'r')
        self.assertEqual(controller.budget.requests, run.provider_requests)
        self.assertEqual(controller.budget.tool_calls, run.tool_calls)
        self.assertLessEqual(run.provider_requests, run.provider_request_limit)

    async def test_two_controllers_cannot_deliver_the_same_knowledge_twice(self):
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        first = self.controller().propagate()
        second = self.controller().propagate()
        self.assertTrue(first)
        self.assertEqual(second, ())
        keys = [p.delivery_key for p in propagations(self.repo.snapshot('r'))]
        self.assertEqual(len(keys), len(set(keys)))

    async def test_the_target_cap_bounds_fanout_through_the_controller(self):
        base = await self.validated_branch()
        for index in range(5):
            self.open_branch(f'g{index}', f'w{index}',
                             explore(f't{index}', [index, index], group_id=f'g{index}'))
        self.controller(propagation_policy=PropagationPolicy(max_targets=2)).propagate()
        s = self.repo.snapshot('r')
        carried = [p for p in propagations(s) if p.canonical_finding_id == base.id]
        self.assertEqual(len(carried), 2)


class IntegrationTests(ControllerCase):
    async def test_the_full_stage_six_loop_from_discovery_to_retraction(self):
        """Branch A validates a fact; it reaches branch B; B reconsiders and asks for
        follow-up work; the fact is then invalidated and only B is told."""
        base = await self.validated_branch()
        self.open_branch('gb', 'b', explore('tb', [10, 20], group_id='gb'))
        self.open_branch('gc', 'c', Task(id='tc', run_id='r', objective='unrelated', group_id='gc',
                                         description=json.dumps([7, 7]), tags=('other',),
                                         required_tools=('arithmetic',)))
        controller = self.controller(ReconsideringProvider(outcome='FOLLOW_UP_REQUESTED'))
        await controller.run_until_idle()
        s = self.repo.snapshot('r')

        carried = next(p for p in propagations(s) if p.canonical_finding_id == base.id
                       and p.kind == PropagationKind.INSIGHT)
        self.assertEqual(carried.target_task_id, 'tb')
        self.assertEqual(carried.matched_features, ('CRITERION:c1',))
        self.assertEqual(carried.outcome.value, 'FOLLOW_UP_REQUESTED')
        follow = s[carried.follow_up_task_id]
        self.assertEqual((follow.kind, follow.group_id, follow.required),
                         ('follow_up', 'gb', False))
        self.assertGreaterEqual(s['r'].cycle, 2)

        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        notice = next(p for p in retractions_of(after) if p.retracts_id == carried.id)
        self.assertEqual(notice.target_task_id, 'tb')
        self.assertEqual([p.target_task_id for p in retractions_of(after)
                          if p.canonical_finding_id == base.id], ['tb'])
        self.assertEqual(after[base.id].status, FindingStatus.INVALIDATED)
        self.assertNotIn(base.id, state_of(after).validated_findings)
        # Branch C was never a recipient and is untouched by any of it.
        self.assertEqual(after['gc'].status, GroupStatus.ACTIVE)
        self.assertEqual([p.id for p in propagations(after) if p.target_task_id == 'tc'], [])
        validate_records(after.values())

        recorded = [e.type for e in self.repo.inspect('r').events]
        for expected in (EventType.PROPAGATION_SELECTED, EventType.CROSS_POLLINATION,
                         EventType.PROPAGATION_DELIVERED, EventType.RECONSIDERATION_STARTED,
                         EventType.RECONSIDERATION_COMPLETED, EventType.CYCLE_STARTED,
                         EventType.CYCLE_COMPLETED, EventType.BRANCH_PROGRESS,
                         EventType.PROPAGATION_RETRACTED):
            self.assertIn(expected, recorded)


if __name__ == '__main__':
    unittest.main()
