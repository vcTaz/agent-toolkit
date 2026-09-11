"""The shipped scenarios, executed end to end through the real controller.

Nothing here is satisfied by a scripted answer. Every claim that reaches an answer was
verified by the trusted arithmetic tool against its own operands; every promotion was an
independent review; the run's terminal state was written by the workflow, not by the CLI;
and the same ``WorkController`` the Stage-7 suite drives is the one that ran.
"""
import unittest
from stage8_support import ExampleCase, executed
from swarm import evaluation, inspection, runner, scenario as scenario_module
from swarm.domain import Finding, FindingStatus, Result, ResultStatus, RunState, validate_records
from swarm.examples import resolve
from swarm.persistence import SQLiteRepository


class CompletedScenarioTests(ExampleCase):
    """explore → critique → validate → consolidate → propagate → reconsider → gate →
    synthesize → final review REVISE → resynthesize → PASS → COMPLETED."""
    example = 'arithmetic_success'

    def test_the_run_completes_with_a_reviewed_answer(self):
        self.assertEqual(self.report['run']['state'], 'COMPLETED')
        self.assertEqual(self.execution.outcome.exit_code, 0)
        self.assertIsNotNone(self.report['run']['result_id'])

    def test_every_phase_of_the_architecture_actually_ran(self):
        kinds = {entry['type'] for entry in self.report['timeline']}
        for kind in ('CYCLE_STARTED', 'FINDING_CREATED', 'REVIEW_COMPLETED', 'FINDING_CRITIQUED',
                     'FINDING_VALIDATED', 'KNOWLEDGE_PROMOTED', 'CONSOLIDATION_COMPLETED',
                     'CROSS_POLLINATION', 'PROPAGATION_DELIVERED', 'RECONSIDERATION_COMPLETED',
                     'SYNTHESIS_GATE_EVALUATED', 'SYNTHESIS_STARTED', 'RESULT_CREATED',
                     'FINAL_REVIEW_STARTED', 'FINAL_REVIEW_COMPLETED',
                     'RESULT_REVISION_REQUESTED', 'RUN_COMPLETED'):
            with self.subTest(kind=kind):
                self.assertIn(kind, kinds)

    def test_multiple_agents_worked_multiple_branches(self):
        assignments = self.report['assignments']
        self.assertGreaterEqual(len({a['agent_id'] for a in assignments}), 5)
        self.assertGreaterEqual(len({t['group_id'] for t in self.report['tasks']
                                     if t['group_id']}), 3)

    def test_criticism_raised_a_blocking_issue_that_validation_had_to_resolve(self):
        blocking = [r for r in self.execution.reviews('criticism') if r['blocking_issues']]
        self.assertTrue(blocking)
        keys = {f'{r["id"]}#0' for r in blocking}
        resolved = {key for r in self.execution.reviews('validation') for key in r['resolved_issues']}
        self.assertTrue(keys <= resolved)

    def test_every_validated_claim_rests_on_host_verified_tool_evidence(self):
        for finding in self.execution.findings('VALIDATED'):
            with self.subTest(finding=finding['id']):
                self.assertTrue(finding['verified_evidence'])
                for item in finding['verified_evidence']:
                    self.assertEqual(item['tool_name'], 'arithmetic')
                    self.assertIn('"matches": true', item['value'])

    def test_cross_pollination_was_selective_rather_than_broadcast(self):
        delivered = {p['target_task_id'] for p in self.report['propagations']}
        self.assertIn('tc', delivered)
        self.assertNotIn('tb', delivered, 'an unrelated criterion must not receive knowledge')
        for propagation in self.report['propagations']:
            self.assertGreaterEqual(propagation['score'], 2)
            self.assertTrue(propagation['matched_features'])

    def test_each_delivery_was_answered_by_the_branch_that_received_it(self):
        outcomes = {p['outcome'] for p in self.report['propagations']}
        self.assertTrue(outcomes <= {'APPLIED', 'NO_CHANGE', 'FOLLOW_UP_REQUESTED'})
        self.assertTrue(outcomes)

    def test_the_reviewed_version_was_never_edited_only_superseded(self):
        versions = self.report['results']
        self.assertEqual([r['status'] for r in versions], ['REVISED', 'ACCEPTED'])
        self.assertEqual(versions[1]['supersedes_id'], versions[0]['id'])
        self.assertTrue(set(versions[0]['finding_ids']) < set(versions[1]['finding_ids']))

    def test_the_synthesizer_and_the_final_reviewer_are_different_identities(self):
        authors = {r['author'] for r in self.report['results']}
        judges = {r['reviewer'] for r in self.execution.reviews('final')}
        self.assertTrue(authors and judges)
        self.assertEqual(authors & judges, set())

    def test_the_accepted_coverage_was_recomputed_from_the_citations(self):
        accepted = self.report['result']
        findings = {f['id']: f for f in self.report['findings']}
        for entry in accepted['coverage']:
            for identity in entry['finding_ids']:
                self.assertIn(entry['criterion_id'], findings[identity]['criterion_ids'])
        self.assertEqual(sorted(e['criterion_id'] for e in accepted['coverage'] if e['required']),
                         ['c1', 'c2'])

    def test_the_terminal_snapshot_satisfies_every_invariant(self):
        validate_records(self.execution.outcome.snapshot.values())

    def test_the_completed_report_names_the_accepted_result_and_no_gaps(self):
        report = self.report['outcome']
        self.assertEqual(report['state'], 'COMPLETED')
        self.assertEqual(report['result_id'], self.report['run']['result_id'])
        self.assertEqual(report['gaps'], [])


