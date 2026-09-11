"""End-to-end Stage-7 scenarios: the whole loop from exploration to a terminal outcome.

Nothing here is satisfied by a fake-provider assertion. Every claim that reaches the answer
was verified by the trusted arithmetic tool against its own operands, every promotion was an
independent review, and completion required the controller's own gate to hold at the moment
it wrote COMPLETED.
"""
import json
import unittest
from dataclasses import replace
from stage5_support import TOOLS, agent, explore
from stage7_support import (CompletingProvider, TWO_CRITERIA, final_review, final_reviews,
                            omit_support, report_of, repairs_of, results_of, run_with,
                            setup_completing_run, syntheses_of, two_branch_run)
from swarm.domain import (AgentGroup, Evidence, Finding, FindingStatus, Propagation,
                          PropagationStatus, ReconsiderationOutcome, ResultStatus, ReviewDecision,
                          ReviewKind, ReviewRecord, RunState, Task, TaskStatus, validate_records)
from swarm.events import EventType
from swarm.orchestration import WorkController
from swarm.persistence import SQLiteRepository


class IntegrationCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def controller(self, provider, **kwargs):
        return WorkController(self.repo, 'r', {'fake': provider}, TOOLS, **kwargs)

    def events(self, *kinds):
        wanted = set(kinds)
        return [(str(e.type), json.loads(e.detail_json))
                for e in self.repo.inspect('r').events if e.type in wanted]

    def trace(self):
        return [t for t, _ in self.events(
            EventType.RUN_STATE_CHANGED, EventType.CROSS_POLLINATION,
            EventType.RECONSIDERATION_COMPLETED, EventType.SYNTHESIS_GATE_EVALUATED,
            EventType.RESULT_CREATED, EventType.FINAL_REVIEW_COMPLETED,
            EventType.RESULT_REVISION_REQUESTED, EventType.REPAIR_WORK_CREATED,
            EventType.RUN_COMPLETED, EventType.RUN_EXHAUSTED)]

    def shared_criterion_run(self, *, first=(1, 2, 3), second=(4, 5), third=(10, 20), run=None):
        """Two branches investigate c1 independently; a third covers c2.

        The shared criterion is what makes the run cross-pollinate: branch A's validated
        total is relevant to branch C's task, so a delivery and a reconsideration happen
        before the gate is ever consulted.
        """
        tasks = [explore('ta', list(first), group_id='ga'),
                 explore('tc', list(second), group_id='gc'),
                 replace(explore('tb', list(third), group_id='gb'),
                         acceptance_criterion_ids=('c2',))]
        setup_completing_run(
            self.repo, tasks,
            [agent('a', 'ga'), agent('b', 'gb'), agent('c', 'gc'), agent('critic'),
             agent('validator'), agent('writer'), agent('judge')],
            run=run,
            groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',)),
                    AgentGroup(id='gb', run_id='r', agent_ids=('b',), task_ids=('tb',)),
                    AgentGroup(id='gc', run_id='r', agent_ids=('c',), task_ids=('tc',))])
        return tasks


