"""Synthesis: deliberate context, provenance, candidate admission, versions and staleness."""
import unittest
from dataclasses import replace
from test_stage7_gate import GateFixture
from swarm.admission import check_assignment_admissibility
from swarm.completion import evaluate_gate
from swarm.context import ContextBuilder, ContextError, digest
from swarm.domain import (AgentStatus, Assignment, AssignmentStatus, DomainError, Finding,
                          FindingStatus, Result, ResultStatus, ReviewDecision, Task, TaskStatus,
                          validate_records)
from swarm.output import ExecutionResult, ResultClaimDraft, ResultDraft
from swarm.persistence import SQLiteRepository
from swarm.serialization import encode
from swarm.synthesis import admit_result, repeated_attempt, stale_support, synthesis_task


def identity(kind, serial=[0]):
    serial[0] += 1
    return f'{kind}-{serial[0]}'


class SynthesisFixture(GateFixture):
    """A gate-ready run plus a running synthesis assignment pinned to its support."""

    def ready(self):
        s = self.covered()
        self.gate = evaluate_gate(s, 'r')
        self.syn = self.add(replace(synthesis_task(lambda k: 'tsyn', 'r', s, self.gate),
                                    status=TaskStatus.RUNNING, assignment_id='asyn'))
        self.assignment = self.add(Assignment(
            id='asyn', run_id='r', task_id='tsyn', agent_id='free', role_id='role:SYNTHESIZER',
            status=AssignmentStatus.RUNNING, task_revision=self.syn.revision, provider_key='fake',
            input_finding_ids=self.gate.support,
            input_finding_revisions=tuple(self.records[i].revision for i in self.gate.support),
            criterion_ids=('c1', 'c2'),
            criterion_hashes=tuple(digest(encode(c)) for c in
                                   self.records['r'].acceptance_criteria)))
        self.records['free'] = replace(self.records['free'], status=AgentStatus.RUNNING,
                                       role_id='role:SYNTHESIZER', assignment_id='asyn',
                                       revision=self.records['free'].revision + 1)
        return self.project()


def envelope(answer='the combined total', finding_ids=('f1', 'f2'), **fields):
    draft = ResultDraft(answer, tuple(finding_ids), fields.pop('criterion_ids', ('c1', 'c2')),
                        fields.pop('claims', (ResultClaimDraft('c1 total', ('f1',)),
                                              ResultClaimDraft('c2 total', ('f2',)))),
                        fields.pop('limitations', ()))
    return ExecutionResult('SUCCEEDED', 'synthesized', result=draft, assignment_id='asyn', **fields)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = SynthesisFixture()
        self.s = self.f.ready()

    def admit(self, result=None):
        return admit_result(self.s['asyn'], result or envelope(), self.s, identity)

    def refusal(self, result):
        with self.assertRaises(ValueError) as caught:
            admit_result(self.s['asyn'], result, self.s, identity)
        return str(caught.exception)

    def test_a_valid_candidate_becomes_one_immutable_result_version(self):
        records, events, record = self.admit()
        self.assertEqual(record.version, 1)
        self.assertEqual(record.status, ResultStatus.CANDIDATE)
        self.assertEqual(record.finding_ids, ('f1', 'f2'))
        self.assertEqual(record.finding_revisions, (self.s['f1'].revision, self.s['f2'].revision))
        self.assertEqual(record.created_by_assignment, 'asyn')
        self.assertIsNone(record.decision)
        self.assertEqual([str(e.type) for e in events], ['RESULT_CREATED'])

    def test_coverage_is_recomputed_from_the_cited_findings(self):
        _, _, record = self.admit()
        coverage = {e.criterion_id: e.finding_ids for e in record.coverage}
        self.assertEqual(coverage, {'c1': ('f1',), 'c2': ('f2',)})

    def test_a_declared_criterion_the_citations_do_not_support_is_refused(self):
        # The model may say it covered c2; only the cited findings decide whether it did.
        self.assertIn('RESULT_REQUIRED_CRITERION_UNSUPPORTED',
                      self.refusal(envelope(finding_ids=('f1',),
                                            claims=(ResultClaimDraft('c1 total', ('f1',)),))))

    def test_only_validated_support_may_be_cited(self):
        self.f.records['f2'] = replace(self.s['f2'], status=FindingStatus.INVALIDATED, revision=3)
        self.s = self.f.project()
        self.assertIn('RESULT_STALE', self.refusal(envelope()))

    def test_a_current_but_unvalidated_citation_is_refused(self):
        """Staleness is not the only guard: a candidate whose revision never moved is still
        not validated knowledge, and may not support an answer."""
        candidate = self.f.finding('f5', 'ta', 'sum([8]) = 8', numbers=(8,), total=8,
                                   criterion_ids=('c1',), status=FindingStatus.CRITIQUED)
        self.f.records['asyn'] = replace(
            self.s['asyn'], input_finding_ids=self.s['asyn'].input_finding_ids + ('f5',),
            input_finding_revisions=self.s['asyn'].input_finding_revisions + (candidate.revision,))
        self.s = self.f.project()
        self.assertEqual(stale_support(self.s['asyn'], self.s), ())
        self.assertEqual(self.refusal(envelope(finding_ids=('f1', 'f2', 'f5'))),
                         'RESULT_SUPPORT_NOT_VALIDATED: f5')

    def test_a_rejected_finding_may_not_support_a_result(self):
        self.f.records['f3'] = self.f.finding('f3', 'ta', 'sum([9]) = 9', numbers=(9,), total=9,
                                              criterion_ids=('c1',), status=FindingStatus.REJECTED)
        self.s = self.f.project()
        self.assertIn('RESULT_SUPPORT_NOT_IN_CONTEXT',
                      self.refusal(envelope(finding_ids=('f1', 'f2', 'f3'))))

    def test_support_the_assignment_never_pinned_is_refused(self):
        self.f.validated('f4', 'ta', 'sum([5]) = 5', 'c1', numbers=(5,), total=5)
        self.s = self.f.project()
        self.assertIn('RESULT_SUPPORT_NOT_IN_CONTEXT',
                      self.refusal(envelope(finding_ids=('f1', 'f2', 'f4'))))

    def test_an_unresolvable_reference_is_refused(self):
        self.assertIn('RESULT_SUPPORT_MISSING', self.refusal(envelope(finding_ids=('f1', 'nope'))))

    def test_a_claim_with_no_support_is_refused(self):
        self.assertEqual(self.refusal(envelope(claims=(ResultClaimDraft('a bare assertion', ()),))),
                         'RESULT_CLAIM_UNSUPPORTED')

    def test_a_claim_citing_uncited_support_is_refused(self):
        self.assertEqual(self.refusal(envelope(finding_ids=('f1', 'f2'),
                                               claims=(ResultClaimDraft('x', ('f9',)),))),
                         'RESULT_CLAIM_REFERENCE_NOT_CITED')

    def test_an_unknown_criterion_is_refused(self):
        self.assertEqual(self.refusal(envelope(criterion_ids=('c1', 'c9'))),
                         'RESULT_UNKNOWN_CRITERION')

    def test_duplicate_citations_are_refused(self):
        self.assertEqual(self.refusal(envelope(finding_ids=('f1', 'f1', 'f2'))),
                         'RESULT_DUPLICATE_SUPPORT')

    def test_an_oversized_answer_is_refused(self):
        self.assertEqual(self.refusal(envelope(answer='x' * 9000)), 'RESULT_SIZE')