class ExhaustedScenarioTests(ExampleCase):
    """A required claim the verifier refuses; bounded repair; an honest EXHAUSTED."""
    example = 'arithmetic_exhausted'

    def test_the_run_exhausts_and_offers_no_answer(self):
        self.assertEqual(self.report['run']['state'], 'EXHAUSTED')
        self.assertEqual(self.execution.outcome.exit_code, 1)
        self.assertIsNone(self.report['run']['result_id'])
        self.assertEqual(self.report['results'], [])

    def test_the_unverifiable_claim_was_rejected_by_evidence_not_by_opinion(self):
        rejected = self.execution.findings('REJECTED')
        self.assertTrue(rejected)
        for finding in rejected:
            trails = [entry['verification'] for entry in finding['lifecycle']
                      if entry['kind'] == 'validation']
            self.assertTrue(any('TOOL_RESULT_CONTRADICTS_CLAIM' in trail for trail in trails),
                            trails)

    def test_bounded_repair_was_attempted_and_then_refused_with_a_reason(self):
        decisions = self.report['provenance']['repair_decisions']
        self.assertTrue([d for d in decisions if d['admitted']])
        refused = [d for d in decisions if not d['admitted']]
        self.assertTrue(refused)
        self.assertTrue(all(d['reason'] for d in refused))
        self.assertLessEqual(self.report['run']['repair_rounds'],
                             self.report['run']['limits']['repair_round_limit'])

    def test_partial_knowledge_is_preserved_and_labelled_as_unfinished(self):
        report = self.report['outcome']
        self.assertEqual(report['state'], 'EXHAUSTED')
        self.assertEqual([(g['criterion_id'], g['reason']) for g in report['gaps']],
                         [('c2', 'UNSUPPORTED')])
        self.assertEqual(sorted(report['validated_finding_ids']),
                         sorted(f['id'] for f in self.execution.findings('VALIDATED')))
        self.assertTrue(report['validated_finding_ids'])

    def test_the_run_says_why_it_stopped(self):
        self.assertIn('c2', self.report['run']['stop_reason'])
        self.assertEqual([e['type'] for e in self.execution.events('RUN_EXHAUSTED')], ['RUN_EXHAUSTED'])

    def test_the_covered_criterion_is_still_reported_as_clean(self):
        readings = {entry['id']: entry for entry in self.report['criteria']}
        self.assertIsNone(readings['c1']['blocking_gap'])
        self.assertEqual(readings['c2']['blocking_gap'], 'UNSUPPORTED')

    def test_the_exhausted_snapshot_satisfies_every_invariant(self):
        validate_records(self.execution.outcome.snapshot.values())


