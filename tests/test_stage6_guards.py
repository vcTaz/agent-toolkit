"""Guards that a first mutation battery showed no test was exercising.

Each test here isolates one guard so that disabling it fails *this* test rather than being
masked by a stronger check that happens to fire first.
"""
import json
import unittest
from dataclasses import replace
from stage5_support import TOOLS, agent, explore, findings, run_record, seed, setup_run
from stage6_support import Fixture, ReconsideringProvider, cycles, propagations, tasks_of
from swarm.admission import check_assignment_admissibility
from swarm.context import ContextBuilder
from swarm.cycles import measure_branch
from swarm.domain import (Agent, AgentGroup, Conflict, ConflictKind, ConflictStatus, Cycle,
                          CycleStatus, DomainError, FindingStatus, Propagation, PropagationKind,
                          PropagationStatus, ReconsiderationOutcome, RoleName, Task, TaskStatus,
                          validate_records)
from swarm.events import EventDraft, EventType
# The Stage-5/6 subject is the work engine: these tests drive admitted work, review
# and circulation to quiescence. Whether the run is then finished is the Stage-7 run
# workflow, exercised in the Stage-7 suite against ``WorkController`` above this layer.
from swarm.engine import WorkEngine
from swarm.output import ExecutionResult, ReconsiderationDraft
from swarm.persistence import SQLiteRepository
from swarm.propagation import (RECONSIDERATION_KIND, admissible_follow_up, delivery_key,
                               knowledge_units, retractions)
from swarm.roles import role_id


def insight(identity, *, target, key='k', revision=1, status=PropagationStatus.SELECTED,
            finding='fa', group='gb', **fields):
    return Propagation(id=identity, run_id='r', kind=PropagationKind.INSIGHT, knowledge_key=key,
                       knowledge_revision=revision, canonical_finding_id=finding,
                       source_finding_ids=(finding,), target_task_id=target, target_group_id=group,
                       delivery_key=delivery_key(PropagationKind.INSIGHT, key, revision, target),
                       status=status, **fields)


def two_branch_fixture(**task_fields):
    f = Fixture()
    f.group('ga', 'a')
    f.group('gb', 'b')
    f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
    f.task('tb', group_id='gb', **task_fields)
    f.finding('fa', 'ta', 'sum([1, 2]) = 3')
    return f


class EligibilityGuardTests(unittest.TestCase):
    """Propagation follows the projection, and the projection must agree with status."""

    def test_knowledge_absent_from_the_projection_is_not_offered(self):
        # Consolidation has not yet published this fact; routing must not race ahead of it.
        f = two_branch_fixture()
        snapshot = f.project()
        state = next(r for r in snapshot.values() if r.id == 'state')
        snapshot['state'] = replace(state, validated_findings=(), revision=state.revision + 1)
        self.assertEqual(knowledge_units(snapshot, 'r'), ())

    def test_a_projection_still_listing_a_withdrawn_claim_does_not_make_it_eligible(self):
        f = two_branch_fixture()
        snapshot = f.project()
        snapshot['fa'] = replace(snapshot['fa'], status=FindingStatus.INVALIDATED, revision=2)
        # The projection is deliberately left stale; status is still the authority.
        self.assertEqual(knowledge_units(snapshot, 'r'), ())

    def test_a_projection_listing_a_merely_critiqued_claim_does_not_make_it_eligible(self):
        """A CRITIQUED claim is a live consolidation candidate, so it reaches the status
        check rather than being filtered out earlier. Only VALIDATED may propagate."""
        f = two_branch_fixture()
        snapshot = f.project()
        snapshot['fa'] = replace(snapshot['fa'], status=FindingStatus.CRITIQUED, revision=2)
        state = snapshot['state']
        snapshot['state'] = replace(state, validated_findings=('fa',), candidate_findings=(),
                                    revision=state.revision + 1)
        self.assertEqual(knowledge_units(snapshot, 'r'), ())


