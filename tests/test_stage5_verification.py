"""Host verification, deterministic consolidation, conflicts and shared-state projection."""
import json
import unittest
from dataclasses import replace
from swarm.domain import (Assignment, Conflict, ConflictKind, ConflictStatus, Criterion, Evidence,
                          Finding, FindingStatus, Run, SwarmState, Task)
from swarm.knowledge import (consolidate, criterion_coverage, detect_conflicts, duplicate_groups,
                             evidence_signature, invalidate_closure, normalize_claim, project)
from swarm.verification import (ArithmeticVerification, VerificationRegistry, parse_sum_claim,
                                structured_sum_value)

CRITERIA = (Criterion(id='c1', description='sums', verifier_kind='arithmetic'),)


def tool_evidence(numbers, expected, actual=None, reference='tool-1', verified=False):
    actual = sum(numbers) if actual is None else actual
    return Evidence(kind='tool_result', tool_name='arithmetic', reference=reference, verified=verified,
                    arguments_json=json.dumps({'expected': expected, 'numbers': numbers}, sort_keys=True),
                    value=json.dumps({'actual': actual, 'matches': actual == expected}))


def finding(identity='f', claim='sum([1, 2, 3]) = 6', evidence=(), **kwargs):
    kwargs.setdefault('criterion_ids', ('c1',))
    return Finding(id=identity, run_id='r', task_id='t', assignment_id='x', claim=claim,
                   evidence=evidence, **kwargs)


def snapshot(*records):
    base = {'r': Run(id='r', objective='x', acceptance_criteria=CRITERIA)}
    base.update({r.id: r for r in records})
    return base


class VerificationTests(unittest.TestCase):
    def verify(self, f, tool_results=()):
        return VerificationRegistry().verify(f, snapshot(f), tool_results)

    def test_matching_authoritative_tool_result_entails_the_claim(self):
        decision = self.verify(finding(evidence=(tool_evidence([1, 2, 3], 6),)))
        self.assertEqual(decision.decision, 'PASS')
        self.assertTrue(all(e.verified for e in decision.evidence))
        self.assertEqual([e.reference for e in decision.evidence], ['tool-1'])

    def test_successful_tool_call_over_other_numbers_does_not_verify_the_claim(self):
        # The call succeeded and even matched — but it summed something else entirely.
        decision = self.verify(finding(evidence=(tool_evidence([9, 9], 18),)))
        self.assertEqual(decision.decision, 'INCONCLUSIVE')
        self.assertIn('NO_ENTAILING_TOOL_RESULT', decision.reason)

    def test_incorrect_claim_with_a_successful_tool_call_fails(self):
        decision = self.verify(finding(claim='sum([10, 20]) = 99',
                                       evidence=(tool_evidence([10, 20], 99),)))
        self.assertEqual(decision.decision, 'FAIL')
        self.assertIn('TOOL_RESULT_CONTRADICTS_CLAIM', decision.reason)

    def test_a_correct_computation_does_not_verify_a_different_asserted_total(self):
        # The tool really did sum these operands correctly — for a total the claim does not state.
        decision = self.verify(finding(claim='sum([1, 2, 3]) = 99',
                                       evidence=(tool_evidence([1, 2, 3], 6),)))
        self.assertEqual(decision.decision, 'FAIL')
        self.assertEqual(decision.evidence, ())

    def test_a_result_that_denies_its_own_match_never_verifies(self):
        denied = Evidence(kind='tool_result', tool_name='arithmetic', reference='tool-1',
                          arguments_json=json.dumps({'expected': 6, 'numbers': [1, 2, 3]}, sort_keys=True),
                          value=json.dumps({'actual': 6, 'matches': False}))
        self.assertEqual(self.verify(finding(evidence=(denied,))).decision, 'FAIL')

    def test_unsupported_claim_form_is_inconclusive_not_guessed(self):
        for claim in ('the total is six', 'sum([1,2,3]) is 6', 'product([2,3]) = 6'):
            with self.subTest(claim=claim):
                self.assertIsNone(parse_sum_claim(claim))
                self.assertEqual(self.verify(finding(claim=claim,
                                 evidence=(tool_evidence([1, 2, 3], 6),))).decision, 'INCONCLUSIVE')

    def test_model_supplied_verified_flag_cannot_create_verified_evidence(self):
        # Even if a verified evidence entry existed, entailment is judged from the recorded
        # arguments and value, never from the flag.
        forged = Evidence(kind='tool_result', tool_name='arithmetic', reference='forged', verified=True,
                          arguments_json=json.dumps({'numbers': [1, 2, 3], 'expected': 6}),
                          value=json.dumps({'actual': 99, 'matches': True}))
        self.assertEqual(self.verify(finding(evidence=(forged,))).decision, 'FAIL')

    def test_verifier_kind_without_a_policy_fails_closed(self):
        run = Run(id='r', objective='x', acceptance_criteria=(Criterion(id='c1', description='prose'),))
        f = finding(evidence=(tool_evidence([1, 2, 3], 6),))
        decision = VerificationRegistry().verify(f, {'r': run}, ())
        self.assertEqual(decision.decision, 'INCONCLUSIVE')
        self.assertIn('UNSUPPORTED_VERIFIER_KIND', decision.reason)

    def test_claims_without_criteria_or_evidence_are_never_verified(self):
        self.assertEqual(self.verify(finding(criterion_ids=())).decision, 'INCONCLUSIVE')
        self.assertEqual(self.verify(finding()).decision, 'INCONCLUSIVE')

    def test_a_validator_tool_result_can_supply_the_entailment(self):
        decision = self.verify(finding(), (tool_evidence([1, 2, 3], 6, reference='own'),))
        self.assertEqual((decision.decision, decision.evidence[0].reference), ('PASS', 'own'))

    def test_policy_is_selected_by_verifier_kind(self):
        self.assertEqual(ArithmeticVerification().verifier_kind, 'arithmetic')