class FailedScenarioTests(ExampleCase):
    """FAILED and EXHAUSTED are different facts, and the run says which one it is."""
    example = 'failed_no_decomposition'

    def test_a_run_with_no_task_graph_fails_rather_than_exhausting(self):
        self.assertEqual(self.report['run']['state'], 'FAILED')
        self.assertEqual(self.execution.outcome.exit_code, 2)
        self.assertIn('NO_ADMITTED_WORK', self.report['run']['stop_reason'])

    def test_failing_at_configuration_spends_no_provider_request(self):
        self.assertEqual(self.report['metrics']['provider_requests'], 0)
        self.assertEqual(self.report['metrics']['tool_calls'], 0)

    def test_the_failed_run_writes_a_terminal_report_and_no_result(self):
        self.assertEqual(self.report['outcome']['state'], 'FAILED')
        self.assertIsNone(self.report['outcome']['result_id'])
        self.assertEqual(self.report['results'], [])

    def test_the_exit_code_distinguishes_failed_from_exhausted(self):
        self.assertNotEqual(runner.EXIT_CODES[RunState.FAILED],
                            runner.EXIT_CODES[RunState.EXHAUSTED])

    def test_the_failed_snapshot_satisfies_every_invariant(self):
        validate_records(self.execution.outcome.snapshot.values())


class CapabilityBoundaryTests(unittest.TestCase):
    """The MVP's boundary is explicit: what it cannot verify, it refuses to start."""

    def test_a_scenario_asking_for_an_unshipped_verifier_never_runs(self):
        with self.assertRaises(scenario_module.ScenarioError) as caught:
            scenario_module.load(resolve('unsupported_verifier'), tool_names=runner.TOOL_NAMES)
        self.assertEqual([p.code for p in caught.exception.problems],
                         ['UNSUPPORTED_VERIFIER_KIND'])

    def test_the_shipped_verifier_registry_is_arithmetic_only(self):
        from swarm.verification import VerificationRegistry
        self.assertEqual({p.verifier_kind for p in VerificationRegistry().policies},
                         {'arithmetic'})

    def test_no_generic_task_request_became_schedulable_work(self):
        for name in ('arithmetic_success', 'arithmetic_exhausted'):
            with self.subTest(example=name):
                execution = executed(name)
                self.assertEqual(execution.report['task_requests'], [])
                self.assertEqual([t for t in execution.report['tasks']
                                  if t['kind'] not in ('exploration', 'criticism', 'validation',
                                                       'reconsideration', 'follow_up', 'repair',
                                                       'synthesis', 'final_review')], [])


class ReproducibilityTests(unittest.TestCase):
    """A deterministic scenario produces the same semantic result every time."""

    def outcomes(self, name, times):
        scenario = scenario_module.load(resolve(name), tool_names=runner.TOOL_NAMES)
        seen = []
        for _ in range(times):
            repository = SQLiteRepository(':memory:')
            try:
                outcome = runner.execute_scenario(repository, scenario)
                report = inspection.build(repository.inspect(outcome.run_id), outcome.run_id,
                                          sections=('run', 'criteria', 'result', 'results',
                                                    'outcome', 'findings', 'reviews',
                                                    'propagations', 'cycles', 'provenance'))
            finally:
                repository.close()
            seen.append(evaluation.normalise(report, outcome.run_id))
        return seen

    def test_repeated_runs_of_the_completing_scenario_are_equivalent(self):
        first, second = self.outcomes('arithmetic_minimal', 2)
        self.assertEqual(first, second)

    def test_repeated_runs_of_the_exhausting_scenario_are_equivalent(self):
        first, second = self.outcomes('arithmetic_exhausted', 2)
        self.assertEqual(first, second)

    def test_normalisation_removes_only_genuinely_volatile_values(self):
        report = executed('arithmetic_minimal').report
        normalised = evaluation.normalise({'run': report['run']}, 'r')
        self.assertEqual(normalised['run']['created_at'], '<volatile>')
        self.assertEqual(normalised['run']['state'], 'COMPLETED')

    def test_run_identity_is_substituted_so_two_runs_can_be_compared(self):
        self.assertEqual(evaluation.normalise({'id': 'abc:task:1'}, 'abc'),
                         {'id': '<run>:task:1'})

    def test_declaration_order_does_not_change_what_the_run_established(self):
        """Order changes which branch runs first; it must not change what was proven.

        Task declaration order feeds ``created_at``, which feeds deterministic selection,
        so reversing it genuinely reorders dispatch. The terminal state, the validated
        claims and the criteria covered are properties of the evidence, not of the order.
        """
        import json
        payload = json.loads(resolve('arithmetic_success').read_text())
        outcomes = []
        for tasks in (payload['tasks'], list(reversed(payload['tasks']))):
            scenario = scenario_module.parse(dict(payload, tasks=tasks),
                                             tool_names=runner.TOOL_NAMES)
            repository = SQLiteRepository(':memory:')
            try:
                outcome = runner.execute_scenario(repository, scenario)
                report = inspection.build(repository.inspect(outcome.run_id), outcome.run_id,
                                          sections=('run', 'criteria', 'result', 'findings'))
            finally:
                repository.close()
            outcomes.append((
                report['run']['state'],
                tuple(sorted(f['claim'] for f in report['findings']
                             if f['status'] == 'VALIDATED')),
                tuple(sorted(c['id'] for c in report['criteria']
                             if c['covered'] and c['blocking_gap'] is None)),
                tuple(sorted(report['result']['finding_ids'])) and tuple(
                    sorted(e['criterion_id'] for e in report['result']['coverage']))))
        self.assertEqual(outcomes[0], outcomes[1])

    def test_a_different_terminal_state_survives_normalisation(self):
        # Normalisation must not be so aggressive that a regression compares equal.
        completed = evaluation.normalise({'state': 'COMPLETED'}, 'r')
        exhausted = evaluation.normalise({'state': 'EXHAUSTED'}, 'r')
        self.assertNotEqual(completed, exhausted)


