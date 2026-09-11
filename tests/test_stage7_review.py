"""Final review: independence, the PASS/REVISE/REJECT contract, staleness and repair limits."""
import unittest
from dataclasses import replace
from stage5_support import TOOLS
from stage7_support import (CompletingProvider, final_review, final_reviews, omit_support,
                            report_of, results_of, run_with, two_branch_run)
from test_stage7_synthesis import SynthesisFixture, envelope, identity
from swarm.admission import check_assignment_admissibility
from swarm.completion import evaluate_gate, repair_key
from swarm.domain import (AgentStatus, Assignment, AssignmentStatus, Conflict, ConflictKind,
                          DomainError, Finding, FindingStatus, Gap, GateStatus, Result,
                          ResultStatus, RevisionKind, ReviewDecision, ReviewKind, ReviewRecord,
                          RunState, Task, TaskStatus, validate_records)
from swarm.events import EventType
from swarm.finalreview import (admit_final_review, classify, final_review_task, judged,
                               pass_blockers, repair_task, stale_reasons)
from swarm.orchestration import WorkController
from swarm.output import ExecutionResult, ReviewDraft
from swarm.persistence import SQLiteRepository
from swarm.policies import excluded_final_reviewers, excluded_review_agents, review_kind
from swarm.synthesis import admit_result


class ReviewFixture(SynthesisFixture):
    """A candidate result plus a running, independent final-review assignment."""

    def candidate(self, **overrides):
        s = self.ready()
        _, _, result = admit_result(s['asyn'], envelope(**overrides), s, lambda k: 'res-1')
        self.result = self.add(result)
        self.add(replace(self.records['free'], status=AgentStatus.IDLE, assignment_id=None,
                         revision=self.records['free'].revision + 1))
        self.add(replace(self.records['asyn'], status=AssignmentStatus.COMPLETED,
                         revision=self.records['asyn'].revision + 1))
        self.add(replace(self.records['tsyn'], status=TaskStatus.COMPLETED, assignment_id=None,
                         revision=self.records['tsyn'].revision + 1))
        return self.project()

    def reviewing(self, reviewer='judge', **overrides):
        s = self.candidate(**overrides)
        from swarm.domain import Agent
        self.add(Agent(id=reviewer, run_id='r', permissions=('arithmetic',),
                       role_id='role:FINAL_REVIEWER', status=AgentStatus.RUNNING,
                       assignment_id='afin'))
        task = self.add(replace(final_review_task(self.result, lambda k: 'tfin', 'r', s),
                                status=TaskStatus.RUNNING, assignment_id='afin'))
        self.add(Assignment(id='afin', run_id='r', task_id='tfin', agent_id=reviewer,
                            role_id='role:FINAL_REVIEWER', status=AssignmentStatus.RUNNING,
                            provider_key='fake', task_revision=task.revision,
                            input_finding_ids=self.result.finding_ids,
                            input_finding_revisions=self.result.finding_revisions,
                            result_id=self.result.id, result_revision=self.result.revision,
                            criterion_ids=('c1', 'c2'),
                            criterion_hashes=tuple(_hash(c) for c in
                                                   self.records['r'].acceptance_criteria)))
        return self.project()


def _hash(criterion):
    from swarm.context import digest
    from swarm.serialization import encode
    return digest(encode(criterion))


def review_envelope(decision='PASS', *, target='res-1', revision=1, **fields):
    draft = ReviewDraft(target, revision, decision, f'final review {decision}', (),
                        fields.pop('blocking_issues', ()), fields.pop('nonblocking_issues', ()),
                        fields.pop('checks', ()), (), fields.pop('criterion_ids', ()),
                        fields.pop('unsupported_claims', ()))
    return ExecutionResult('SUCCEEDED', 'judged', review=draft, assignment_id='afin', **fields)


