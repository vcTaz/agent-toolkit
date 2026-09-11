"""The synthesis gate: computed readiness, criterion coverage, gaps and repair decisions."""
import unittest
from dataclasses import replace
from stage6_support import Fixture
from stage7_support import OPTIONAL_SECOND, TWO_CRITERIA
from swarm.completion import (COMPLETION_REQUESTS, GateDecision, criterion_readiness,
                              evaluate_gate, gap_records, limitations, repair_admissible,
                              repair_capacity, support_findings, unconsumed_knowledge)
from swarm.domain import (Agent, AgentGroup, Conflict, ConflictKind, ConflictStatus, Criterion,
                          Evidence, Finding, FindingStatus, GateStatus, Gap, Propagation,
                          PropagationKind, PropagationStatus, ReconsiderationOutcome,
                          ReviewDecision, ReviewKind, ReviewRecord, Task, TaskStatus)


class GateFixture(Fixture):
    """A settled two-criterion run built by hand, so the gate is tested without a controller."""

    def __init__(self, criteria=TWO_CRITERIA, **run_fields):
        super().__init__(acceptance_criteria=criteria, **run_fields)
        self.group('ga', 'a')
        self.group('gb', 'b')
        self.add(Agent(id='free', run_id='r', permissions=('arithmetic',)))
        self.task('ta', group_id='ga', status=TaskStatus.COMPLETED, acceptance_criterion_ids=('c1',))
        self.task('tb', group_id='gb', status=TaskStatus.COMPLETED, acceptance_criterion_ids=('c2',))

    def validated(self, identity, task_id, claim, criterion, *, numbers=(1, 2), total=3, **fields):
        finding = self.finding(identity, task_id, claim, numbers=numbers, total=total,
                               criterion_ids=(criterion,), **fields)
        self.verify(finding)
        return finding

    def verify(self, finding):
        """A host-verified passing validation, which is what the gate reads as support."""
        assignment = f'{finding.assignment_id}-rev'
        from swarm.domain import Assignment
        self.add(Assignment(id=assignment, run_id='r', task_id=finding.task_id, agent_id='free',
                            role_id='role:VALIDATOR'))
        review = self.add(ReviewRecord(id=f'{finding.id}-review', run_id='r',
                                       assignment_id=assignment, target_id=finding.id,
                                       target_revision=finding.revision, kind=ReviewKind.VALIDATION,
                                       decision=ReviewDecision.PASS,
                                       evidence=(replace(finding.evidence[0], verified=True),)))
        self.records[finding.id] = replace(finding, review_ids=(review.id,))
        return self.records[finding.id]

    def covered(self):
        self.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        self.validated('f2', 'tb', 'sum([10, 20]) = 30', 'c2', numbers=(10, 20), total=30)
        return self.settle()

    def settle(self):
        """Finish every fixture assignment, so the run reads as a settled wave."""
        from swarm.domain import Assignment, AssignmentStatus
        for record in list(self.records.values()):
            if isinstance(record, Assignment) and record.status == AssignmentStatus.CREATED:
                self.records[record.id] = replace(record, status=AssignmentStatus.COMPLETED,
                                                  revision=record.revision + 1)
        return self.project()