class ProgressComponentTests(unittest.TestCase):
    """Each progress component is isolated by removing the ones that would mask it."""

    def uncriteried(self):
        """No criteria, so the coverage component is empty and cannot mask anything."""
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED, acceptance_criterion_ids=())
        return f

    def signature(self, fixture):
        return measure_branch(fixture.project(), 'r', fixture.records['ga']).signature

    def test_promotion_alone_counts_as_progress(self):
        """The claim and its evidence are unchanged, so only the validated set moves."""
        f = self.uncriteried()
        f.finding('fa', 'ta', 'sum([1, 2]) = 3', status=FindingStatus.CRITIQUED, criterion_ids=())
        before = self.signature(f)
        f.records['fa'] = replace(f.records['fa'], status=FindingStatus.VALIDATED, revision=2)
        self.assertNotEqual(self.signature(f), before)

    def test_a_resolved_conflict_alone_counts_as_progress(self):
        f = self.uncriteried()
        f.group('gb', 'b')
        f.task('tb', group_id='gb', status=TaskStatus.COMPLETED, acceptance_criterion_ids=())
        f.finding('fa', 'ta', 'sum([1, 2]) = 3', criterion_ids=())
        f.finding('fb', 'tb', 'sum([2, 1]) = 3', numbers=(2, 1), criterion_ids=())
        f.add(Conflict(id='k1', run_id='r', finding_ids=('fa', 'fb'), finding_revisions=(1, 1),
                       kind=ConflictKind.DECLARED_CONTRADICTION, signature='s', reason='fixture'))
        before = self.signature(f)
        f.records['k1'] = replace(f.records['k1'], status=ConflictStatus.RESOLVED,
                                  resolution='FIXTURE', resolved_at='2026-09-09T00:00:00+00:00',
                                  revision=2)
        self.assertNotEqual(self.signature(f), before)


class InvariantGuardTests(unittest.TestCase):
    def snapshot(self, *records):
        f = two_branch_fixture()
        for record in records:
            f.records[record.id] = record
        return f.project().values()

    def test_a_consumed_delivery_without_an_outcome_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            validate_records(self.snapshot(
                insight('p1', target='tb', status=PropagationStatus.CONSUMED)))
        self.assertIn('reconsideration outcome', str(caught.exception))

    def test_an_outcome_on_a_delivery_that_was_never_consumed_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            validate_records(self.snapshot(
                insight('p1', target='tb', outcome=ReconsiderationOutcome.APPLIED)))
        self.assertIn('only a consumed delivery', str(caught.exception))

    def test_follow_up_work_without_a_follow_up_outcome_is_refused(self):
        f = two_branch_fixture()
        f.task('follow', group_id='gb', kind='follow_up')
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.CONSUMED,
                                  outcome=ReconsiderationOutcome.NO_CHANGE,
                                  follow_up_task_id='follow')
        with self.assertRaises(DomainError) as caught:
            validate_records(f.project().values())
        self.assertIn('FOLLOW_UP_REQUESTED', str(caught.exception))

    def test_a_retraction_must_name_the_delivery_it_retracts(self):
        f = two_branch_fixture()
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.DELIVERED)
        f.records['p2'] = replace(insight('p2', target='tb', key='k2'),
                                  kind=PropagationKind.RETRACTION)
        with self.assertRaises(DomainError) as caught:
            validate_records(f.project().values())
        self.assertIn('retraction names the delivery', str(caught.exception))

    def test_an_insight_may_not_claim_to_retract_something(self):
        f = two_branch_fixture()
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.DELIVERED)
        f.records['p2'] = insight('p2', target='tb', key='k2', retracts_id='p1')
        with self.assertRaises(DomainError) as caught:
            validate_records(f.project().values())
        self.assertIn('retraction names the delivery', str(caught.exception))

    def test_two_cycles_cannot_share_a_number(self):
        f = two_branch_fixture()
        for identity in ('c1', 'c2'):
            f.records[identity] = Cycle(id=identity, run_id='r', number=1, trigger='INITIAL',
                                        status=CycleStatus.CLOSED, ended_at='2026-09-09T00:00:00+00:00')
        with self.assertRaises(DomainError) as caught:
            validate_records(f.project().values())
        self.assertIn('cycle numbers are unique', str(caught.exception))

    def test_two_cycles_cannot_be_open_at_once(self):
        f = two_branch_fixture()
        for index, identity in enumerate(('c1', 'c2'), start=1):
            f.records[identity] = Cycle(id=identity, run_id='r', number=index, trigger='INITIAL')
        with self.assertRaises(DomainError) as caught:
            validate_records(f.project().values())
        self.assertIn('at most one open cycle', str(caught.exception))


