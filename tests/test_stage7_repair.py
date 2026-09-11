"""Repair and revision limits: bounded rounds, duplicate suppression, no endless loops."""
import json
import unittest
from dataclasses import replace
from stage5_support import TOOLS, agent, explore
from stage7_support import (CompletingProvider, TWO_CRITERIA, final_review, final_reviews,
                            omit_support, report_of, repairs_of, results_of, run_with,
                            setup_completing_run, syntheses_of, two_branch_run)
from swarm.domain import (AgentGroup, Gap, ResultStatus, RevisionKind, ReviewDecision, RunState,
                          Task, TaskStatus)
from swarm.events import EventType
from swarm.orchestration import WorkController
from swarm.persistence import SQLiteRepository


class RepairCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def controller(self, provider, **kwargs):
        return WorkController(self.repo, 'r', {'fake': provider}, TOOLS, **kwargs)

    def events(self, kind):
        return [json.loads(e.detail_json) for e in self.repo.inspect('r').events if e.type == kind]

    def wording(self, *, decision='REVISE'):
        """A reviewer that complains only about how the answer reads."""
        def judge(context):
            return final_review(context, decision, issues=('the ordering is confusing',))
        return judge

    def missing_evidence(self, criterion_ids=('c2',)):
        """A reviewer that names an unsupported claim and where it belongs."""
        def judge(context):
            return final_review(context, 'REVISE', criterion_ids=list(criterion_ids),
                                unsupported_claims=('the totals were also cross-checked',))
        return judge


class PresentationLimitTests(RepairCase):
    async def test_presentation_revisions_are_bounded_and_counted(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.wording()] * 6)
        s = await self.controller(provider).run_until_idle()
        run = s['r']
        self.assertEqual(run.state, RunState.EXHAUSTED)
        self.assertEqual(run.presentation_revisions, run.presentation_revision_limit)
        self.assertEqual(run.stop_reason, 'PRESENTATION_REVISION_LIMIT')
        self.assertEqual(run.repair_rounds, 0)

    async def test_each_revision_creates_a_new_version_and_never_edits_the_old_one(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.wording()] * 6)
        s = await self.controller(provider).run_until_idle()
        versions = results_of(s)
        self.assertEqual([r.version for r in versions], [1, 2, 3])
        self.assertEqual([r.status for r in versions[:2]],
                         [ResultStatus.REVISED, ResultStatus.REVISED])
        self.assertEqual([r.revision_kind for r in versions[:2]],
                         [RevisionKind.PRESENTATION, RevisionKind.PRESENTATION])
        self.assertEqual(versions[1].supersedes_id, versions[0].id)

    async def test_the_revision_feedback_reaches_the_next_synthesis(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.wording(), 'PASS'])
        s = await self.controller(provider).run_until_idle()
        self.assertEqual(s['r'].state, RunState.COMPLETED)
        second = syntheses_of(s)[1]
        self.assertTrue(any('ordering is confusing' in note for note in second.limitations))
        self.assertIsNotNone(second.source_review_id)
        self.assertEqual(second.source_result_id, results_of(s)[0].id)

    async def test_a_presentation_revision_creates_no_repair_work(self):
        two_branch_run(self.repo)
        await self.controller(CompletingProvider(verdicts=[self.wording(), 'PASS'])).run_until_idle()
        self.assertEqual(repairs_of(self.repo.snapshot('r')), [])