class IndependenceTests(unittest.TestCase):
    def test_every_synthesizer_identity_is_excluded(self):
        f = ReviewFixture()
        s = f.candidate()
        self.assertEqual(excluded_final_reviewers(s, 'r'), frozenset({'free'}))

    def test_a_final_review_task_routes_through_the_independence_policy(self):
        f = ReviewFixture()
        s = f.reviewing()
        self.assertEqual(review_kind(s['tfin']), ReviewKind.FINAL)
        self.assertEqual(excluded_review_agents(s['tfin'], s), frozenset({'free'}))

    def test_the_synthesizer_may_not_review_its_own_result(self):
        f = ReviewFixture()
        f.reviewing(reviewer='free')
        with self.assertRaises(DomainError):
            validate_records(list(f.project().values()) + [
                ReviewRecord(id='bad', run_id='r', assignment_id='afin', target_id='res-1',
                             target_revision=1, kind=ReviewKind.FINAL,
                             decision=ReviewDecision.PASS)])

    def test_a_finding_review_may_not_target_a_result(self):
        f = ReviewFixture()
        s = f.reviewing()
        with self.assertRaises(DomainError):
            validate_records(list(s.values()) + [
                ReviewRecord(id='bad', run_id='r', assignment_id='afin', target_id='res-1',
                             target_revision=1, kind=ReviewKind.VALIDATION,
                             decision=ReviewDecision.PASS)])

    def test_a_final_review_may_not_target_a_finding(self):
        f = ReviewFixture()
        s = f.reviewing()
        with self.assertRaises(DomainError):
            validate_records(list(s.values()) + [
                ReviewRecord(id='bad', run_id='r', assignment_id='afin', target_id='f1',
                             target_revision=1, kind=ReviewKind.FINAL,
                             decision=ReviewDecision.PASS)])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.f = ReviewFixture()
        self.s = self.f.reviewing()

    def admit(self, result=None):
        return admit_final_review(self.s['afin'], result or review_envelope(), self.s, identity)

    def refusal(self, result):
        with self.assertRaises(ValueError) as caught:
            admit_final_review(self.s['afin'], result, self.s, identity)
        return str(caught.exception)

    def test_the_review_record_names_the_exact_version_and_the_criteria_at_fault(self):
        _, events, record = self.admit(review_envelope('REVISE', criterion_ids=('c2',),
                                                       blocking_issues=('the answer omits c2',)))
        self.assertEqual((record.target_id, record.target_revision), ('res-1', 1))
        self.assertEqual(record.kind, ReviewKind.FINAL)
        self.assertEqual(record.decision, ReviewDecision.REVISE)
        self.assertEqual(record.criterion_ids, ('c2',))
        self.assertEqual(record.verification, 'CURRENT')
        self.assertEqual([str(e.type) for e in events], ['FINAL_REVIEW_COMPLETED'])

    def test_only_the_three_final_decisions_are_admissible(self):
        for decision in ('CHALLENGE', 'FAIL', 'INCONCLUSIVE'):
            with self.subTest(decision=decision):
                self.assertEqual(self.refusal(review_envelope(decision)),
                                 'FINAL_REVIEW_DECISION_NOT_ADMISSIBLE')

    def test_a_review_of_the_wrong_version_is_refused(self):
        self.assertEqual(self.refusal(review_envelope(revision=2)), 'FINAL_REVIEW_TARGET_MISMATCH')
        self.assertEqual(self.refusal(review_envelope(target='res-9')),
                         'FINAL_REVIEW_TARGET_MISMATCH')

    def test_an_unknown_criterion_is_refused(self):
        self.assertEqual(self.refusal(review_envelope('REVISE', criterion_ids=('c9',))),
                         'FINAL_REVIEW_UNKNOWN_CRITERION')

    def test_a_reviewer_cannot_change_a_finding_or_the_run(self):
        records, _, _ = self.admit(review_envelope('REJECT'))
        self.assertEqual([type(r).__name__ for r in records], ['ReviewRecord'])

    def test_the_admissibility_check_pins_the_result_version(self):
        decision = check_assignment_admissibility(self.s['afin'], review_envelope(), self.s)
        self.assertTrue(decision.allowed, decision.reason)
        self.f.records['res-1'] = replace(self.s['res-1'], status=ResultStatus.SUPERSEDED,
                                          revision=2)
        moved = self.f.project()
        self.assertEqual(check_assignment_admissibility(moved['afin'], review_envelope(), moved).reason,
                         'RESULT_VERSION_CHANGED')


