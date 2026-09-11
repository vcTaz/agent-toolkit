"""Inspection, provenance, metrics and the causal trace.

The question this suite asks of every section is the same: can a developer reconstruct why
the run did what it did *from stored records*? An explanation that is composed rather than
projected would still read plausibly and would prove nothing, so each test below ties the
inspection output back to the record that authorised it.
"""
import json
import unittest
from stage8_support import ExampleCase, executed, invoke
from swarm import inspection, metrics as metrics_module, render, timeline
from swarm.domain import Finding, Result, ReviewRecord
from swarm.events import EventType
from swarm.persistence import SQLiteRepository


class SectionTests(ExampleCase):
    example = 'arithmetic_success'

    def test_every_declared_section_is_produced(self):
        for name in inspection.SECTIONS:
            with self.subTest(section=name):
                self.assertIn(name, self.report)

    def test_the_default_section_set_is_a_subset_of_everything(self):
        self.assertTrue(set(inspection.DEFAULT_SECTIONS) < set(inspection.SECTIONS))

    def test_requesting_one_section_produces_only_that_section(self):
        repository = SQLiteRepository(self.execution.database)
        self.addCleanup(repository.close)
        report = inspection.build(repository.inspect(self.execution.run_id),
                                  self.execution.run_id, sections=('metrics',))
        self.assertEqual(report['sections'], ['metrics'])
        self.assertNotIn('findings', report)

    def test_an_unknown_run_is_a_lookup_error(self):
        repository = SQLiteRepository(':memory:')
        self.addCleanup(repository.close)
        with self.assertRaises(Exception):
            inspection.build(repository.inspect('nope'), 'nope')

    def test_the_whole_report_is_json_serialisable(self):
        self.assertIsInstance(json.dumps(self.report), str)


class CriterionReadingTests(ExampleCase):
    example = 'arithmetic_exhausted'

    def test_each_criterion_carries_the_gate_reading_that_decided_it(self):
        readings = {entry['id']: entry for entry in self.report['criteria']}
        self.assertEqual(set(readings), {'c1', 'c2'})
        self.assertIsNone(readings['c1']['blocking_gap'])
        self.assertEqual(readings['c2']['blocking_gap'], 'UNSUPPORTED')

    def test_a_clean_criterion_names_the_host_verified_support_behind_it(self):
        c1 = next(e for e in self.report['criteria'] if e['id'] == 'c1')
        self.assertTrue(c1['verified_ids'])
        self.assertEqual(sorted(c1['verified_ids']), sorted(c1['supporting_ids']))


class ProvenanceTests(ExampleCase):
    """The five questions Stage 8 has to be able to answer from records."""
    example = 'arithmetic_success'

    def test_why_was_this_finding_validated(self):
        for finding in self.execution.findings('VALIDATED'):
            with self.subTest(finding=finding['id']):
                self.assertIn('validated by', finding['why'])
                validations = [e for e in finding['lifecycle'] if e['kind'] == 'validation']
                self.assertTrue(validations)
                self.assertIn('TOOL_RESULT_ENTAILS_CLAIM', validations[-1]['verification'])

    def test_what_evidence_verified_it(self):
        entries = self.report['evidence']
        self.assertTrue(entries)
        for entry in entries:
            self.assertTrue(entry['verified'])
            self.assertEqual(entry['tool_name'], 'arithmetic')
            arguments = json.loads(entry['arguments'])
            value = json.loads(entry['value'])
            # The verifier read the claim's own operands, not merely a successful call.
            self.assertEqual(sum(arguments['numbers']), value['actual'])
            self.assertTrue(value['matches'])
            self.assertIn(str(value['actual']), entry['claim'])

    def test_a_validated_claim_keeps_both_independent_recomputations(self):
        """The author's own recorded tool result and the validator's are both verified.

        They are distinguished by their tool-result reference, not by their arguments,
        which are identical by construction: the validator recomputed the same claim.
        """
        references = {}
        for entry in self.report['evidence']:
            references.setdefault(entry['target_id'], set()).add(entry['reference'])
        self.assertTrue(references)
        for target, seen in references.items():
            with self.subTest(finding=target):
                self.assertGreaterEqual(len(seen), 2)

    def test_why_did_this_agent_receive_this_finding(self):
        for propagation in self.report['propagations']:
            with self.subTest(propagation=propagation['id']):
                self.assertTrue(propagation['matched_features'])
                self.assertIn('score', propagation['why'])
                self.assertIn(propagation['canonical_finding_id'],
                              {f['id'] for f in self.report['findings']})

    def test_why_was_this_propagation_sent_to_this_branch(self):
        tasks = {t['id']: t for t in self.report['tasks']}
        for propagation in self.report['propagations']:
            target = tasks[propagation['target_task_id']]
            source = next(f for f in self.report['findings']
                          if f['id'] == propagation['canonical_finding_id'])
            shared = set(source['criterion_ids']) & set(target['acceptance_criterion_ids'])
            self.assertTrue(shared or set(source['tags']) & set(target['tags']))

    def test_which_findings_support_the_final_result(self):
        support = self.report['provenance']['result_support']
        self.assertTrue(support)
        cited = {identity for entry in support for identity in entry['finding_ids']}
        self.assertEqual(cited, set(self.report['result']['finding_ids']))

    def test_the_provenance_section_records_every_final_review_decision(self):
        recorded = [entry['decision'] for entry in self.report['provenance']['final_reviews']]
        self.assertEqual(recorded, ['REVISE', 'PASS'])