class ReadinessTests(unittest.TestCase):
    def test_all_required_criteria_cleanly_covered_is_ready(self):
        s = GateFixture().covered()
        decision = evaluate_gate(s, 'r')
        self.assertEqual(decision.status, GateStatus.READY)
        self.assertEqual(decision.reasons, ())
        self.assertEqual(decision.support, ('f1', 'f2'))
        self.assertTrue(all(entry.clean for entry in decision.readiness))

    def test_a_missing_criterion_is_not_ready(self):
        f = GateFixture()
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        decision = evaluate_gate(f.project(), 'r')
        self.assertNotEqual(decision.status, GateStatus.READY)
        self.assertIn('CRITERION_UNSUPPORTED: c2', decision.reasons)
        self.assertEqual([g.criterion_id for g in decision.gaps], ['c2'])

    def test_an_invalidated_supporting_finding_is_not_ready(self):
        f = GateFixture()
        s = f.covered()
        f.records['f2'] = replace(s['f2'], status=FindingStatus.INVALIDATED, revision=3)
        decision = evaluate_gate(f.project(), 'r')
        self.assertNotEqual(decision.status, GateStatus.READY)
        self.assertEqual([g.reason for g in decision.gaps], ['COVERAGE_LOST'])

    def test_an_unresolved_required_conflict_is_not_ready(self):
        f = GateFixture()
        f.covered()
        f.validated('f3', 'tb', 'sum([10, 20]) = 31', 'c2', numbers=(10, 20), total=31)
        f.add(Conflict(id='k1', run_id='r', finding_ids=('f2', 'f3'), finding_revisions=(1, 1),
                       kind=ConflictKind.CONTRADICTORY_VALUE, signature='sum:[10, 20]',
                       criterion_ids=('c2',), reason='two totals'))
        decision = evaluate_gate(f.project(), 'r')
        self.assertNotEqual(decision.status, GateStatus.READY)
        self.assertEqual([g.reason for g in decision.gaps], ['CONFLICTED'])
        self.assertEqual(decision.gaps[0].conflict_ids, ('k1',))

    def test_a_conflict_over_a_nonrequired_criterion_does_not_block(self):
        f = GateFixture(criteria=OPTIONAL_SECOND)
        f.covered()
        f.validated('f3', 'tb', 'sum([10, 20]) = 31', 'c2', numbers=(10, 20), total=31)
        f.add(Conflict(id='k1', run_id='r', finding_ids=('f2', 'f3'), finding_revisions=(1, 1),
                       kind=ConflictKind.CONTRADICTORY_VALUE, signature='sum:[10, 20]',
                       criterion_ids=('c2',), reason='two totals'))
        s = f.project()
        decision = evaluate_gate(s, 'r')
        self.assertEqual(decision.status, GateStatus.READY)
        # It is not silently settled either: the contest is carried as a limitation.
        self.assertTrue(any('OPEN CONFLICT k1' in note for note in limitations(s, 'r')))

    def test_outstanding_required_review_blocks_readiness(self):
        f = GateFixture()
        f.covered()
        f.finding('f3', 'ta', 'sum([7]) = 7', numbers=(7,), total=7, criterion_ids=('c1',),
                  status=FindingStatus.PROPOSED)
        decision = evaluate_gate(f.project(), 'r')
        self.assertNotEqual(decision.status, GateStatus.READY)
        self.assertIn('REQUIRED_REVIEW_OUTSTANDING', decision.reasons)

    def test_unsettled_branch_work_blocks_readiness(self):
        f = GateFixture()
        f.covered()
        f.task('tc', group_id='ga', acceptance_criterion_ids=('c1',))
        decision = evaluate_gate(f.project(), 'r')
        self.assertNotEqual(decision.status, GateStatus.READY)
        self.assertIn('BRANCH_WORK_UNSETTLED: tc', decision.reasons)

    def test_unsettled_required_work_blocks_readiness(self):
        """A required review task belongs to no branch, and still holds the gate."""
        f = GateFixture()
        f.covered()
        f.task('tv', kind='validation', target_finding_id='f1', group_id=None,
               acceptance_criterion_ids=('c1',))
        decision = evaluate_gate(f.project(), 'r')
        self.assertNotEqual(decision.status, GateStatus.READY)
        self.assertIn('REQUIRED_WORK_UNSETTLED: tv', decision.reasons)

    def test_support_without_host_verified_evidence_is_not_clean(self):
        f = GateFixture()
        f.finding('f1', 'ta', 'sum([1, 2]) = 3', criterion_ids=('c1',))
        f.validated('f2', 'tb', 'sum([10, 20]) = 30', 'c2', numbers=(10, 20), total=30)
        entries = {e.criterion_id: e for e in criterion_readiness(f.project(), 'r')}
        self.assertEqual(entries['c1'].blocking_gap, 'SUPPORT_UNVERIFIED')
        self.assertEqual(entries['c1'].verified_ids, ())
        self.assertEqual(entries['c2'].verified_ids, ('f2',))

    def test_insufficient_completion_budget_never_claims_ready(self):
        f = GateFixture(provider_request_limit=10, provider_requests=9)
        decision = evaluate_gate(f.covered(), 'r')
        self.assertEqual(decision.status, GateStatus.EXHAUSTED)
        self.assertIn('COMPLETION_BUDGET_INSUFFICIENT', decision.reasons)

    def test_exactly_the_completion_reserve_is_enough(self):
        f = GateFixture(provider_request_limit=10, provider_requests=10 - COMPLETION_REQUESTS)
        self.assertEqual(evaluate_gate(f.covered(), 'r').status, GateStatus.READY)

    def test_a_stopped_run_is_never_ready(self):
        f = GateFixture(work_stop_reason='CANCELLED')
        self.assertEqual(evaluate_gate(f.covered(), 'r').status, GateStatus.EXHAUSTED)