class RunnerTests(unittest.TestCase):
    def test_the_runner_drives_the_same_controller_the_tests_drive(self):
        from swarm.orchestration import WorkController
        import inspect as python_inspect
        source = python_inspect.getsource(runner.execute_scenario)
        self.assertIn('WorkController(', source)
        self.assertIn('run_until_idle', source)
        self.assertTrue(issubclass(WorkController, __import__(
            'swarm.engine', fromlist=['WorkEngine']).WorkEngine))

    def test_the_command_surface_performs_no_orchestration_of_its_own(self):
        """There is no CLI-only path: the surface seeds, reads and renders, nothing else.

        Every name below is a controller-owned decision — scheduling, admission, the gate,
        a run transition, a work factory. A command module that reached for one would be a
        second orchestrator, which is exactly what the architecture forbids.
        """
        import inspect as python_inspect
        from swarm import cli
        forbidden = ('evaluate_gate', 'workflow.advance', 'transition(', '_dispatch',
                     '_schedule', 'admit_result', 'admit_review', 'admit_proposals',
                     'check_assignment_admissibility', 'plan_reviews', 'plan_propagations',
                     'synthesis_task', 'final_review_task', 'repair_task', 'repair_admissible')
        for module in (cli, runner):
            source = python_inspect.getsource(module)
            for name in forbidden:
                with self.subTest(module=module.__name__, name=name):
                    self.assertNotIn(name, source)

    def test_an_unrecognised_terminal_state_still_reports_a_nonzero_code(self):
        self.assertEqual(runner.EXIT_CODES[RunState.COMPLETED], 0)
        self.assertNotIn(RunState.RECEIVED, runner.EXIT_CODES)
        self.assertNotEqual(runner.UNKNOWN_STATE, 0)

    def test_a_supplied_run_identity_is_used_verbatim(self):
        scenario = scenario_module.load(resolve('arithmetic_minimal'),
                                        tool_names=runner.TOOL_NAMES)
        repository = SQLiteRepository(':memory:')
        self.addCleanup(repository.close)
        outcome = runner.execute_scenario(repository, scenario, run_id='chosen')
        self.assertEqual(outcome.run_id, 'chosen')
        self.assertEqual(outcome.state, RunState.COMPLETED)

    def test_generated_run_identities_are_unique_per_run(self):
        scenario = scenario_module.load(resolve('arithmetic_minimal'),
                                        tool_names=runner.TOOL_NAMES)
        self.assertNotEqual(runner.new_run_id(scenario), runner.new_run_id(scenario))


if __name__ == '__main__':
    unittest.main()