class CompletedScenarioTests(IntegrationCase):
    """explore → critique → validate → consolidate → propagate → reconsider →
    gate READY → synthesize → final review REVISE → resynthesize → PASS → COMPLETED."""

    async def run_scenario(self):
        self.shared_criterion_run()
        def omission(context):
            return final_review(context, 'REVISE', criterion_ids=['c1'],
                                issues=('the answer omits one of the supported totals',))
        provider = CompletingProvider(verdicts=[omission, 'PASS'],
                                      synthesizer=[omit_support('[4, 5]'), None])
        self.provider = provider
        return await self.controller(provider).run_until_idle()

    async def test_the_run_completes_through_a_presentation_revision(self):
        s = await self.run_scenario()
        self.assertEqual(s['r'].state, RunState.COMPLETED)
        self.assertEqual(s['r'].presentation_revisions, 1)
        self.assertEqual(s['r'].repair_rounds, 0)
        versions = results_of(s)
        self.assertEqual([r.status for r in versions],
                         [ResultStatus.REVISED, ResultStatus.ACCEPTED])
        self.assertEqual(s['r'].result_id, versions[1].id)

    async def test_every_phase_of_the_loop_actually_ran(self):
        await self.run_scenario()
        trace = self.trace()
        for kind in ('CROSS_POLLINATION', 'RECONSIDERATION_COMPLETED', 'SYNTHESIS_GATE_EVALUATED',
                     'RESULT_CREATED', 'FINAL_REVIEW_COMPLETED', 'RESULT_REVISION_REQUESTED',
                     'RUN_COMPLETED'):
            with self.subTest(kind=kind):
                self.assertIn(kind, trace)

    async def test_the_first_review_was_revise_and_the_second_was_pass(self):
        s = await self.run_scenario()
        self.assertEqual([r.decision for r in final_reviews(s)],
                         [ReviewDecision.REVISE, ReviewDecision.PASS])
        self.assertEqual(len(syntheses_of(s)), 2)
        self.assertEqual(repairs_of(s), [])

    async def test_the_accepted_answer_cites_only_host_verified_knowledge(self):
        s = await self.run_scenario()
        accepted = s[s['r'].result_id]
        self.assertTrue(accepted.finding_ids)
        for identity, revision in zip(accepted.finding_ids, accepted.finding_revisions):
            finding = s[identity]
            self.assertEqual(finding.status, FindingStatus.VALIDATED)
            self.assertEqual(finding.revision, revision)
            verified = [item for review in finding.review_ids for item in s[review].evidence
                        if item.verified]
            self.assertTrue(verified, f'{identity} rests on no host-verified evidence')
            for item in verified:
                # The verifier read the claim's own operands, not merely a successful call.
                self.assertEqual(item.tool_name, 'arithmetic')
                self.assertTrue(json.loads(item.value)['matches'])

    async def test_the_revision_added_the_omitted_support_rather_than_new_knowledge(self):
        s = await self.run_scenario()
        first, second = results_of(s)
        self.assertTrue(set(first.finding_ids) < set(second.finding_ids))
        self.assertEqual({f.id for f in s.values() if isinstance(f, Finding)
                          and f.status == FindingStatus.VALIDATED},
                         set(second.finding_ids))

    async def test_the_coverage_of_the_accepted_result_is_host_computed(self):
        s = await self.run_scenario()
        accepted = s[s['r'].result_id]
        for entry in accepted.coverage:
            for identity in entry.finding_ids:
                self.assertIn(entry.criterion_id, s[identity].criterion_ids)
        self.assertEqual(sorted(e.criterion_id for e in accepted.coverage if e.required),
                         ['c1', 'c2'])

    async def test_the_causation_chain_links_the_result_to_its_review(self):
        s = await self.run_scenario()
        accepted = s[s['r'].result_id]
        correlated = [e for e in self.repo.inspect('r').events if e.correlation_id == accepted.id]
        self.assertTrue({str(e.type) for e in correlated} >=
                        {'RESULT_CREATED', 'FINAL_REVIEW_STARTED', 'FINAL_REVIEW_COMPLETED'})
        self.assertEqual(accepted.review_id, final_reviews(s)[-1].id)

    async def test_the_synthesizer_and_the_final_reviewer_are_different_identities(self):
        s = await self.run_scenario()
        from swarm.domain import Assignment
        authors = {s[r.created_by_assignment].agent_id for r in results_of(s)}
        judges = {s[r.assignment_id].agent_id for r in final_reviews(s)}
        self.assertTrue(authors)
        self.assertTrue(judges)
        self.assertEqual(authors & judges, set())

    async def test_the_terminal_snapshot_satisfies_every_invariant(self):
        s = await self.run_scenario()
        validate_records(s.values())
        self.assertEqual(self.repo.inspect('r').status, 'COMPLETED')

    async def test_the_completed_report_carries_the_answer_and_its_knowledge(self):
        s = await self.run_scenario()
        report = report_of(s)
        self.assertEqual(report.state, RunState.COMPLETED)
        self.assertEqual(report.result_id, s['r'].result_id)
        self.assertEqual(report.gaps, ())
        self.assertEqual(sorted(report.validated_finding_ids),
                         sorted(f.id for f in s.values() if isinstance(f, Finding)
                                and f.status == FindingStatus.VALIDATED))