class ExhaustionProvenanceTests(ExampleCase):
    example = 'arithmetic_exhausted'

    def test_why_did_the_run_become_exhausted(self):
        provenance = self.report['provenance']
        self.assertEqual(provenance['terminal_state'], 'EXHAUSTED')
        self.assertIn('c2', provenance['stop_reason'])
        self.assertEqual([g['criterion_id'] for g in provenance['terminal_report']['gaps']], ['c2'])

    def test_the_last_gate_evaluation_names_the_blocking_reason(self):
        gate = self.report['provenance']['final_gate']
        self.assertEqual(gate['status'], 'EXHAUSTED')
        self.assertTrue(any('c2' in reason for reason in gate['reasons']))

    def test_every_repair_refusal_carries_its_reason(self):
        refused = [d for d in self.report['provenance']['repair_decisions'] if not d['admitted']]
        self.assertTrue(refused)
        for decision in refused:
            self.assertTrue(decision['reason'])
            self.assertEqual(decision['criterion_id'], 'c2')

    def test_a_rejected_claim_explains_itself_by_the_evidence_that_refused_it(self):
        for finding in self.execution.findings('REJECTED'):
            with self.subTest(finding=finding['id']):
                self.assertIn('rejected by', finding['why'])
                self.assertIn('CONTRADICTS', finding['why'])


class TimelineTests(ExampleCase):
    example = 'arithmetic_success'

    def test_the_trace_is_in_causal_order(self):
        sequences = [entry['sequence'] for entry in self.report['timeline']]
        self.assertEqual(sequences, sorted(sequences))

    def test_the_narrative_covers_the_whole_loop(self):
        kinds = [entry['type'] for entry in self.report['timeline']]
        # Scenario tasks are seeded rather than created, so the narrative starts at the
        # first assignment; TASK_CREATED first appears when the controller authors a review.
        expected = ['TASK_ASSIGNED', 'FINDING_CREATED', 'TASK_CREATED', 'REVIEW_COMPLETED',
                    'FINDING_VALIDATED', 'KNOWLEDGE_PROMOTED', 'CROSS_POLLINATION',
                    'PROPAGATION_DELIVERED', 'RECONSIDERATION_COMPLETED', 'SYNTHESIS_STARTED',
                    'RESULT_CREATED', 'FINAL_REVIEW_COMPLETED', 'RUN_COMPLETED']
        positions = [kinds.index(kind) for kind in expected]
        self.assertEqual(positions, sorted(positions), 'phases appear out of causal order')

    def test_every_trace_line_carries_identifiers_for_deeper_inspection(self):
        entries = [e for e in self.report['timeline']
                   if e['type'] in ('TASK_ASSIGNED', 'RESULT_CREATED', 'FINDING_VALIDATED')]
        self.assertTrue(entries)
        for entry in entries:
            self.assertTrue(timeline.identifiers(entry))

    def test_the_core_narrative_and_the_execution_detail_do_not_overlap(self):
        self.assertEqual(set(timeline.CORE_EVENTS) & set(timeline.DETAIL_EVENTS), set())

    def test_record_changed_is_in_neither_set_because_it_carries_record_images(self):
        self.assertNotIn(EventType.RECORD_CHANGED, timeline.CORE_EVENTS)
        self.assertNotIn(EventType.RECORD_CHANGED, timeline.DETAIL_EVENTS)

    def test_a_detail_key_outside_the_allowlist_is_never_printed_verbatim(self):
        summary = timeline.summarise({'reason': 'kept', 'context': 'SECRET-PAYLOAD',
                                      'result': {'answer': 'SECRET-ANSWER'}})
        self.assertIn('reason=kept', summary)
        self.assertNotIn('SECRET', summary)

    def test_a_counted_key_is_reported_by_shape_and_bounded(self):
        summary = timeline.summarise({'gaps': ['a' * 200, 'b' * 200]})
        self.assertIn('gaps[2]', summary)
        self.assertLess(len(summary), 120)


