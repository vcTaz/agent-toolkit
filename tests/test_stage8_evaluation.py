"""The evaluation harness: does it actually notice when the swarm misbehaves?

An evaluation layer that only ever passes is worse than none, so most of this suite feeds
the checks *wrong* observations and asserts that they fail. The harness also has to fail
closed on an expectation it does not recognise, because a silently ignored expectation
would quietly reduce coverage every time a scenario is edited.
"""
import unittest
from dataclasses import replace
from stage8_support import executed
from swarm import evaluation, runner
from swarm.examples import catalogue, resolve
from swarm import scenario as scenario_module


class _Observed:
    """A stand-in for one executed run, so a check can be shown a wrong observation."""

    def __init__(self, report, exit_code=0):
        self.report, self.outcome = report, type('O', (), {'exit_code': exit_code})()

    def context(self):
        return evaluation._Context(self.report, self.outcome)


class CheckTests(unittest.TestCase):
    """Each check is fed a true and a false observation of the same run."""

    @classmethod
    def setUpClass(cls):
        cls.completed = executed('arithmetic_success')
        cls.exhausted = executed('arithmetic_exhausted')

    def check(self, name, expected, execution, exit_code=0):
        ctx = _Observed(execution.report, exit_code).context()
        return evaluation.CHECKS[name](expected, ctx)

    def assertPasses(self, name, expected, execution=None, **kwargs):
        ok, detail = self.check(name, expected, execution or self.completed, **kwargs)
        self.assertTrue(ok, detail)

    def assertFails(self, name, expected, execution=None, **kwargs):
        ok, detail = self.check(name, expected, execution or self.completed, **kwargs)
        self.assertFalse(ok, detail)

    def test_the_terminal_state_check_notices_the_wrong_state(self):
        self.assertPasses('terminal_state', 'COMPLETED')
        self.assertFails('terminal_state', 'EXHAUSTED')

    def test_the_exit_code_check_notices_a_wrong_code(self):
        self.assertPasses('exit_code', 0)
        self.assertFails('exit_code', 1)

    def test_the_answer_check_notices_a_missing_claim(self):
        self.assertPasses('answer_contains', ['sum([1, 2, 3]) = 6'])
        self.assertFails('answer_contains', ['sum([1, 2, 3]) = 7'])

    def test_the_coverage_check_notices_an_uncovered_criterion(self):
        self.assertPasses('criteria_covered', ['c1', 'c2'])
        self.assertFails('criteria_covered', ['c1', 'c2'], self.exhausted)

    def test_the_validated_claim_check_notices_a_claim_that_never_stood(self):
        self.assertPasses('validated_claims', ['sum([10, 20]) = 30'])
        self.assertFails('validated_claims', ['sum([10, 20]) = 99'])

    def test_the_rejected_claim_check_notices_a_candidate_that_was_never_refused(self):
        self.assertPasses('rejected_claims', ['sum([10, 20]) = 99'], self.exhausted)
        self.assertFails('rejected_claims', ['sum([10, 20]) = 99'])

    def test_the_no_rejection_check_notices_a_rejected_finding(self):
        self.assertPasses('no_rejected_findings', True)
        self.assertFails('no_rejected_findings', True, self.exhausted)

    def test_the_gap_check_compares_the_exact_gap_set(self):
        self.assertPasses('gaps', [])
        self.assertFails('gaps', ['c2:UNSUPPORTED'])
        self.assertPasses('gaps', ['c2:UNSUPPORTED'], self.exhausted)

    def test_the_propagation_check_notices_a_discovery_that_never_arrived(self):
        self.assertPasses('propagated_to', ['tc'])
        self.assertFails('propagated_to', ['tb'])

    def test_the_leakage_check_notices_a_discovery_that_should_not_have_arrived(self):
        self.assertPasses('not_propagated_to', ['tb'])
        self.assertFails('not_propagated_to', ['tc'])

    def test_the_reconsideration_check_notices_an_unanswered_delivery(self):
        self.assertPasses('reconsiderations_reported', True)
        self.assertFails('reconsiderations_reported', True,
                         _NoPropagations(self.completed.report))

    def test_the_blocking_criticism_check_needs_both_a_challenge_and_its_resolution(self):
        self.assertPasses('blocking_criticism', True)
        self.assertFails('blocking_criticism', True, _NoBlockingCriticism(self.completed.report))

    def test_the_final_review_check_compares_the_exact_verdict_sequence(self):
        self.assertPasses('final_review_decisions', ['REVISE', 'PASS'])
        self.assertFails('final_review_decisions', ['PASS'])
        self.assertFails('final_review_decisions', ['PASS', 'REVISE'])

    def test_the_result_version_check_counts_versions(self):
        self.assertPasses('result_versions', 2)
        self.assertFails('result_versions', 1)

    def test_the_no_result_check_distinguishes_an_answer_from_none(self):
        self.assertPasses('no_result', True, self.exhausted)
        self.assertFails('no_result', True)

    def test_the_stop_reason_check_reads_the_run_record(self):
        self.assertPasses('stop_reason_contains', 'c2', self.exhausted)
        self.assertFails('stop_reason_contains', 'c9', self.exhausted)

    def test_the_repair_check_notices_a_run_that_never_repaired(self):
        self.assertPasses('repair_attempted', True, self.exhausted)
        self.assertFails('repair_attempted', True)

    def test_the_answer_check_fails_rather_than_crashing_when_there_is_no_result(self):
        ok, detail = self.check('answer_contains', ['anything'], self.exhausted)
        self.assertFalse(ok)
        self.assertIn('no accepted result', detail)