class PersistenceGuardTests(unittest.TestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)
        # Every record in its initial lifecycle state, so the repository accepts the seed.
        f = Fixture()
        f.group('ga', 'a')
        f.group('gb', 'b')
        f.task('ta', group_id='ga')
        f.task('tb', group_id='gb')
        f.finding('fa', 'ta', 'sum([1, 2]) = 3', status=FindingStatus.PROPOSED)
        records = list(f.records.values())
        self.repo.commit('r', records, [EventDraft(type=EventType.RECORD_CHANGED, record_id=r.id,
                                                   record_revision=r.revision) for r in records])
        self.delivery = insight('p1', target='tb')
        self.commit(self.delivery)

    def commit(self, *records):
        self.repo.commit('r', records, [EventDraft(type=EventType.RECORD_CHANGED, record_id=r.id,
                                                   record_revision=r.revision) for r in records])

    def test_a_recorded_decision_cannot_be_rewritten(self):
        for change in ({'score': 99}, {'target_task_id': 'ta'}, {'matched_features': ('TAG:x',)},
                       {'knowledge_revision': 9}, {'insight': 'something else'}):
            with self.assertRaises(DomainError) as caught:
                self.commit(replace(self.delivery, revision=2, **change))
            self.assertIn('propagation decisions are immutable', str(caught.exception))

    def test_a_recorded_outcome_cannot_be_replaced(self):
        delivered = replace(self.delivery, revision=2, status=PropagationStatus.DELIVERED)
        self.commit(delivered)
        consumed = replace(delivered, revision=3, status=PropagationStatus.CONSUMED,
                           outcome=ReconsiderationOutcome.NO_CHANGE, outcome_reason='stands')
        self.commit(consumed)
        with self.assertRaises(DomainError) as caught:
            self.commit(replace(consumed, revision=4, outcome=ReconsiderationOutcome.APPLIED))
        self.assertIn('write-once', str(caught.exception))

    def test_cycle_work_is_append_only(self):
        cycle = Cycle(id='cy', run_id='r', number=1, trigger='INITIAL', task_ids=('ta', 'tb'))
        self.commit(cycle)
        with self.assertRaises(DomainError) as caught:
            self.commit(replace(cycle, revision=2, task_ids=('tb',)))
        self.assertIn('append-only', str(caught.exception))
        with self.assertRaises(DomainError) as caught:
            self.commit(replace(cycle, revision=2, trigger='NEW_KNOWLEDGE'))
        self.assertIn('immutable', str(caught.exception))


class FollowUpGuardTests(unittest.TestCase):
    def consumed(self, **fields):
        f = two_branch_fixture(status=TaskStatus.COMPLETED)
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.CONSUMED,
                                  outcome=ReconsiderationOutcome.FOLLOW_UP_REQUESTED,
                                  outcome_reason='needs a recheck', **fields)
        return f

    def test_work_for_knowledge_that_is_no_longer_current_is_refused(self):
        f = self.consumed()
        snapshot = f.project()
        self.assertIsNone(admissible_follow_up(snapshot['p1'], RECONSIDERATION_KIND, snapshot, 'r'))
        snapshot['fa'] = replace(snapshot['fa'], status=FindingStatus.INVALIDATED, revision=2)
        self.assertEqual(admissible_follow_up(snapshot['p1'], RECONSIDERATION_KIND, snapshot, 'r'),
                         'KNOWLEDGE_NOT_CURRENT')

    def test_a_second_delivery_of_the_same_fact_does_not_earn_a_second_task(self):
        """Equivalence is by fact and target, not by which delivery carried it."""
        f = self.consumed()
        f.task('carrier', group_id='gb', kind=RECONSIDERATION_KIND, source_propagation_id='p1')
        f.records['fa'] = replace(f.records['fa'], revision=2)
        f.records['p2'] = insight('p2', target='tb', revision=2,
                                  status=PropagationStatus.CONSUMED,
                                  outcome=ReconsiderationOutcome.FOLLOW_UP_REQUESTED,
                                  outcome_reason='again')
        snapshot = f.project()
        self.assertEqual(admissible_follow_up(snapshot['p2'], RECONSIDERATION_KIND, snapshot, 'r'),
                         'DUPLICATE_FOLLOW_UP')