class StalenessTests(unittest.TestCase):
    def setUp(self):
        self.f = SynthesisFixture()
        self.s = self.f.ready()

    def test_support_that_moved_makes_the_synthesis_stale(self):
        self.f.records['f1'] = replace(self.s['f1'], revision=self.s['f1'].revision + 1)
        s = self.f.project()
        self.assertTrue(any(r.startswith('SUPPORT_REVISION_CHANGED') for r in
                            stale_support(s['asyn'], s)))
        with self.assertRaises(ValueError) as caught:
            admit_result(s['asyn'], envelope(), s, identity)
        self.assertIn('RESULT_STALE', str(caught.exception))

    def test_an_unrelated_change_does_not_make_the_synthesis_stale(self):
        self.f.task('tz', group_id='ga', acceptance_criterion_ids=('c1',))
        s = self.f.project()
        self.assertEqual(stale_support(s['asyn'], s), ())
        self.assertIsNotNone(admit_result(s['asyn'], envelope(), s, identity)[2])

    def test_a_repeated_attempt_over_the_same_support_is_recognised(self):
        self.f.records['tsyn'] = replace(self.s['tsyn'], status=TaskStatus.FAILED,
                                         outcome='RESULT_MISSING', assignment_id=None, revision=9)
        s = self.f.project()
        self.assertIn('RESULT_MISSING', repeated_attempt(s, 'r', self.f.gate.support, None))
        self.assertIsNone(repeated_attempt(s, 'r', ('f1',), None))
        self.assertIsNone(repeated_attempt(s, 'r', self.f.gate.support, 'review-1'))


class ProvenanceTests(unittest.TestCase):
    def test_the_synthesis_task_pins_the_controller_selected_support(self):
        f = SynthesisFixture()
        s = f.covered()
        gate = evaluate_gate(s, 'r')
        task = synthesis_task(lambda k: 'tsyn', 'r', s, gate)
        self.assertEqual(task.required_finding_ids, ('f1', 'f2'))
        self.assertEqual(task.candidate_finding_ids, ())
        self.assertEqual(task.acceptance_criterion_ids, ('c1', 'c2'))
        self.assertTrue(task.required)

    def test_the_context_carries_the_evidence_and_no_candidate(self):
        f = SynthesisFixture()
        s = f.ready()
        context = ContextBuilder().build(s, s['tsyn'], s['free'], s['role:SYNTHESIZER'], (),
                                         assignment_id='probe')
        self.assertEqual(context.finding_ids, ('f1', 'f2'))
        self.assertNotIn('candidate', ''.join(context.reasons))
        self.assertIn('"evidence"', context.json)

    def test_an_invalidated_support_member_refuses_the_context_outright(self):
        f = SynthesisFixture()
        s = f.ready()
        f.records['f2'] = replace(s['f2'], status=FindingStatus.INVALIDATED, revision=3)
        s = f.project()
        with self.assertRaises(ContextError):
            ContextBuilder().build(s, s['tsyn'], s['free'], s['role:SYNTHESIZER'], (),
                                   assignment_id='probe')

    def test_limitations_reach_the_synthesis_context(self):
        f = SynthesisFixture()
        s = f.covered()
        gate = evaluate_gate(s, 'r')
        task = f.add(replace(synthesis_task(lambda k: 'tsyn2', 'r', s, gate),
                             limitations=('one contested claim remains open',)))
        s = f.project()
        context = ContextBuilder().build(s, s[task.id], s['free'], s['role:SYNTHESIZER'], (),
                                         assignment_id='probe')
        self.assertIn('one contested claim remains open', context.json)