class ExhaustedScenarioTests(IntegrationCase):
    """A required criterion cannot be verified; bounded repair is spent and the run exhausts."""

    async def run_scenario(self):
        self.shared_criterion_run()
        # Branch B asserts a total the arithmetic verifier refuses, and every repair attempt
        # repeats the same unverifiable claim.
        provider = CompletingProvider(wrong={'tb': 99}, repair=((10, 20), 99))
        return await self.controller(provider).run_until_idle()

    async def test_the_run_exhausts_and_never_reports_an_answer(self):
        s = await self.run_scenario()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertIsNone(s['r'].result_id)
        self.assertEqual(results_of(s), [])
        self.assertEqual(self.repo.inspect('r').status, 'EXHAUSTED')

    async def test_the_unverifiable_claim_was_rejected_by_evidence_not_opinion(self):
        s = await self.run_scenario()
        rejected = [f for f in s.values() if isinstance(f, Finding)
                    and f.status == FindingStatus.REJECTED]
        self.assertTrue(rejected)
        for finding in rejected:
            trails = [s[i].verification for i in finding.review_ids
                      if s[i].kind == ReviewKind.VALIDATION]
            self.assertTrue(any('TOOL_RESULT_CONTRADICTS_CLAIM' in trail for trail in trails), trails)

    async def test_bounded_repair_was_attempted_and_then_refused(self):
        s = await self.run_scenario()
        created = [d for t, d in self.events(EventType.REPAIR_WORK_CREATED) if d['admitted']]
        refused = [d for t, d in self.events(EventType.REPAIR_WORK_CREATED) if not d['admitted']]
        self.assertTrue(created)
        self.assertTrue(refused)
        self.assertLessEqual(s['r'].repair_rounds, s['r'].repair_round_limit)
        self.assertEqual({d['criterion_id'] for d in created}, {'c2'})

    async def test_the_terminal_report_keeps_the_partial_knowledge_and_the_gap(self):
        s = await self.run_scenario()
        report = report_of(s)
        self.assertEqual(report.state, RunState.EXHAUSTED)
        self.assertEqual([(g.criterion_id, g.reason) for g in report.gaps], [('c2', 'UNSUPPORTED')])
        validated = {f.id for f in s.values() if isinstance(f, Finding)
                     and f.status == FindingStatus.VALIDATED}
        self.assertEqual(set(report.validated_finding_ids), validated)
        self.assertTrue(validated, 'partial knowledge is preserved, not discarded')

    async def test_the_run_says_why_it_stopped(self):
        s = await self.run_scenario()
        self.assertIn('c2', s['r'].stop_reason)
        exhausted = [d for t, d in self.events(EventType.RUN_EXHAUSTED)]
        self.assertEqual(len(exhausted), 1)
        self.assertEqual(exhausted[0]['stop_reason'], s['r'].stop_reason)
        self.assertEqual(exhausted[0]['gaps'], ['c2:UNSUPPORTED'])

    async def test_the_exhausted_snapshot_satisfies_every_invariant(self):
        s = await self.run_scenario()
        validate_records(s.values())

    async def test_partial_knowledge_is_never_presented_as_a_completed_result(self):
        s = await self.run_scenario()
        self.assertNotEqual(s['r'].state, RunState.COMPLETED)
        self.assertEqual([r for r in results_of(s) if r.status == ResultStatus.ACCEPTED], [])


class DeterminismTests(IntegrationCase):
    async def test_the_same_scenario_produces_the_same_terminal_record(self):
        outcomes = []
        for _ in range(3):
            self.repo = SQLiteRepository(':memory:')
            self.addCleanup(self.repo.close)
            self.shared_criterion_run()
            s = await self.controller(CompletingProvider()).run_until_idle()
            accepted = s[s['r'].result_id]
            outcomes.append((str(s['r'].state), accepted.version, accepted.finding_ids,
                             tuple((e.criterion_id, e.finding_ids) for e in accepted.coverage),
                             s['r'].provider_requests, s['r'].cycle))
        self.assertEqual(len(set(outcomes)), 1, outcomes)


if __name__ == '__main__':
    unittest.main()