class RetractionGuardTests(unittest.TestCase):
    def test_a_delivery_that_was_never_received_is_closed_without_a_notice(self):
        f = two_branch_fixture()
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.SELECTED)
        snapshot = f.project()
        snapshot['fa'] = replace(snapshot['fa'], status=FindingStatus.INVALIDATED, revision=2)
        records, _ = retractions(snapshot, 'r', lambda kind: 'notice', 1)
        self.assertEqual([r.id for r in records], ['p1'])
        self.assertEqual(records[0].status, PropagationStatus.RETRACTED)
        self.assertEqual([r for r in records if r.retracts_id], [])

    def test_a_received_delivery_does_get_a_notice(self):
        f = two_branch_fixture()
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.DELIVERED)
        snapshot = f.project()
        snapshot['fa'] = replace(snapshot['fa'], status=FindingStatus.INVALIDATED, revision=2)
        records, _ = retractions(snapshot, 'r', lambda kind: 'notice', 1)
        self.assertEqual([r.retracts_id for r in records if r.retracts_id], ['p1'])

    def test_the_notice_key_depends_only_on_the_delivery_it_retracts(self):
        """A retry that reruns the same routing must not manufacture a second notice."""
        f = two_branch_fixture()
        f.records['p1'] = insight('p1', target='tb', status=PropagationStatus.DELIVERED)
        snapshot = f.project()
        snapshot['fa'] = replace(snapshot['fa'], status=FindingStatus.INVALIDATED, revision=2)
        keys = {retractions(snapshot, 'r', lambda kind: 'notice', cycle, reason)[0][1].delivery_key
                for cycle, reason in ((1, 'FIRST_PASS'), (4, 'SECOND_PASS'))}
        self.assertEqual(len(keys), 1)


class DeliveryVisibilityTests(unittest.TestCase):
    """Only a delivery that was actually delivered is owed an answer."""

    def test_only_a_delivered_propagation_is_consumable(self):
        from swarm.propagation import for_task
        f = two_branch_fixture()
        f.task('carrier', group_id='gb')
        states = {'sel': PropagationStatus.SELECTED, 'del': PropagationStatus.DELIVERED,
                  'skip': PropagationStatus.SKIPPED, 'ret': PropagationStatus.RETRACTED}
        for index, (identity, status) in enumerate(states.items()):
            f.records[identity] = insight(identity, target='carrier', key=f'k{index}',
                                          status=status)
        f.records['con'] = insight('con', target='carrier', key='kc',
                                   status=PropagationStatus.CONSUMED,
                                   outcome=ReconsiderationOutcome.NO_CHANGE,
                                   outcome_reason='already answered')
        snapshot = f.project()
        entries = for_task(snapshot, snapshot['carrier'])
        self.assertEqual({p.id for p, consumable in entries if consumable}, {'del'})


class AdmissionGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def delivered(self, **builder):
        setup_run(self.repo, [explore('ta', [1, 2, 3], group_id='ga')],
                  [agent('a', 'ga'), agent('critic'), agent('validator')],
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',))])
        await WorkEngine(self.repo, 'r', {'fake': ReconsideringProvider()},
                             TOOLS).run_until_idle()
        seed(self.repo, 'r', Agent(id='b', run_id='r', group_id='gb', permissions=('arithmetic',)),
             AgentGroup(id='gb', run_id='r', agent_ids=('b',), task_ids=('tb',)),
             explore('tb', [10, 20], group_id='gb'))
        controller = WorkEngine(self.repo, 'r', {'fake': ReconsideringProvider()}, TOOLS,
                                    context_builder=ContextBuilder(**builder))
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r')

    def envelope(self, assignment_id, *drafts, **fields):
        return ExecutionResult('SUCCEEDED', 'ok', (), (), (), tuple(drafts), None, None, None,
                               assignment_id, (), **fields)

    @staticmethod
    def running(snapshot, assignment, **assignment_fields):
        """A working copy in which one settled assignment is live again, with every pin it
        holds restored, so the proposal checks are reached instead of an earlier staleness
        check short-circuiting first."""
        from swarm.domain import AgentStatus, AssignmentStatus
        live = replace(snapshot[assignment.id], status=AssignmentStatus.RUNNING, ended_at=None,
                       **assignment_fields)
        task = snapshot[live.task_id]
        working = dict(snapshot)
        working[live.id] = live
        working[task.id] = replace(task, status=TaskStatus.RUNNING, assignment_id=live.id,
                                   revision=live.task_revision)
        working[live.agent_id] = replace(snapshot[live.agent_id], status=AgentStatus.RUNNING,
                                         assignment_id=live.id, role_id=live.role_id)
        for identity, revision in zip(live.input_finding_ids, live.input_finding_revisions):
            working[identity] = replace(snapshot[identity], revision=revision)
        for identity, revision in zip(live.propagation_ids, live.propagation_revisions):
            working[identity] = replace(snapshot[identity], revision=revision)
        return working, live

    async def test_a_delivery_the_context_dropped_is_not_consumed(self):
        """The cap is a real boundary: an assignment settles only what it actually saw."""
        controller, s = await self.delivered(max_propagations=0)
        for propagation in propagations(s):
            self.assertIsNone(propagation.outcome)
            self.assertNotEqual(propagation.status, PropagationStatus.CONSUMED)
        for record in s.values():
            if hasattr(record, 'propagation_ids'):
                self.assertEqual(record.propagation_ids, ())

    async def test_an_answer_to_another_branch_delivery_is_refused_even_when_pinned(self):
        """Pinning is not authority: the delivery must be one this task owes an answer for."""
        controller, s = await self.delivered()
        consumed = next(p for p in propagations(s) if p.status == PropagationStatus.CONSUMED)
        live_delivery = replace(consumed, status=PropagationStatus.DELIVERED, outcome=None,
                                outcome_reason='', outcome_assignment_id=None)
        # An assignment on the *source* branch pins the delivery routed to the other branch.
        other = next(a for a in s.values() if hasattr(a, 'role_version') and a.task_id == 'ta'
                     and a.role_id == role_id(RoleName.EXPLORER))
        working, live = self.running(s, other, propagation_ids=(consumed.id,),
                                     propagation_revisions=(live_delivery.revision,))
        working[consumed.id] = live_delivery
        decision = check_assignment_admissibility(
            live, self.envelope(live.id, ReconsiderationDraft(consumed.id, 'APPLIED', 'not mine')),
            working, tuple(t.spec for t in TOOLS.values()))
        self.assertEqual(decision.reason, 'RECONSIDERATION_TARGET_INELIGIBLE')

    async def test_an_answer_that_is_owed_but_was_never_pinned_is_refused(self):
        controller, s = await self.delivered()
        consumed = next(p for p in propagations(s) if p.status == PropagationStatus.CONSUMED)
        # The delivery is owed again, but this assignment never pinned it.
        working, live = self.running(s, s[consumed.outcome_assignment_id],
                                     propagation_ids=(), propagation_revisions=())
        working[consumed.id] = replace(consumed, status=PropagationStatus.DELIVERED,
                                       outcome=None, outcome_reason='', outcome_assignment_id=None)
        decision = check_assignment_admissibility(
            live, self.envelope(live.id, ReconsiderationDraft(consumed.id, 'APPLIED', 'x')),
            working, tuple(t.spec for t in TOOLS.values()))
        self.assertEqual(decision.reason, 'RECONSIDERATION_NOT_IN_CONTEXT')

    async def test_a_reviewer_assignment_is_refused_a_reconsideration_even_if_hand_built(self):
        controller, s = await self.delivered()
        review = next(a for a in s.values() if hasattr(a, 'role_version')
                      and a.role_id == role_id(RoleName.VALIDATOR))
        working, live = self.running(s, review)
        decision = check_assignment_admissibility(
            live, self.envelope(live.id, ReconsiderationDraft('p1', 'APPLIED', 'x')),
            working, tuple(t.spec for t in TOOLS.values()))
        self.assertEqual(decision.reason, 'RECONSIDERATION_FORBIDDEN')


class CycleGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def test_re_entering_an_exhausted_run_opens_no_further_wave(self):
        setup_run(self.repo, [explore('ta', [1, 2, 3], group_id='ga')],
                  [agent('a', 'ga'), agent('critic'), agent('validator')],
                  run=run_record(cycle_limit=1),
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',))])
        for _ in range(2):
            await WorkEngine(self.repo, 'r', {'fake': ReconsideringProvider()},
                                 TOOLS).run_until_idle()
        s = self.repo.snapshot('r')
        self.assertEqual(s['r'].cycle, 1)
        self.assertEqual([c.number for c in cycles(s)], [1])


if __name__ == '__main__':
    unittest.main()