class StaleReviewTests(unittest.TestCase):
    def setUp(self):
        self.f = ReviewFixture()
        self.s = self.f.reviewing()

    def test_a_review_of_current_support_is_not_stale(self):
        self.assertEqual(stale_reasons(self.s['afin'], self.s), ())

    def test_support_invalidated_during_review_makes_it_stale(self):
        self.f.records['f2'] = replace(self.s['f2'], status=FindingStatus.INVALIDATED, revision=5)
        s = self.f.project()
        reasons = stale_reasons(s['afin'], s)
        self.assertTrue(any(r.startswith('SUPPORT_INVALIDATED') for r in reasons), reasons)
        _, events, record = admit_final_review(s['afin'], review_envelope(), s, identity)
        self.assertTrue(record.verification.startswith('STALE: '))
        self.assertIn('FINAL_REVIEW_STALE', [str(e.type) for e in events])

    def test_support_whose_revision_moved_during_review_makes_it_stale(self):
        """Still validated, but no longer the revision the reviewer was given."""
        self.f.records['f2'] = replace(self.s['f2'], revision=self.s['f2'].revision + 1)
        s = self.f.project()
        reasons = stale_reasons(s['afin'], s)
        self.assertTrue(any(r.startswith('SUPPORT_REVISION_CHANGED: f2') for r in reasons), reasons)
        record = admit_final_review(s['afin'], review_envelope(), s, identity)[2]
        self.assertTrue(record.verification.startswith('STALE: '))
        self.assertTrue(pass_blockers(s['res-1'], s, 'r', evaluate_gate(s, 'r'), reasons))

    def test_a_conflict_opened_during_review_makes_it_stale(self):
        self.f.add(Conflict(id='k1', run_id='r', finding_ids=('f1', 'f2'), finding_revisions=(1, 1),
                            kind=ConflictKind.DECLARED_CONTRADICTION, signature='sig',
                            reason='contested'))
        s = self.f.project()
        self.assertIn('CONFLICT_OPENED: k1', stale_reasons(s['afin'], s))

    def test_an_unrelated_change_does_not_make_the_review_stale(self):
        self.f.task('tz', group_id='ga', acceptance_criterion_ids=('c1',))
        s = self.f.project()
        self.assertEqual(stale_reasons(s['afin'], s), ())


class PassRecheckTests(unittest.TestCase):
    """PASS is necessary and never sufficient."""

    def setUp(self):
        self.f = ReviewFixture()
        self.s = self.f.reviewing()
        self.review = admit_final_review(self.s['afin'], review_envelope(), self.s, identity)[2]

    def test_a_current_pass_has_no_blockers(self):
        gate = evaluate_gate(self.s, 'r')
        self.assertEqual(pass_blockers(self.s['res-1'], self.s, 'r', gate), ())

    def test_support_invalidated_after_the_review_blocks_completion(self):
        self.f.records['f2'] = replace(self.s['f2'], status=FindingStatus.INVALIDATED, revision=5)
        s = self.f.project()
        gate = evaluate_gate(s, 'r')
        blockers = pass_blockers(s['res-1'], s, 'r', gate)
        self.assertTrue(any(b.startswith('SUPPORT_INVALIDATED') for b in blockers), blockers)

    def test_a_result_that_covers_no_required_criterion_blocks_completion(self):
        """A version whose own coverage lost a required criterion cannot complete the run,
        whatever the reviewer said and whatever the gate says about knowledge at large."""
        from swarm.domain import ResultCoverage
        hollow = replace(self.s['res-1'],
                         coverage=(ResultCoverage(criterion_id='c1', finding_ids=('f1',)),
                                   ResultCoverage(criterion_id='c2', finding_ids=())))
        self.f.records['res-1'] = hollow
        s = self.f.project()
        blockers = pass_blockers(hollow, s, 'r', evaluate_gate(s, 'r'))
        self.assertIn('REQUIRED_CRITERION_UNSUPPORTED: c2', blockers)

    def test_a_result_missing_a_required_criterion_entirely_blocks_completion(self):
        trimmed = replace(self.s['res-1'],
                          coverage=self.s['res-1'].coverage[:1], criterion_ids=('c1',))
        self.f.records['res-1'] = trimmed
        s = self.f.project()
        self.assertIn('REQUIRED_CRITERION_NOT_IN_RESULT: c2',
                      pass_blockers(trimmed, s, 'r', evaluate_gate(s, 'r')))

    def test_a_conflict_opened_after_the_review_blocks_completion(self):
        self.f.add(Conflict(id='k1', run_id='r', finding_ids=('f1', 'f2'), finding_revisions=(1, 1),
                            kind=ConflictKind.DECLARED_CONTRADICTION, signature='sig',
                            reason='contested'))
        s = self.f.project()
        self.assertTrue(pass_blockers(s['res-1'], s, 'r', evaluate_gate(s, 'r')))