class MetricsTests(ExampleCase):
    example = 'arithmetic_success'

    def test_metrics_agree_with_the_records_they_describe(self):
        values = self.report['metrics']
        self.assertEqual(values['tasks']['total'], len(self.report['tasks']))
        self.assertEqual(values['findings']['total'], len(self.report['findings']))
        self.assertEqual(values['reviews']['total'], len(self.report['reviews']))
        self.assertEqual(values['propagations']['total'], len(self.report['propagations']))
        self.assertEqual(values['results']['versions'], len(self.report['results']))
        self.assertEqual(values['assignments']['total'], len(self.report['assignments']))

    def test_metrics_agree_with_the_runs_own_durable_counters(self):
        values, run = self.report['metrics'], self.report['run']
        self.assertEqual(values['provider_requests'], run['provider_requests'])
        self.assertEqual(values['tool_calls'], run['tool_calls'])
        self.assertEqual(values['cycles_charged'], run['cycle'])
        self.assertEqual(values['repair_rounds'], run['repair_rounds'])
        self.assertEqual(values['presentation_revisions'], run['presentation_revisions'])

    def test_review_kinds_are_counted_separately(self):
        values = self.report['metrics']['reviews']
        self.assertEqual(values['criticism'] + values['validation'] + values['final'],
                         values['total'])
        self.assertEqual(values['final'], 2)
        self.assertTrue(values['verified_evidence'])

    def test_reconsideration_outcomes_are_counted_by_outcome(self):
        counts = self.report['metrics']['reconsiderations']
        self.assertEqual(sum(counts.values()), len(self.report['propagations']))
        self.assertIn('UNREPORTED', counts)

    def test_the_terminal_state_and_a_duration_are_reported(self):
        values = self.report['metrics']
        self.assertEqual(values['terminal_state'], 'COMPLETED')
        self.assertIsInstance(values['duration_seconds'], float)
        self.assertGreaterEqual(values['duration_seconds'], 0)

    def test_a_missing_timestamp_yields_no_duration_rather_than_a_crash(self):
        self.assertIsNone(metrics_module._moment('not a time'))


class RenderTests(ExampleCase):
    example = 'arithmetic_exhausted'

    def test_a_non_success_run_is_never_rendered_as_an_answer(self):
        text = render.run_report(self.report)
        self.assertIn('validated partial knowledge', text)
        self.assertIn('is not an answer', text)
        self.assertNotIn('answer  ', text)

    def test_a_completed_terminal_report_does_not_call_its_knowledge_partial(self):
        completed = executed('arithmetic_minimal').report
        text = render.outcome_block(completed['outcome'], completed['findings'])
        self.assertIn('validated knowledge:', text)
        self.assertNotIn('validated partial knowledge', text)

    def test_a_completed_run_leads_with_its_answer_rather_than_its_gaps(self):
        text = render.run_report(executed('arithmetic_minimal').report)
        self.assertIn('answer', text)
        self.assertNotIn('validated partial knowledge', text)

    def test_the_terminal_note_distinguishes_failed_from_exhausted(self):
        self.assertNotEqual(render.TERMINAL_NOTES['FAILED'], render.TERMINAL_NOTES['EXHAUSTED'])
        self.assertIn('could not work at all', render.TERMINAL_NOTES['FAILED'])
        self.assertIn('did not suffice', render.TERMINAL_NOTES['EXHAUSTED'])

    def test_rendering_an_empty_trace_says_so_instead_of_printing_nothing(self):
        self.assertEqual(render.trace([]), 'no events')

    def test_the_evidence_section_distinguishes_two_results_over_the_same_claim(self):
        completed = executed('arithmetic_success').report
        text = render.SECTION_RENDERERS['evidence'](completed['evidence'])
        references = [line for line in text if ' ref ' in line]
        self.assertEqual(len(references), len(completed['evidence']))
        self.assertEqual(len(set(references)), len(references))

    def test_an_empty_section_says_none_rather_than_printing_nothing(self):
        self.assertEqual(render.SECTION_RENDERERS['evidence']([]), ['  none'])

    def test_the_metrics_line_reports_both_use_and_limit(self):
        line = render.metrics_line(self.report['metrics'])
        self.assertIn(f'/{self.report["run"]["limits"]["provider_request_limit"]}', line)
        self.assertIn('cycles=', line)


if __name__ == '__main__':
    unittest.main()