class _NoPropagations:
    """The completed run as it would look if no delivery had ever been answered."""

    def __init__(self, report):
        self.report = dict(report, propagations=[dict(p, outcome=None)
                                                 for p in report['propagations']])


class _NoBlockingCriticism:
    """The completed run as it would look if criticism had raised nothing."""

    def __init__(self, report):
        self.report = dict(report, reviews=[dict(r, blocking_issues=[], resolved_issues=[])
                                            for r in report['reviews']])


class HarnessTests(unittest.TestCase):
    def test_an_unknown_expectation_fails_closed(self):
        scenario = scenario_module.load(resolve('arithmetic_minimal'),
                                        tool_names=runner.TOOL_NAMES)
        scenario = replace(scenario, expect={'vibes': True})
        execution = executed('arithmetic_minimal')
        checks = evaluation._expectation_checks(scenario, execution.report, execution.outcome)
        unknown = next(c for c in checks if c['name'] == 'vibes')
        self.assertFalse(unknown['ok'])
        self.assertIn('unknown expectation', unknown['detail'])

    def test_a_scenario_with_no_expectations_is_reported_rather_than_passing(self):
        scenario = scenario_module.load(resolve('arithmetic_minimal'),
                                        tool_names=runner.TOOL_NAMES)
        scenario = replace(scenario, expect={})
        execution = executed('arithmetic_minimal')
        checks = evaluation._expectation_checks(scenario, execution.report, execution.outcome)
        self.assertIn('expectations_declared', {c['name'] for c in checks})
        self.assertFalse(next(c for c in checks if c['name'] == 'expectations_declared')['ok'])

    def test_invariants_and_provenance_are_checked_for_every_scenario(self):
        execution = executed('arithmetic_minimal')
        scenario = scenario_module.load(resolve('arithmetic_minimal'),
                                        tool_names=runner.TOOL_NAMES)
        names = {c['name'] for c in
                 evaluation._expectation_checks(scenario, execution.report, execution.outcome)}
        self.assertIn('invariants', names)
        self.assertIn('provenance_reconstructible', names)

    def test_an_invariant_violation_is_reported_not_raised(self):
        ok, detail = evaluation._invariants({'x': object()})
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_a_scenario_that_must_be_refused_fails_if_it_validates(self):
        result = evaluation._rejection_result('arithmetic_minimal',
                                              resolve('arithmetic_minimal'), ('ANYTHING',))
        self.assertFalse(result['ok'])
        self.assertIn('must be refused', result['checks'][0]['detail'])

    def test_a_refusal_with_the_wrong_code_fails(self):
        result = evaluation._rejection_result('unsupported_verifier',
                                              resolve('unsupported_verifier'), ('OTHER_CODE',))
        self.assertFalse(result['ok'])

    def test_an_unknown_scenario_is_a_failing_result_not_a_crash(self):
        result = evaluation.evaluate_scenario('nothing_like_this')
        self.assertFalse(result['ok'])
        self.assertEqual(result['terminal_state'], 'UNKNOWN')

    def test_the_suite_covers_every_packaged_scenario(self):
        self.assertEqual(set(evaluation.suite_names()),
                         {entry['name'] for entry in catalogue()})

    def test_every_rejection_fixture_is_a_packaged_scenario(self):
        self.assertTrue(set(evaluation.REJECTIONS) <= set(evaluation.suite_names()))


class SuiteTests(unittest.TestCase):
    """The shipped suite must pass, and it must pass because the run behaved."""

    @classmethod
    def setUpClass(cls):
        cls.outcome = evaluation.run_suite()

    def test_the_whole_suite_passes(self):
        failures = [check for entry in self.outcome['results']
                    for check in entry['checks'] if not check['ok']]
        self.assertEqual(failures, [], failures)
        self.assertTrue(self.outcome['ok'])

    def test_every_scenario_contributes_checks(self):
        self.assertEqual(self.outcome['scenarios'], len(evaluation.suite_names()))
        for entry in self.outcome['results']:
            with self.subTest(scenario=entry['scenario']):
                self.assertTrue(entry['checks'])

    def test_the_summary_counts_agree_with_the_individual_checks(self):
        checks = [c for entry in self.outcome['results'] for c in entry['checks']]
        self.assertEqual(self.outcome['passed'], sum(c['ok'] for c in checks))
        self.assertEqual(self.outcome['failed'], sum(not c['ok'] for c in checks))

    def test_a_named_subset_can_be_evaluated_alone(self):
        outcome = evaluation.run_suite(['arithmetic_minimal'])
        self.assertEqual(outcome['scenarios'], 1)
        self.assertTrue(outcome['ok'])

    def test_repeating_a_scenario_adds_a_determinism_check_that_passes(self):
        outcome = evaluation.run_suite(['arithmetic_minimal'], repeat=2)
        checks = [c for c in outcome['results'][0]['checks'] if c['name'] == 'determinism']
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0]['ok'], checks[0]['detail'])


if __name__ == '__main__':
    unittest.main()