class GapDecisionTests(unittest.TestCase):
    def gap(self, reason='UNSUPPORTED', criterion='c2'):
        return Gap(criterion_id=criterion, reason=reason)

    def test_the_cycle_limit_with_an_unresolved_gap_is_exhausted(self):
        f = GateFixture(cycle=3, cycle_limit=3)
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        decision = evaluate_gate(f.project(), 'r')
        self.assertEqual(decision.status, GateStatus.EXHAUSTED)
        self.assertEqual(decision.repairable, ())

    def test_the_repair_limit_with_an_unresolved_gap_is_exhausted(self):
        f = GateFixture(repair_rounds=2, repair_round_limit=2)
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        s = f.project()
        self.assertEqual(evaluate_gate(s, 'r').status, GateStatus.EXHAUSTED)
        self.assertEqual(repair_admissible(s, 'r', self.gap()).reason, 'REPAIR_LIMIT')

    def test_an_admissible_gap_leaves_the_run_not_ready(self):
        f = GateFixture()
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        decision = evaluate_gate(f.project(), 'r')
        self.assertEqual(decision.status, GateStatus.NOT_READY)
        self.assertEqual([g.criterion_id for g in decision.repairable], ['c2'])

    def test_repair_needs_somewhere_to_run(self):
        f = GateFixture()
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        f.records['free'] = replace(f.records['free'], group_id='ga', revision=2)
        s = f.project()
        self.assertFalse(repair_capacity(s, 'r'))
        self.assertEqual(repair_admissible(s, 'r', self.gap()).reason, 'NO_REPAIR_CAPACITY')
        self.assertEqual(evaluate_gate(s, 'r').status, GateStatus.EXHAUSTED)

    def test_the_task_limit_refuses_repair(self):
        f = GateFixture(task_limit=2)
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        self.assertEqual(repair_admissible(f.project(), 'r', self.gap()).reason, 'TASK_LIMIT')

    def test_budget_reserved_for_completion_refuses_repair(self):
        f = GateFixture(provider_request_limit=8, provider_requests=6)
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        self.assertEqual(repair_admissible(f.project(), 'r', self.gap()).reason, 'BUDGET_EXHAUSTED')

    def test_a_gap_reason_no_work_can_close_is_not_repairable(self):
        f = GateFixture()
        s = f.covered()
        self.assertEqual(repair_admissible(s, 'r', self.gap('SUPPORT_UNVERIFIED')).reason,
                         'GAP_NOT_REPAIRABLE')

    def test_duplicate_repair_for_the_same_gap_is_suppressed(self):
        f = GateFixture()
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        f.task('repair-1', kind='repair', acceptance_criterion_ids=('c2',),
               outcome='GATE#c2#UNSUPPORTED', status=TaskStatus.FAILED)
        self.assertEqual(repair_admissible(f.project(), 'r', self.gap()).reason, 'DUPLICATE_REPAIR')


class SupportSelectionTests(unittest.TestCase):
    def test_support_is_criterion_relevant_and_dependency_closed(self):
        f = GateFixture()
        base = f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        f.validated('f2', 'tb', 'sum([10, 20]) = 30', 'c2', numbers=(10, 20), total=30,
                    dependency_finding_ids=(base.id,))
        f.finding('f9', 'ta', 'unrelated note', criterion_ids=(), status=FindingStatus.VALIDATED)
        self.assertEqual(support_findings(f.project(), 'r'), ('f1', 'f2'))

    def test_knowledge_nobody_consumed_is_still_available_to_synthesis(self):
        f = GateFixture()
        s = f.covered()
        # A delivery that reached branch B and was never answered stays reportable, and the
        # knowledge it carried is still legitimate support.
        f.add(Propagation(id='p1', run_id='r', kind=PropagationKind.INSIGHT, knowledge_key='k',
                          knowledge_revision=1, canonical_finding_id='f1', source_finding_ids=('f1',),
                          target_task_id='tb', target_group_id='gb', delivery_key='dk1',
                          status=PropagationStatus.DELIVERED))
        s = f.project()
        self.assertIn('f1', support_findings(s, 'r'))
        self.assertTrue(any('never answered' in note for note in unconsumed_knowledge(s, 'r')))


class GapRecordTests(unittest.TestCase):
    def test_required_flags_follow_the_criterion_definition(self):
        f = GateFixture(criteria=OPTIONAL_SECOND)
        f.validated('f1', 'ta', 'sum([1, 2]) = 3', 'c1')
        gaps = gap_records(f.project(), 'r')
        self.assertEqual([(g.criterion_id, g.required) for g in gaps], [('c2', False)])

    def test_a_gap_explains_itself(self):
        f = GateFixture()
        s = f.covered()
        f.records['f2'] = replace(s['f2'], status=FindingStatus.INVALIDATED, revision=3)
        gap = gap_records(f.project(), 'r')[0]
        self.assertEqual((gap.criterion_id, gap.reason, gap.invalidated_support),
                         ('c2', 'COVERAGE_LOST', ('f2',)))
        self.assertEqual(gap.key, 'c2:COVERAGE_LOST')


if __name__ == '__main__':
    unittest.main()