class EvidenceRepairTests(RepairCase):
    async def test_an_evidence_revision_creates_bounded_repair_work(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.missing_evidence()] * 4,
                                      repair=((7, 8), 15))
        s = await self.controller(provider).run_until_idle()
        created = [e for e in self.events(EventType.REPAIR_WORK_CREATED) if e['admitted']]
        self.assertTrue(created)
        self.assertTrue(all(e['review_id'] for e in created))
        self.assertLessEqual(s['r'].repair_rounds, s['r'].repair_round_limit)

    async def test_evidence_repair_rounds_are_bounded(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.missing_evidence()] * 8,
                                      repair=((7, 8), 15))
        s = await self.controller(provider, ).run_until_idle()
        self.assertIn(s['r'].state, (RunState.EXHAUSTED, RunState.COMPLETED))
        self.assertLessEqual(s['r'].repair_rounds, s['r'].repair_round_limit)

    async def test_an_unsupported_claim_the_reviewer_cannot_locate_exhausts(self):
        """The controller authors work against a criterion, never against free text."""
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.missing_evidence(criterion_ids=())])
        s = await self.controller(provider).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertTrue(s['r'].stop_reason.startswith('UNREPAIRABLE_REVISE: UNSUPPORTED_CLAIMS'))
        self.assertEqual(s['r'].repair_rounds, 0)

    async def test_a_reject_the_controller_cannot_confirm_exhausts_immediately(self):
        two_branch_run(self.repo)
        s = await self.controller(CompletingProvider(verdicts=['REJECT'])).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertEqual(s['r'].stop_reason, 'UNREPAIRABLE_REJECT: NO_CONFIRMED_DEFECT')
        self.assertEqual(results_of(s)[0].status, ResultStatus.REJECTED)
        self.assertEqual(s['r'].repair_rounds, 0)

    async def test_a_rejected_result_does_not_invalidate_its_underlying_findings(self):
        two_branch_run(self.repo)
        s = await self.controller(CompletingProvider(verdicts=['REJECT'])).run_until_idle()
        from swarm.domain import Finding, FindingStatus
        validated = [f for f in s.values() if isinstance(f, Finding)
                     and f.status == FindingStatus.VALIDATED]
        self.assertEqual(len(validated), 2)
        self.assertEqual(sorted(report_of(s).validated_finding_ids),
                         sorted(f.id for f in validated))

    async def test_duplicate_repair_for_the_same_gap_is_refused_with_a_reason(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(wrong={'tb': 99})
        s = await self.controller(provider).run_until_idle()
        refused = [e for e in self.events(EventType.REPAIR_WORK_CREATED) if not e['admitted']]
        self.assertTrue(any(e['reason'] == 'DUPLICATE_REPAIR' for e in refused), refused)
        self.assertEqual(len(repairs_of(s)), 1)


class RepairCycleTests(RepairCase):
    """A repair wave is charged like any other, and never overlaps an open one."""

    async def open_wave(self):
        two_branch_run(self.repo)
        controller = self.controller(CompletingProvider())
        controller._open_run()
        return controller

    async def test_a_repair_wave_closes_the_open_wave_before_charging_another(self):
        from swarm.domain import Cycle, CycleStatus
        from swarm.finalreview import repair_task
        controller = await self.open_wave()
        before = self.repo.snapshot('r')
        self.assertEqual([c.status for c in before.values() if isinstance(c, Cycle)],
                         [CycleStatus.OPEN])
        task = repair_task(Gap(criterion_id='c2', reason='UNSUPPORTED'), None,
                           controller.identity, 'r', before)
        self.assertTrue(controller.open_repair_cycle([task], 'TEST_REPAIR', 'a gap'))
        after = self.repo.snapshot('r')
        cycles = sorted((c for c in after.values() if isinstance(c, Cycle)), key=lambda c: c.number)
        self.assertEqual([c.status for c in cycles], [CycleStatus.CLOSED, CycleStatus.OPEN])
        self.assertEqual(cycles[-1].task_ids, (task.id,))
        self.assertEqual(after['r'].cycle, 2)

    async def test_a_repair_wave_with_no_task_charges_nothing(self):
        controller = await self.open_wave()
        before = self.repo.snapshot('r')['r'].cycle
        self.assertFalse(controller.open_repair_cycle([], 'TEST_REPAIR', 'nothing to do'))
        self.assertEqual(self.repo.snapshot('r')['r'].cycle, before)


class LoopBoundTests(RepairCase):
    async def test_synthesis_and_review_cannot_loop_forever(self):
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.wording()] * 20)
        s = await self.controller(provider).run_until_idle()
        self.assertIn(s['r'].state, (RunState.EXHAUSTED, RunState.COMPLETED))
        self.assertLessEqual(s['r'].synthesis_attempts, s['r'].synthesis_attempt_limit)
        self.assertLessEqual(len(final_reviews(s)), s['r'].synthesis_attempt_limit)

    async def test_a_repeated_synthesis_over_unchanged_support_is_refused(self):
        """A synthesizer that never returns a result stops the run instead of retrying it."""
        two_branch_run(self.repo)
        def broken(context):
            from stage5_support import done
            return done(summary='nothing to say')
        s = await self.controller(CompletingProvider(synthesizer=broken)).run_until_idle()
        self.assertEqual(s['r'].state, RunState.EXHAUSTED)
        self.assertTrue(s['r'].stop_reason.startswith('SYNTHESIS_REPEATED_FAILURE'))
        self.assertEqual(len(syntheses_of(s)), 1)

    async def test_stale_feedback_never_repairs_a_newer_version(self):
        """Each review names one version; the second review judges the version it was given."""
        two_branch_run(self.repo)
        provider = CompletingProvider(verdicts=[self.wording(), 'PASS'])
        s = await self.controller(provider).run_until_idle()
        versions = results_of(s)
        reviews = final_reviews(s)
        self.assertEqual([r.target_id for r in reviews], [versions[0].id, versions[1].id])
        self.assertEqual([r.target_revision for r in reviews], [1, 1])
        self.assertEqual(versions[0].review_id, reviews[0].id)
        self.assertEqual(versions[1].review_id, reviews[1].id)


class ExhaustionTraceTests(RepairCase):
    async def test_the_exhausted_run_explains_itself(self):
        two_branch_run(self.repo)
        s = await self.controller(CompletingProvider(wrong={'tb': 99})).run_until_idle()
        run, report = s['r'], report_of(s)
        self.assertEqual(run.state, RunState.EXHAUSTED)
        self.assertIn('c2', run.stop_reason)
        self.assertEqual([(g.criterion_id, g.reason) for g in report.gaps], [('c2', 'UNSUPPORTED')])
        self.assertEqual(len(report.validated_finding_ids), 1)
        self.assertEqual([str(e.type) for e in self.repo.inspect('r').events
                          if e.type == EventType.RUN_EXHAUSTED], ['RUN_EXHAUSTED'])

    async def test_every_gate_evaluation_is_recorded_with_its_reasons(self):
        two_branch_run(self.repo)
        await self.controller(CompletingProvider(wrong={'tb': 99})).run_until_idle()
        gates = self.events(EventType.SYNTHESIS_GATE_EVALUATED)
        self.assertTrue(gates)
        self.assertTrue(all('status' in g and 'criteria' in g for g in gates))
        self.assertTrue(any('CRITERION_UNSUPPORTED: c2' in g['reasons'] for g in gates))


if __name__ == '__main__':
    unittest.main()