class ClassificationTests(unittest.TestCase):
    """The controller decides what a revision requires; the reviewer only locates it."""

    def setUp(self):
        self.f = ReviewFixture()
        self.s = self.f.reviewing()
        self.gate = evaluate_gate(self.s, 'r')

    def classify(self, **fields):
        review = admit_final_review(self.s['afin'], review_envelope('REVISE', **fields),
                                    self.s, identity)[2]
        return classify(review, self.s['res-1'], self.s, 'r', self.gate)

    def test_a_wording_complaint_over_intact_knowledge_is_presentation(self):
        verdict = self.classify(blocking_issues=('the ordering is confusing',))
        self.assertEqual(verdict.revision_kind, RevisionKind.PRESENTATION)

    def test_naming_a_criterion_the_result_already_covers_is_presentation(self):
        verdict = self.classify(criterion_ids=('c2',),
                                blocking_issues=('the c2 conclusion is not stated',))
        self.assertEqual(verdict.revision_kind, RevisionKind.PRESENTATION)

    def test_an_unsupported_claim_is_an_evidence_defect(self):
        verdict = self.classify(unsupported_claims=('the totals were also cross-checked',))
        self.assertEqual(verdict.revision_kind, RevisionKind.EVIDENCE)

    def test_a_gate_that_no_longer_holds_is_an_evidence_defect(self):
        self.f.records['f2'] = replace(self.s['f2'], status=FindingStatus.INVALIDATED, revision=5)
        self.s = self.f.project()
        self.gate = evaluate_gate(self.s, 'r')
        verdict = self.classify(blocking_issues=('the ordering is confusing',))
        self.assertEqual(verdict.revision_kind, RevisionKind.EVIDENCE)
        self.assertTrue(any(r.startswith('GATE_') for r in verdict.reasons))

    def test_a_complaint_naming_nothing_the_record_confirms_is_neither(self):
        review = admit_final_review(self.s['afin'], review_envelope('REJECT'), self.s, identity)[2]
        verdict = classify(review, self.s['res-1'], self.s, 'r', self.gate)
        self.assertEqual(verdict.revision_kind, RevisionKind.NONE)
        self.assertEqual(verdict.reasons, ('NO_CONFIRMED_DEFECT',))


class RepairAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.f = ReviewFixture()
        self.s = self.f.reviewing()
        self.review = admit_final_review(self.s['afin'],
                                         review_envelope('REVISE', criterion_ids=('c2',)),
                                         self.s, identity)[2]

    def test_a_repair_task_carries_its_full_provenance(self):
        gap = Gap(criterion_id='c2', reason='UNSUPPORTED')
        task = repair_task(gap, self.review, lambda k: 'trep', 'r', self.s, round_number=1)
        self.assertEqual(task.kind, 'repair')
        self.assertEqual(task.acceptance_criterion_ids, ('c2',))
        self.assertEqual(task.source_review_id, self.review.id)
        self.assertEqual(task.source_result_id, 'res-1')
        self.assertEqual(task.outcome, repair_key(gap, self.review.id))
        self.assertIn('round 1', task.description)
        self.assertTrue(task.required)

    def test_repair_work_requires_the_evidence_its_verifier_needs(self):
        task = repair_task(Gap(criterion_id='c2', reason='UNSUPPORTED'), self.review,
                           lambda k: 'trep', 'r', self.s)
        self.assertEqual(task.required_tools, ('arithmetic',))

    def test_repair_keys_separate_gate_gaps_from_review_gaps(self):
        gap = Gap(criterion_id='c2', reason='UNSUPPORTED')
        self.assertNotEqual(repair_key(gap, None), repair_key(gap, self.review.id))
        self.assertTrue(repair_key(gap, None).startswith('GATE#'))