class ConsolidationTests(unittest.TestCase):
    def duplicates(self, *claims, evidence=None):
        evidence = evidence or (tool_evidence([1, 2, 3], 6),)
        return [finding(f'f{i}', claim, evidence, status=FindingStatus.VALIDATED)
                for i, claim in enumerate(claims)]

    def test_exact_duplicates_group_under_a_stable_canonical_representative(self):
        records = self.duplicates('sum([1, 2, 3]) = 6', 'SUM([1, 2, 3])   =  6')
        groups = duplicate_groups(snapshot(*records))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].canonical_id, 'f0')
        self.assertEqual(groups[0].member_ids, ('f0', 'f1'))
        self.assertEqual(groups[0].duplicate_ids, ('f1',))

    def test_similar_prose_is_not_merged(self):
        records = self.duplicates('the sum is 6', 'the sum is six')
        self.assertEqual(len(duplicate_groups(snapshot(*records))), 2)
        self.assertNotEqual(normalize_claim('the sum is 6'), normalize_claim('the sum is six'))

    def test_identical_claim_with_different_evidence_is_not_merged(self):
        a = finding('f0', evidence=(tool_evidence([1, 2, 3], 6),), status=FindingStatus.VALIDATED)
        b = finding('f1', evidence=(tool_evidence([3, 3], 6),), status=FindingStatus.VALIDATED)
        self.assertNotEqual(evidence_signature(a), evidence_signature(b))
        self.assertEqual(len(duplicate_groups(snapshot(a, b))), 2)

    def test_canonical_choice_prefers_the_more_advanced_status_then_the_stable_id(self):
        records = self.duplicates('sum([1, 2, 3]) = 6', 'sum([1, 2, 3]) = 6')
        records[0] = replace(records[0], status=FindingStatus.PROPOSED)
        self.assertEqual(duplicate_groups(snapshot(*records))[0].canonical_id, 'f1')

    def test_result_is_independent_of_insertion_and_hash_order(self):
        records = self.duplicates(*['sum([1, 2, 3]) = 6'] * 3)
        forward = consolidate(snapshot(*records))
        backward = consolidate(snapshot(*reversed(records)))
        self.assertEqual(forward, backward)
        self.assertEqual(forward.canonical_ids, ('f0',))
        self.assertEqual(forward.duplicate_ids, ('f1', 'f2'))
        # Provenance is preserved: every original identity stays a member of its group.
        self.assertEqual(forward.groups[0].member_ids, ('f0', 'f1', 'f2'))

    def test_projection_offers_one_representative_and_keeps_every_record(self):
        records = self.duplicates('sum([1, 2, 3]) = 6', 'sum([1, 2, 3]) = 6')
        s = snapshot(*records, SwarmState(id='s', run_id='r'))
        updated = project(s, s['s'])
        self.assertEqual(updated.validated_findings, ('f0',))
        self.assertEqual(updated.revision, 2)
        self.assertIsNotNone(s['f1'])


class SupersessionTests(unittest.TestCase):
    def test_a_superseded_claim_leaves_shared_knowledge_but_stays_on_record(self):
        from swarm.domain import revise_finding, transition
        original = finding('f0', 'sum([1, 2, 3]) = 6', (tool_evidence([1, 2, 3], 6),),
                           status=FindingStatus.VALIDATED)
        replacement = revise_finding(original, new_id='f1', claim='sum([1, 2, 3, 4]) = 10',
                                     evidence=(tool_evidence([1, 2, 3, 4], 10),))
        superseded = transition(original, FindingStatus.SUPERSEDED)
        s = snapshot(superseded, replacement, SwarmState(id='s', run_id='r',
                                                         validated_findings=('f0',)))
        updated = project(s, s['s'])
        self.assertEqual(updated.validated_findings, ())
        self.assertEqual(updated.candidate_findings, ('f1',))
        # The claim was never edited in place; both identities remain inspectable.
        self.assertEqual(s['f0'].claim, 'sum([1, 2, 3]) = 6')
        self.assertEqual(replacement.supersedes_id, 'f0')


