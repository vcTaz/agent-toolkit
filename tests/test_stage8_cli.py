"""The command line: what it runs, what it refuses, and what it tells the operator.

Exit codes are part of the contract here. A terminal outcome is information, so EXHAUSTED
and FAILED are reported with distinct nonzero codes rather than raised as crashes, and a
configuration the host refuses never reaches a run at all.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from stage8_support import MINIMAL, database_path, document, executed, invoke
from swarm import cli, inspection, runner


class CommandTests(unittest.TestCase):
    def test_examples_lists_every_packaged_scenario(self):
        captured = invoke('examples')
        self.assertEqual(captured.code, 0)
        for name in ('arithmetic_minimal', 'arithmetic_success', 'arithmetic_exhausted',
                     'failed_no_decomposition', 'unsupported_verifier'):
            self.assertIn(name, captured.out)

    def test_examples_json_is_machine_readable(self):
        payload = invoke('examples', '--json').json()
        self.assertTrue(all({'name', 'path', 'description'} <= set(entry)
                            for entry in payload['examples']))

    def test_validate_accepts_a_packaged_scenario_without_running_it(self):
        captured = invoke('validate', '--scenario', 'arithmetic_minimal')
        self.assertEqual(captured.code, 0)
        self.assertIn('VALID', captured.out)

    def test_validate_reports_a_refusal_on_stderr_with_a_refused_exit_code(self):
        captured = invoke('validate', '--scenario', 'unsupported_verifier')
        self.assertEqual(captured.code, cli.REFUSED)
        self.assertIn('UNSUPPORTED_VERIFIER_KIND', captured.err)
        self.assertIn('acceptance_criteria[0].verifier_kind', captured.err)

    def test_an_unknown_scenario_reference_is_refused_with_the_catalogue(self):
        captured = invoke('validate', '--scenario', 'no_such_thing')
        self.assertEqual(captured.code, cli.REFUSED)
        self.assertIn('no scenario file or packaged example', captured.err)
        self.assertIn('arithmetic_minimal', captured.err)

    def test_a_refusal_can_be_read_as_structured_problems(self):
        captured = invoke('validate', '--scenario', 'unsupported_verifier', '--json')
        payload = json.loads(captured.err)
        self.assertEqual(payload['status'], 'REJECTED')
        self.assertEqual([p['code'] for p in payload['problems']], ['UNSUPPORTED_VERIFIER_KIND'])


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.database = str(Path(self.workspace.name) / 'runs.db')

    def run_example(self, name, *extra):
        return invoke('run', '--scenario', name, '--database', self.database, *extra)

    def test_a_completing_scenario_exits_zero_and_prints_its_answer(self):
        captured = self.run_example('arithmetic_minimal')
        self.assertEqual(captured.code, 0)
        self.assertIn('COMPLETED', captured.out)
        self.assertIn('sum([1, 2, 3]) = 6', captured.out)

    def test_the_run_output_explains_what_completed_means(self):
        captured = self.run_example('arithmetic_minimal')
        self.assertIn('independent final reviewer', captured.out)
        self.assertIn('inspect it with', captured.out)

    def test_a_run_identity_can_be_chosen_and_is_inspectable_afterwards(self):
        self.run_example('arithmetic_minimal', '--run-id', 'chosen-run')
        captured = invoke('inspect', 'chosen-run', '--database', self.database)
        self.assertEqual(captured.code, 0)
        self.assertIn('chosen-run', captured.out)

    def test_the_trace_flag_adds_the_causal_timeline(self):
        captured = self.run_example('arithmetic_minimal', '--trace')
        self.assertIn('timeline:', captured.out)
        self.assertIn('FINDING_VALIDATED', captured.out)
        self.assertIn('RUN_COMPLETED', captured.out)

    def test_run_json_is_a_bounded_report_not_a_record_dump(self):
        payload = self.run_example('arithmetic_minimal', '--json').json()
        self.assertEqual(sorted(payload['sections']), sorted(cli.RUN_SECTIONS))
        self.assertNotIn('events', payload)
        self.assertNotIn('assignments', payload)
        self.assertEqual(payload['run']['state'], 'COMPLETED')

    def test_list_runs_finds_what_run_committed(self):
        self.run_example('arithmetic_minimal', '--run-id', 'first')
        self.run_example('arithmetic_minimal', '--run-id', 'second')
        payload = invoke('list-runs', '--database', self.database, '--json').json()
        self.assertEqual({row['run_id'] for row in payload['runs']}, {'first', 'second'})
        self.assertTrue(all(row['state'] == 'COMPLETED' for row in payload['runs']))

    def test_list_runs_on_an_empty_database_says_so(self):
        captured = invoke('list-runs', '--database', self.database)
        self.assertEqual(captured.code, 0)
        self.assertIn('no runs', captured.out)


class ExitCodeTests(unittest.TestCase):
    """A terminal outcome is information; the exit code says which outcome it was."""

    def code_for(self, name):
        return invoke('run', '--scenario', name, '--database', database_path(f'cli-{name}')).code

    def test_completed_exits_zero(self):
        self.assertEqual(self.code_for('arithmetic_minimal'), 0)

    def test_exhausted_exits_nonzero_but_is_not_a_crash(self):
        captured = invoke('run', '--scenario', 'arithmetic_exhausted',
                          '--database', database_path('cli-exhausted'))
        self.assertEqual(captured.code, 1)
        self.assertIn('EXHAUSTED', captured.out)
        self.assertIn('did not suffice', captured.out)
        self.assertIn('unresolved criteria', captured.out)
        self.assertEqual(captured.err, '')

    def test_failed_uses_its_own_code_and_explains_the_difference(self):
        captured = invoke('run', '--scenario', 'failed_no_decomposition',
                          '--database', database_path('cli-failed'))
        self.assertEqual(captured.code, 2)
        self.assertIn('FAILED means the run could not work at all', captured.out)
        self.assertIn('This is not EXHAUSTED', captured.out)

    def test_a_refused_configuration_uses_a_code_of_its_own(self):
        captured = invoke('run', '--scenario', 'unsupported_verifier',
                          '--database', database_path('cli-refused'))
        self.assertEqual(captured.code, cli.REFUSED)
        self.assertNotIn(captured.code, (0, 1, 2, 3))

    def test_every_terminal_state_maps_to_a_distinct_code(self):
        codes = list(runner.EXIT_CODES.values())
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn(cli.REFUSED, codes)
        self.assertNotIn(cli.STORAGE, codes)


class EvaluateCommandTests(unittest.TestCase):
    def test_evaluating_one_scenario_reports_its_checks_and_exits_zero(self):
        captured = invoke('evaluate', '--scenario', 'arithmetic_minimal')
        self.assertEqual(captured.code, 0)
        self.assertIn('PASS  arithmetic_minimal', captured.out)
        self.assertIn('terminal_state', captured.out)
        self.assertIn('OK', captured.out)

    def test_evaluating_a_refusal_fixture_checks_the_refusal_itself(self):
        captured = invoke('evaluate', '--scenario', 'unsupported_verifier')
        self.assertEqual(captured.code, 0)
        self.assertIn('config_rejected', captured.out)

    def test_an_unknown_scenario_fails_the_suite_rather_than_being_skipped(self):
        captured = invoke('evaluate', '--scenario', 'no_such_scenario')
        self.assertEqual(captured.code, 1)
        self.assertIn('FAIL', captured.out)

    def test_the_structured_form_carries_every_check(self):
        payload = invoke('evaluate', '--scenario', 'arithmetic_minimal', '--json').json()
        self.assertEqual(payload['scenarios'], 1)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['failed'], 0)
        self.assertTrue(all({'name', 'ok', 'detail'} <= set(check)
                            for check in payload['results'][0]['checks']))


class InspectCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.execution = executed('arithmetic_success')

    def inspect(self, *extra):
        return invoke('inspect', self.execution.run_id, '--database', self.execution.database,
                      *extra)

    def test_the_default_inspection_is_summarised_not_exhaustive(self):
        payload = self.inspect('--json').json()
        self.assertEqual(sorted(payload['sections']), sorted(inspection.DEFAULT_SECTIONS))
        self.assertNotIn('events', payload)
        self.assertNotIn('timeline', payload)

    def test_every_section_can_be_requested(self):
        payload = self.inspect('--all', '--json').json()
        for name in inspection.SECTIONS:
            with self.subTest(section=name):
                self.assertIn(name, payload)

    def test_a_single_section_can_be_selected(self):
        payload = self.inspect('--section', 'findings', '--json').json()
        self.assertEqual(payload['sections'], ['findings'])
        self.assertNotIn('metrics', payload)

    def test_an_unknown_section_is_refused_rather_than_ignored(self):
        captured = self.inspect('--section', 'secrets')
        self.assertEqual(captured.code, cli.REFUSED)
        self.assertIn('unknown section', captured.err)

    def test_an_unknown_run_is_refused(self):
        captured = invoke('inspect', 'no-such-run', '--database', self.execution.database)
        self.assertEqual(captured.code, cli.REFUSED)
        self.assertIn('no run', captured.err)

    def test_the_rendered_inspection_answers_why_a_finding_was_validated(self):
        captured = self.inspect('--section', 'findings')
        self.assertIn('validated by', captured.out)
        self.assertIn('TOOL_RESULT_ENTAILS_CLAIM', captured.out)
        self.assertIn('verified: arithmetic(', captured.out)

    def test_the_rendered_inspection_answers_why_a_branch_received_a_discovery(self):
        captured = self.inspect('--section', 'propagations')
        self.assertIn('score', captured.out)
        self.assertIn('CRITERION:c1', captured.out)

    def test_the_timeline_is_available_without_reading_sqlite(self):
        captured = self.inspect('--trace')
        for kind in ('TASK_ASSIGNED', 'FINDING_VALIDATED', 'CROSS_POLLINATION',
                     'SYNTHESIS_GATE_EVALUATED', 'FINAL_REVIEW_COMPLETED', 'RUN_COMPLETED'):
            with self.subTest(kind=kind):
                self.assertIn(kind, captured.out)

    def test_the_default_timeline_omits_execution_seam_bookkeeping(self):
        self.assertNotIn('PROVIDER_REQUESTED', self.inspect('--trace').out)
        self.assertIn('PROVIDER_REQUESTED', self.inspect('--trace', '--full').out)


class OutputSafetyTests(unittest.TestCase):
    """Inspection is a projection of records, never a dump of what a model was shown."""

    @classmethod
    def setUpClass(cls):
        cls.execution = executed('arithmetic_success')

    def test_no_context_payload_reaches_the_inspection_output(self):
        payload = json.dumps(invoke('inspect', self.execution.run_id, '--database',
                                    self.execution.database, '--all', '--full', '--json').json())
        self.assertNotIn('context_json', payload)
        self.assertNotIn('allowed_output_fields', payload)

    def test_no_before_after_record_image_reaches_the_timeline(self):
        entries = self.execution.report['timeline']
        self.assertTrue(entries)
        for entry in entries:
            self.assertNotIn('change', entry['summary'])
            self.assertNotEqual(entry['type'], 'RECORD_CHANGED')

    def test_assignments_expose_provenance_by_hash_rather_than_by_payload(self):
        for assignment in self.execution.report['assignments']:
            self.assertTrue(assignment['context_hash'])
            self.assertNotIn('context_json', assignment)


class ParserTests(unittest.TestCase):
    def refuse(self, argv):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(argv)
        return err.getvalue()

    def test_a_missing_subcommand_is_a_usage_error(self):
        self.assertIn('required', self.refuse([]))

    def test_run_requires_a_scenario(self):
        self.assertIn('--scenario', self.refuse(['run']))

    def test_the_default_database_is_a_file_so_a_run_stays_inspectable(self):
        args = cli.build_parser().parse_args(['run', '--scenario', 'x'])
        self.assertEqual(args.database, cli.DEFAULT_DATABASE)
        self.assertNotEqual(args.database, ':memory:')

    def test_evaluate_defaults_to_an_in_memory_database(self):
        args = cli.build_parser().parse_args(['evaluate'])
        self.assertEqual(args.database, ':memory:')


if __name__ == '__main__':
    unittest.main()