class VersionTests(unittest.TestCase):
    """Result versions are immutable in storage, not merely by convention."""

    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)
        self.f = SynthesisFixture()
        self.s = self.f.ready()
        _, _, self.result = admit_result(self.s['asyn'], envelope(), self.s, lambda k: 'res-1')
        self.f.add(self.result)

    def test_the_snapshot_accepts_a_candidate_result(self):
        validate_records(self.f.project().values())

    def test_a_result_may_not_be_edited(self):
        """Storage refuses an edit; only the verdict fields move."""
        judged = replace(self.result, status=ResultStatus.ACCEPTED, revision=2,
                         review_id='rev-1', decision=ReviewDecision.PASS)
        SQLiteRepository._validate_update(self.result, judged, {})
        for edit in (replace(self.result, answer='rewritten', revision=2),
                     replace(self.result, finding_ids=('f1',), finding_revisions=(1,), revision=2),
                     replace(self.result, version=9, revision=2)):
            with self.subTest(field=edit), self.assertRaises(DomainError):
                SQLiteRepository._validate_update(self.result, edit, {})

    def test_a_recorded_verdict_is_write_once(self):
        judged = replace(self.result, status=ResultStatus.REVISED, revision=2, review_id='rev-1',
                         decision=ReviewDecision.REVISE)
        rejudged = replace(judged, review_id='rev-2', revision=3)
        with self.assertRaises(DomainError):
            SQLiteRepository._validate_update(judged, rejudged, {})

    def test_a_second_version_supersedes_the_first_instead_of_replacing_it(self):
        s = self.f.project()
        records, _, second = admit_result(s['asyn'], envelope(answer='clearer'), s, lambda k: 'res-2')
        self.assertEqual(second.version, 2)
        self.assertEqual(second.supersedes_id, 'res-1')
        superseded = next(r for r in records if r.id == 'res-1')
        self.assertEqual(superseded.status, ResultStatus.SUPERSEDED)
        self.assertEqual(superseded.answer, self.result.answer)

    def test_two_versions_cannot_share_a_number(self):
        clash = replace(self.result, id='res-clash', version=1)
        with self.assertRaises(DomainError):
            validate_records(list(self.f.project().values()) + [clash])

    def test_a_result_cannot_cite_support_it_did_not_reference(self):
        from swarm.domain import ResultCoverage
        broken = replace(self.result, id='res-broken', version=2,
                         coverage=(ResultCoverage(criterion_id='c1', finding_ids=('f9',)),))
        with self.assertRaises(DomainError):
            validate_records(list(self.f.project().values()) + [broken])


class ProposalScopeTests(unittest.TestCase):
    """Only a SYNTHESIZER on a synthesis task may propose a result."""

    def setUp(self):
        self.f = SynthesisFixture()
        self.s = self.f.ready()

    def check(self, snapshot, assignment, result):
        return check_assignment_admissibility(assignment, result, snapshot)

    def test_the_synthesis_proposal_is_admissible_for_the_synthesizer(self):
        self.assertTrue(self.check(self.s, self.s['asyn'], envelope()).allowed)

    def test_another_role_may_not_propose_a_result(self):
        self.f.records['asyn'] = replace(self.s['asyn'], role_id='role:EXPLORER')
        self.f.records['free'] = replace(self.s['free'], role_id='role:EXPLORER')
        s = self.f.project()
        self.assertEqual(self.check(s, s['asyn'], envelope()).reason, 'SYNTHESIS_ROLE_MISMATCH')

    def test_a_synthesizer_may_not_create_findings_or_request_work(self):
        from swarm.output import FindingDraft
        result = replace(envelope(), findings=(FindingDraft('a new claim'),))
        self.assertEqual(self.check(self.s, self.s['asyn'], result).reason,
                         'SYNTHESIS_SCOPE_VIOLATION')

    def test_a_synthesis_task_that_returns_no_result_is_refused(self):
        result = ExecutionResult('SUCCEEDED', 'nothing', assignment_id='asyn')
        self.assertEqual(self.check(self.s, self.s['asyn'], result).reason, 'RESULT_MISSING')


if __name__ == '__main__':
    unittest.main()