class IndependenceExhaustionTests(unittest.IsolatedAsyncioTestCase):
    """No independent final reviewer must prevent completion, never permit self-review."""

    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def test_a_run_without_an_independent_final_reviewer_exhausts(self):
        two_branch_run(self.repo)
        seen = []
        def retire_the_pool(role, context):
            # The moment the synthesizer starts, every other unbranched identity leaves.
            if role != 'synthesizer' or seen:
                return
            seen.append(role)
            from swarm.domain import Agent, AgentStatus, transition
            from swarm.events import EventDraft, EventType
            snapshot = self.repo.snapshot('r')
            for agent in sorted((a for a in snapshot.values() if isinstance(a, Agent)
                                 and a.group_id is None and a.status == AgentStatus.IDLE),
                                key=lambda a: a.id):
                disabled = transition(agent, AgentStatus.DISABLED)
                self.repo.commit('r', [disabled], [EventDraft(type=EventType.RECORD_CHANGED,
                                                              record_id=disabled.id,
                                                              record_revision=disabled.revision)])
        provider = CompletingProvider(before=retire_the_pool)
        s = await WorkController(self.repo, 'r', {'fake': provider}, TOOLS).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertEqual(s['r'].stop_reason, 'NO_INDEPENDENT_FINAL_REVIEWER')
        self.assertEqual(final_reviews(s), [])
        self.assertIsNone(s['r'].result_id)
        candidate = results_of(s)[0]
        self.assertEqual(candidate.status, ResultStatus.CANDIDATE)
        self.assertIsNone(candidate.review_id)


class VerdictRecordTests(unittest.TestCase):
    def setUp(self):
        self.f = ReviewFixture()
        self.s = self.f.reviewing()

    def test_a_judged_result_records_the_review_and_the_revision_kind(self):
        review = admit_final_review(self.s['afin'], review_envelope('REVISE'), self.s, identity)[2]
        revised = judged(self.s['res-1'], ResultStatus.REVISED, review, RevisionKind.PRESENTATION)
        self.assertEqual(revised.status, ResultStatus.REVISED)
        self.assertEqual(revised.review_id, review.id)
        self.assertEqual(revised.decision, ReviewDecision.REVISE)
        self.assertEqual(revised.answer, self.s['res-1'].answer)

    def test_a_run_accepts_at_most_one_result(self):
        review = admit_final_review(self.s['afin'], review_envelope('PASS'), self.s, identity)[2]
        first = judged(self.s['res-1'], ResultStatus.ACCEPTED, review, RevisionKind.NONE)
        second_review = ReviewRecord(id='rev-2', run_id='r', assignment_id='afin',
                                     target_id='res-2', target_revision=1, kind=ReviewKind.FINAL,
                                     decision=ReviewDecision.PASS)
        second = replace(first, id='res-2', version=2, revision=1, review_id='rev-2',
                         supersedes_id='res-1')
        records = [r for r in self.s.values() if r.id != 'res-1']
        with self.assertRaises(DomainError):
            validate_records(records + [review, second_review, first, second])

    def test_an_accepted_result_requires_a_passing_review(self):
        review = admit_final_review(self.s['afin'], review_envelope('REVISE'), self.s, identity)[2]
        bad = judged(self.s['res-1'], ResultStatus.ACCEPTED, review, RevisionKind.NONE)
        with self.assertRaises(DomainError):
            validate_records([r for r in self.s.values() if r.id != 'res-1'] + [review, bad])


if __name__ == '__main__':
    unittest.main()