class ConflictTests(unittest.TestCase):
    def validated(self, identity, claim, **kwargs):
        return finding(identity, claim, (tool_evidence([1], 1),), status=FindingStatus.VALIDATED, **kwargs)

    def test_incompatible_structured_values_open_one_conflict(self):
        s = snapshot(self.validated('f0', 'sum([2, 2]) = 4'), self.validated('f1', 'sum([2, 2]) = 5'))
        specs = detect_conflicts(s, structured_sum_value)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].kind, ConflictKind.CONTRADICTORY_VALUE)
        self.assertEqual(specs[0].finding_ids, ('f0', 'f1'))

    def test_agreeing_and_unrelated_findings_open_nothing(self):
        s = snapshot(self.validated('f0', 'sum([2, 2]) = 4'), self.validated('f1', 'sum([2, 2]) = 4'),
                     self.validated('f2', 'sum([9]) = 9'), self.validated('f3', 'a prose claim'))
        self.assertEqual(detect_conflicts(s, structured_sum_value), ())

    def test_declared_contradiction_is_honoured(self):
        s = snapshot(self.validated('f0', 'left', tags=('contradiction',), related_finding_ids=('f1',)),
                     self.validated('f1', 'right'))
        specs = detect_conflicts(s, structured_sum_value)
        self.assertEqual((specs[0].kind, specs[0].finding_ids),
                         (ConflictKind.DECLARED_CONTRADICTION, ('f0', 'f1')))

    def test_candidates_do_not_open_conflicts(self):
        s = snapshot(finding('f0', 'sum([2, 2]) = 4'), self.validated('f1', 'sum([2, 2]) = 5'))
        self.assertEqual(detect_conflicts(s, structured_sum_value), ())

    def test_unresolved_conflict_denies_clean_criterion_coverage(self):
        conflict = Conflict(id='k', run_id='r', finding_ids=('f0', 'f1'), finding_revisions=(1, 1),
                            kind=ConflictKind.CONTRADICTORY_VALUE, signature='sig')
        s = snapshot(self.validated('f0', 'sum([2, 2]) = 4'), self.validated('f1', 'sum([2, 2]) = 5'),
                     conflict)
        coverage = criterion_coverage(s, 'r')['c1']
        self.assertEqual(coverage.supporting_ids, ('f0', 'f1'))
        self.assertEqual(coverage.conflict_ids, ('k',))
        self.assertFalse(coverage.clean)
        # Remove the conflict and the same knowledge is clean coverage.
        del s['k']
        self.assertTrue(criterion_coverage(s, 'r')['c1'].clean)


class InvalidationTests(unittest.TestCase):
    def chain(self):
        root = finding('root', 'sum([1]) = 1', status=FindingStatus.VALIDATED)
        mid = finding('mid', 'sum([2]) = 2', status=FindingStatus.VALIDATED,
                      dependency_finding_ids=('root',))
        leaf = finding('leaf', 'sum([3]) = 3', status=FindingStatus.VALIDATED,
                       dependency_finding_ids=('mid',))
        other = finding('other', 'sum([4]) = 4', status=FindingStatus.VALIDATED)
        candidate = finding('cand', 'sum([5]) = 5', dependency_finding_ids=('mid',))
        return snapshot(root, mid, leaf, other, candidate)

    def test_transitive_invalidation_reaches_dependents_and_spares_others(self):
        records, events = invalidate_closure(self.chain(), 'r', 'root', 'REASON')
        self.assertEqual([r.id for r in records], ['leaf', 'mid', 'root'])
        self.assertTrue(all(r.status == FindingStatus.INVALIDATED for r in records))
        removal = json.loads(events[-1].detail_json)
        self.assertEqual(removal['removed'], ['leaf', 'mid', 'root'])
        self.assertEqual(removal['unvalidated_dependents'], ['cand'])
        self.assertNotIn('other', removal['removed'])

    def test_invalidation_events_carry_the_retraction_payload_stage_six_needs(self):
        detail = json.loads(invalidate_closure(self.chain(), 'r', 'root', 'REASON')[1][0].detail_json)
        self.assertEqual(detail['root_finding_id'], 'root')
        self.assertEqual(detail['reason'], 'REASON')
        self.assertEqual((detail['revision'], detail['previous_revision']), (2, 1))
        self.assertIn('delivered_to', detail)
        self.assertIn('consumed_by', detail)

    def test_unknown_finding_is_refused(self):
        with self.assertRaises(ValueError):
            invalidate_closure(self.chain(), 'r', 'absent', 'REASON')
