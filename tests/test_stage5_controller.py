"""Controller-owned review, promotion, invalidation, consolidation and conflict behaviour."""
import json
import unittest
from dataclasses import replace
from stage5_support import (Provider, agent, complete_task, done, explore, findings,
                            reject_finding, review_payload, reviews, run_record, seed, setup_run,
                            state_of, target_of, TOOLS)
from swarm.contracts import ModelResponse
from swarm.domain import (Agent, AgentGroup, Assignment, Conflict, ConflictKind, ConflictStatus,
                          DomainError, Evidence, Finding, FindingStatus, ReviewDecision, ReviewKind,
                          ReviewRecord, Role, RoleName, SwarmState, Task, TaskStatus, transition,
                          validate_records)
from swarm.events import EventDraft, EventType
# The Stage-5/6 subject is the work engine: these tests drive admitted work, review
# and circulation to quiescence. Whether the run is then finished is the Stage-7 run
# workflow, exercised in the Stage-7 suite against ``WorkController`` above this layer.
from swarm.engine import WorkEngine
from swarm.persistence import ConflictError, SQLiteRepository, StorageError
from swarm.roles import default_roles


def tool_evidence(numbers, expected, reference='seeded-1'):
    actual = sum(numbers)
    return Evidence(kind='tool_result', tool_name='arithmetic', reference=reference,
                    arguments_json=json.dumps({'expected': expected, 'numbers': numbers}, sort_keys=True),
                    value=json.dumps({'actual': actual, 'matches': actual == expected}))


class ControllerReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def controller(self, provider, **kwargs):
        return WorkEngine(self.repo, 'r', {'fake': provider}, TOOLS, **kwargs)

    async def run_with(self, provider, **kwargs):
        controller = self.controller(provider, **kwargs)
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r')

    def two_branches(self, *, wrong=()):
        tasks = [explore('ta', [1, 2, 3], group_id='ga'), explore('tb', [10, 20], group_id='gb')]
        setup_run(self.repo, tasks,
                  [agent('a', 'ga'), agent('b', 'gb'), agent('critic'), agent('validator')],
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',)),
                          AgentGroup(id='gb', run_id='r', agent_ids=('b',), task_ids=('tb',))])
        return Provider(wrong=dict(wrong))

    # --- integration ------------------------------------------------------------

    async def test_stage_five_scenario_rejects_the_wrong_candidate_and_promotes_the_rest(self):
        provider = self.two_branches(wrong={'tb': 99})
        controller, s = await self.run_with(provider)
        claims = {f.claim: f.status for f in findings(s)}
        self.assertEqual(claims, {'sum([1, 2, 3]) = 6': FindingStatus.VALIDATED,
                                  'sum([10, 20]) = 99': FindingStatus.REJECTED})
        # Every promoted claim went through an independent critic and an independent validator.
        by_target = {}
        for review in reviews(s):
            by_target.setdefault(review.target_id, []).append(review)
        for target, recorded in by_target.items():
            agents = [s[r.assignment_id].agent_id for r in recorded]
            self.assertEqual([r.kind for r in recorded], [ReviewKind.CRITICISM, ReviewKind.VALIDATION])
            self.assertEqual(len(set(agents + [s[s[target].assignment_id].agent_id])), 3)
        state = state_of(s)
        self.assertEqual([s[i].claim for i in state.validated_findings], ['sum([1, 2, 3]) = 6'])
        self.assertEqual(len(state.rejected_findings), 1)
        self.assertEqual(controller.coverage()['c1'].clean, True)
        validate_records(s.values())
        types = [e.type for e in self.repo.inspect('r').events]
        for expected in ('FINDING_CREATED', 'TASK_CREATED', 'REVIEW_STARTED', 'REVIEW_COMPLETED',
                         'FINDING_CRITIQUED', 'FINDING_VALIDATED', 'KNOWLEDGE_PROMOTED',
                         'FINDING_REJECTED'):
            self.assertIn(expected, types)

    async def test_a_duplicate_claim_from_another_branch_consolidates_to_one_representative(self):
        tasks = [explore('ta', [2, 2], group_id='ga'), explore('tb', [2, 2], group_id='gb')]
        setup_run(self.repo, tasks,
                  [agent('a', 'ga'), agent('b', 'gb'), agent('critic'), agent('validator')],
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',)),
                          AgentGroup(id='gb', run_id='r', agent_ids=('b',), task_ids=('tb',))])
        controller, s = await self.run_with(Provider())
        validated = [f for f in findings(s) if f.status == FindingStatus.VALIDATED]
        self.assertEqual(len(validated), 2)
        report = controller.consolidate()
        self.assertEqual(len(report.groups), 1)
        self.assertEqual(len(report.groups[0].member_ids), 2)
        self.assertEqual(report.duplicate_ids, (validated[1].id,))
        # Both records survive; only the canonical one is offered as shared knowledge.
        self.assertEqual(state_of(self.repo.snapshot('r')).validated_findings, (validated[0].id,))
        self.assertIn('CONSOLIDATION_COMPLETED', [e.type for e in self.repo.inspect('r').events])

    # --- independence -----------------------------------------------------------

    async def test_a_lone_agent_produces_a_recorded_review_gap_not_a_self_review(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent('a')])
        provider = Provider()
        controller, s = await self.run_with(provider)
        finding = findings(s)[0]
        self.assertEqual(finding.status, FindingStatus.PROPOSED)
        gap = next(t for t in s.values() if isinstance(t, Task) and t.kind == 'criticism')
        self.assertEqual((gap.status, gap.outcome), (TaskStatus.FAILED, 'NO_INDEPENDENT_REVIEWER'))
        self.assertEqual({role for role, _ in provider.calls}, {'explorer'})
        # The gap is decided before dispatch: no provider request was spent on it.
        self.assertEqual(s['r'].provider_requests, 2)
        rejected = [json.loads(e.detail_json) for e in self.repo.inspect('r').events
                    if e.type == EventType.REVIEW_REJECTED]
        self.assertEqual(rejected[0]['reason'], 'NO_INDEPENDENT_REVIEWER')
        self.assertEqual(reviews(s), [])

    async def test_a_second_agent_criticises_but_cannot_also_validate(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent('a'), agent('b')])
        controller, s = await self.run_with(Provider())
        finding = findings(s)[0]
        self.assertEqual(finding.status, FindingStatus.CRITIQUED)
        critic = s[reviews(s)[0].assignment_id].agent_id
        self.assertNotEqual(critic, s[s[finding.assignment_id].id].agent_id)
        validation = next(t for t in s.values() if isinstance(t, Task) and t.kind == 'validation')
        self.assertEqual((validation.status, validation.outcome),
                         (TaskStatus.FAILED, 'NO_INDEPENDENT_REVIEWER'))
        self.assertEqual([r.kind for r in reviews(s)], [ReviewKind.CRITICISM])

    async def test_generator_critic_and_validator_are_three_distinct_identities(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        controller, s = await self.run_with(Provider())
        finding = findings(s)[0]
        identities = [s[finding.assignment_id].agent_id] + [s[r.assignment_id].agent_id for r in reviews(s)]
        self.assertEqual(len(set(identities)), 3)
        self.assertEqual(finding.status, FindingStatus.VALIDATED)

    # --- exact revision targeting -----------------------------------------------

    async def test_a_target_that_changes_while_its_critic_runs_makes_the_review_stale(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        fired = []
        def before(role, context):
            if role != 'critic' or fired:
                return
            fired.append(True)
            reject_finding(self.repo, 'r', context['target_id'])
        controller, s = await self.run_with(Provider(before=before))
        self.assertEqual(findings(s)[0].status, FindingStatus.REJECTED)
        self.assertEqual(reviews(s), [])
        rejections = [json.loads(e.detail_json).get('reason') for e in self.repo.inspect('r').events
                      if e.type == EventType.OUTPUT_REJECTED]
        self.assertIn('INPUT_FINDING_CHANGED', rejections)

    async def test_a_target_that_changes_while_its_validator_runs_makes_the_review_stale(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        fired = []
        def before(role, context):
            if role != 'validator' or fired:
                return
            fired.append(True)
            reject_finding(self.repo, 'r', context['target_id'])
        controller, s = await self.run_with(Provider(before=before))
        self.assertEqual(findings(s)[0].status, FindingStatus.REJECTED)
        self.assertEqual([r.kind for r in reviews(s)], [ReviewKind.CRITICISM])
        rejections = [json.loads(e.detail_json).get('reason') for e in self.repo.inspect('r').events
                      if e.type == EventType.OUTPUT_REJECTED]
        self.assertIn('INPUT_FINDING_CHANGED', rejections)

    # --- verification through the controller ------------------------------------

    async def test_a_fabricated_tool_reference_is_refused_before_any_record_is_written(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        provider = Provider(validator=lambda context, tool: done(review={
            'target_id': context['target_id'], 'target_revision': target_of(context)['revision'],
            'decision': 'PASS', 'summary': 'trust me', 'evidence_ids': ['invented-tool-result']}))
        controller, s = await self.run_with(provider)
        self.assertEqual(findings(s)[0].status, FindingStatus.CRITIQUED)
        self.assertEqual([r.kind for r in reviews(s)], [ReviewKind.CRITICISM])

    async def test_model_agreement_without_host_verification_does_not_promote(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        # Both reviewers agree enthusiastically; neither runs a check.
        provider = Provider(explorer=lambda context, tool: done(findings=[{'claim': 'the total is fine'}]),
                            validator=lambda context, tool: review_payload(context, 'PASS'))
        controller, s = await self.run_with(provider)
        finding = findings(s)[0]
        self.assertEqual(finding.status, FindingStatus.CRITIQUED)
        validation = next(r for r in reviews(s) if r.kind == ReviewKind.VALIDATION)
        self.assertEqual(validation.decision, ReviewDecision.INCONCLUSIVE)
        self.assertIn('UNSUPPORTED_CLAIM_FORM', validation.verification)
        self.assertFalse(any(e.verified for e in validation.evidence))

    async def test_a_blocking_critique_holds_a_verified_claim_back_until_it_is_addressed(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        provider = Provider(critic=lambda context, tool: review_payload(
            context, 'CHALLENGE', blocking_issues=['the operand list was never confirmed']),
            validator=lambda context, tool: review_payload(context, 'PASS'))
        controller, s = await self.run_with(provider)
        finding = findings(s)[0]
        self.assertEqual(finding.status, FindingStatus.CRITIQUED)
        validation = next(r for r in reviews(s) if r.kind == ReviewKind.VALIDATION)
        self.assertIn('UNRESOLVED_BLOCKING_CRITIQUE', validation.verification)

    async def test_a_validator_that_resolves_the_blocking_issue_promotes_the_claim(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        provider = Provider(critic=lambda context, tool: review_payload(
            context, 'CHALLENGE', blocking_issues=['the operand list was never confirmed']))
        controller, s = await self.run_with(provider)
        finding = findings(s)[0]
        self.assertEqual(finding.status, FindingStatus.VALIDATED)
        validation = next(r for r in reviews(s) if r.kind == ReviewKind.VALIDATION)
        self.assertEqual(validation.resolved_issues, (f'{reviews(s)[0].id}#0',))

    async def test_no_admitted_evidence_is_ever_marked_verified_by_a_model(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        controller, s = await self.run_with(Provider())
        candidate_evidence = [e for f in findings(s) for e in f.evidence]
        self.assertTrue(candidate_evidence)
        self.assertFalse(any(e.verified for e in candidate_evidence))
        # Only the host verifier writes verified evidence, and only onto a validation review.
        verified = [(r.kind, e) for r in reviews(s) for e in r.evidence if e.verified]
        self.assertTrue(verified)
        self.assertTrue(all(kind == ReviewKind.VALIDATION for kind, _ in verified))
        # The envelope cannot even express the flag.
        from swarm.output import OUTPUT_CONTRACT, parse_output
        self.assertNotIn('verified', OUTPUT_CONTRACT)
        with self.assertRaises(ValueError):
            parse_output(json.dumps({'status': 'SUCCEEDED', 'summary': 's', 'review': {
                'target_id': 'f', 'target_revision': 1, 'decision': 'PASS', 'summary': 's',
                'verified': True}}), s['role:VALIDATOR'], ())

    async def test_a_finding_may_not_cite_a_tool_result_the_host_never_recorded(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        provider = Provider(explorer=lambda context, tool: done(
            findings=[{'claim': 'sum([1, 2]) = 3', 'evidence_ids': ['never-executed']}]))
        controller, s = await self.run_with(provider)
        self.assertEqual(findings(s), [])
        self.assertEqual(s['ta'].status, TaskStatus.FAILED)

    async def test_an_inconclusive_critique_leaves_the_candidate_where_it_was(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        provider = Provider(critic=lambda context, tool: review_payload(context, 'INCONCLUSIVE'))
        controller, s = await self.run_with(provider)
        self.assertEqual(findings(s)[0].status, FindingStatus.PROPOSED)
        self.assertEqual([r.decision for r in reviews(s)], [ReviewDecision.INCONCLUSIVE])
        self.assertEqual(state_of(s).candidate_findings, (findings(s)[0].id,))


class PromotionAtomicityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def promoted(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        controller = WorkEngine(self.repo, 'r', {'fake': Provider()}, TOOLS)
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r')

    async def test_promotion_and_shared_state_land_in_one_transaction(self):
        controller, s = await self.promoted()
        finding = findings(s)[0]
        state = state_of(s)
        self.assertEqual(state.validated_findings, (finding.id,))
        self.assertEqual(state.candidate_findings, ())
        promoting = [e for e in self.repo.inspect('r').events if e.type == EventType.KNOWLEDGE_PROMOTED]
        sequence = promoting[0].sequence
        same = [e for e in self.repo.inspect('r').events
                if e.record_id == state.id and abs(e.sequence - sequence) <= 4]
        self.assertTrue(same, 'the projection is written alongside the promotion')

    async def test_a_run_may_hold_only_one_shared_state_projection(self):
        controller, s = await self.promoted()
        second = SwarmState(id='second-state', run_id='r')
        with self.assertRaises(DomainError):
            self.repo.commit('r', [second], [EventDraft(type=EventType.RECORD_CHANGED,
                                                        record_id=second.id, record_revision=1)])
        self.assertEqual(len([r for r in self.repo.snapshot('r').values()
                              if isinstance(r, SwarmState)]), 1)

    async def test_the_projection_keeps_its_identity_and_increments_its_revision(self):
        controller, s = await self.promoted()
        state = state_of(s)
        self.assertGreater(state.revision, 1)
        before = state.revision
        controller.consolidate()
        self.assertEqual(state_of(self.repo.snapshot('r')).id, state.id)
        self.assertGreaterEqual(state_of(self.repo.snapshot('r')).revision, before)

    async def test_a_promotion_that_omits_the_projection_is_refused_at_commit(self):
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c')])
        controller = WorkEngine(self.repo, 'r', {'fake': Provider(
            validator=lambda context, tool: review_payload(context, 'INCONCLUSIVE'))}, TOOLS)
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        finding, state = findings(s)[0], state_of(s)
        # A genuinely independent reviewer, so only the projection is inconsistent.
        validator = next(r for r in reviews(s) if r.kind == ReviewKind.VALIDATION)
        forged = ReviewRecord(id='forged', run_id='r', assignment_id=validator.assignment_id,
                              target_id=finding.id, target_revision=finding.revision,
                              kind=ReviewKind.VALIDATION, decision=ReviewDecision.PASS,
                              evidence=(replace(tool_evidence([1, 2], 3), verified=True),))
        promoted = transition(finding, FindingStatus.VALIDATED, review=forged)
        with self.assertRaises(DomainError) as caught:
            # SwarmState still classifies it as a candidate, so the pair is inconsistent.
            self.repo.commit('r', [forged, promoted],
                             [EventDraft(type=EventType.RECORD_CHANGED, record_id=forged.id, record_revision=1),
                              EventDraft(type=EventType.FINDING_VALIDATED, record_id=promoted.id,
                                         record_revision=promoted.revision)])
        self.assertIn('classification mismatch', str(caught.exception))
        self.assertEqual(self.repo.get('r', finding.id).status, FindingStatus.CRITIQUED)
        self.assertEqual(state_of(self.repo.snapshot('r')).revision, state.revision)

    async def test_a_failed_transaction_leaves_finding_and_projection_untouched(self):
        controller, s = await self.promoted()
        finding, state = findings(s)[0], state_of(s)
        stale_state = replace(state, validated_findings=(), revision=state.revision)
        with self.assertRaises(ConflictError):
            self.repo.commit('r', [stale_state], [EventDraft(type=EventType.RECORD_CHANGED,
                                                             record_id=state.id,
                                                             record_revision=state.revision)])
        after = self.repo.snapshot('r')
        self.assertEqual(state_of(after), state)
        self.assertEqual(after[finding.id].status, FindingStatus.VALIDATED)


class InvalidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def chain(self):
        """One validated root, one validated dependent that required it, one unrelated claim."""
        root = explore('root', [1, 2], group_id='g')
        unrelated = explore('side', [5, 5], group_id='g')
        setup_run(self.repo, [root, unrelated],
                  [agent('a', 'g'), agent('critic'), agent('validator')],
                  groups=[AgentGroup(id='g', run_id='r', agent_ids=('a',),
                                     task_ids=('root', 'side'))])
        controller = WorkEngine(self.repo, 'r', {'fake': Provider()}, TOOLS)
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        base = next(f for f in findings(s) if f.claim == 'sum([1, 2]) = 3')
        follow = explore('follow', [3, 4], group_id='g', required_finding_ids=(base.id,),
                         dependency_ids=('root',))
        seed(self.repo, 'r', follow,
             replace(s['g'], task_ids=s['g'].task_ids + ('follow',), revision=s['g'].revision + 1))
        controller = WorkEngine(self.repo, 'r', {'fake': Provider()}, TOOLS)
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r'), base

    async def test_invalidating_a_root_reaches_its_validated_dependent_and_spares_the_rest(self):
        controller, s, base = await self.chain()
        dependent = next(f for f in findings(s) if base.id in f.dependency_finding_ids)
        unrelated = next(f for f in findings(s) if f.claim == 'sum([5, 5]) = 10')
        self.assertEqual({dependent.status, unrelated.status}, {FindingStatus.VALIDATED})
        removed = controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        self.assertEqual(sorted(removed), sorted([base.id, dependent.id]))
        after = self.repo.snapshot('r')
        self.assertEqual(after[base.id].status, FindingStatus.INVALIDATED)
        self.assertEqual(after[dependent.id].status, FindingStatus.INVALIDATED)
        self.assertEqual(after[unrelated.id].status, FindingStatus.VALIDATED)
        state = state_of(after)
        self.assertEqual(state.validated_findings, (unrelated.id,))
        self.assertEqual(sorted(state.invalidated_findings), sorted([base.id, dependent.id]))
        validate_records(after.values())
        types = [e.type for e in self.repo.inspect('r').events]
        self.assertIn('FINDING_INVALIDATED', types)
        self.assertIn('KNOWLEDGE_REMOVED', types)

    async def test_invalidated_knowledge_can_no_longer_be_selected_as_validated_context(self):
        controller, s, base = await self.chain()
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        from swarm.context import ContextBuilder
        task = Task(id='next', run_id='r', objective='use knowledge', group_id='g',
                    acceptance_criterion_ids=('c1',))
        context = ContextBuilder().build(after, task, after['a'], after['role:EXPLORER'], (),
                                         assignment_id='n')
        self.assertNotIn(base.id, context.finding_ids)

    async def test_a_failing_invalidation_transaction_changes_nothing(self):
        controller, s, base = await self.chain()
        original = self.repo.commit
        def failing(run_id, records, events):
            raise StorageError('disk gone')
        self.repo.commit = failing
        with self.assertRaises(StorageError):
            controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        self.repo.commit = original
        after = self.repo.snapshot('r')
        self.assertEqual(after[base.id].status, FindingStatus.VALIDATED)
        self.assertEqual(state_of(after), state_of(s))

    async def test_revalidation_needs_a_fresh_pass_of_criticism_and_verification(self):
        from swarm.review import ReviewPolicy
        setup_run(self.repo, [explore('ta', [1, 2])], [agent(i) for i in ('a', 'b', 'c', 'd')])
        policy = ReviewPolicy(attempts_per_kind=2)
        controller = WorkEngine(self.repo, 'r', {'fake': Provider()}, TOOLS, review_policy=policy)
        await controller.run_until_idle()
        finding = findings(self.repo.snapshot('r'))[0]
        self.assertEqual(finding.status, FindingStatus.VALIDATED)
        controller.invalidate_finding(finding.id, 'FIXTURE_CORRECTION')
        self.assertEqual(self.repo.get('r', finding.id).status, FindingStatus.INVALIDATED)
        controller = WorkEngine(self.repo, 'r', {'fake': Provider()}, TOOLS, review_policy=policy)
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        self.assertEqual(s[finding.id].status, FindingStatus.VALIDATED)
        recorded = [r.kind for r in reviews(s)]
        self.assertEqual((recorded.count(ReviewKind.CRITICISM), recorded.count(ReviewKind.VALIDATION)),
                         (2, 2))
        # The second pass targeted the invalidated revision, not the original one.
        self.assertEqual(len({r.target_revision for r in reviews(s)}), 4)
        # Every reviewer of this finding is a distinct identity from its author.
        author = s[s[finding.id].assignment_id].agent_id
        self.assertNotIn(author, [s[r.assignment_id].agent_id for r in reviews(s)])
        self.assertEqual(state_of(s).validated_findings, (finding.id,))
        validate_records(s.values())

    async def test_an_assignment_pinned_to_invalidated_evidence_is_still_rejected(self):
        controller, s, base = await self.chain()
        controller.invalidate_finding(base.id, 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        assignment = next(a for a in after.values() if isinstance(a, Assignment)
                          and base.id in a.input_finding_ids)
        from swarm.admission import check_assignment_admissibility
        from swarm.output import ExecutionResult
        decision = check_assignment_admissibility(
            assignment, ExecutionResult('SUCCEEDED', 'late', assignment_id=assignment.id), after)
        self.assertFalse(decision.allowed)


class ConflictScenarioTests(unittest.IsolatedAsyncioTestCase):
    """Two individually reviewed claims that cannot both remain uncontested knowledge."""

    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def contested(self):
        task = Task(id='seeded', run_id='r', objective='fixture', acceptance_criterion_ids=('c1',))
        assignment = Assignment(id='seed-x', run_id='r', task_id='seeded', agent_id='a',
                                role_id='role:EXPLORER', provider_key='fake')
        left = Finding(id='left', run_id='r', task_id='seeded', assignment_id='seed-x',
                       claim='sum([2, 2]) = 4', criterion_ids=('c1',),
                       evidence=(tool_evidence([2, 2], 4),), tags=('contradiction',),
                       related_finding_ids=('right',))
        right = Finding(id='right', run_id='r', task_id='seeded', assignment_id='seed-x',
                        claim='sum([1, 3]) = 4', criterion_ids=('c1',),
                        evidence=(tool_evidence([1, 3], 4, 'seeded-2'),))
        setup_run(self.repo, [], [agent('a'), agent('critic'), agent('validator')],
                  extra=[task, assignment, right, left])
        complete_task(self.repo, 'r', 'seeded', 'seed-x')
        controller = WorkEngine(self.repo, 'r', {'fake': Provider()}, TOOLS)
        await controller.run_until_idle()
        return controller, self.repo.snapshot('r')

    async def test_a_declared_contradiction_opens_a_conflict_over_validated_claims(self):
        controller, s = await self.contested()
        self.assertEqual({s['left'].status, s['right'].status}, {FindingStatus.VALIDATED})
        conflicts = [c for c in s.values() if isinstance(c, Conflict)]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual((conflicts[0].kind, conflicts[0].finding_ids, conflicts[0].status),
                         (ConflictKind.DECLARED_CONTRADICTION, ('left', 'right'), ConflictStatus.OPEN))
        self.assertEqual(state_of(s).open_conflict_ids, (conflicts[0].id,))
        self.assertIn('CONFLICT_OPENED', [e.type for e in self.repo.inspect('r').events])

    async def test_an_open_conflict_denies_clean_coverage_and_reaches_context(self):
        controller, s = await self.contested()
        coverage = controller.coverage()['c1']
        self.assertEqual(coverage.supporting_ids, ('left', 'right'))
        self.assertFalse(coverage.clean)
        from swarm.context import ContextBuilder
        task = Task(id='next', run_id='r', objective='use knowledge', acceptance_criterion_ids=('c1',))
        payload = json.loads(ContextBuilder().build(s, task, s['a'], s['role:EXPLORER'], (),
                                                    assignment_id='n').json)
        shown = {f['id']: f for f in payload['findings']}
        self.assertEqual(sorted(shown), ['left', 'right'])
        self.assertTrue(all('conflicts' in entry for entry in shown.values()))

    async def test_a_conflict_survives_reload_and_resolves_when_a_side_stops_being_validated(self):
        controller, s = await self.contested()
        conflict = next(c for c in s.values() if isinstance(c, Conflict))
        reloaded = self.repo.get('r', conflict.id)
        self.assertEqual(reloaded, conflict)
        controller.invalidate_finding('left', 'FIXTURE_CORRECTION')
        after = self.repo.snapshot('r')
        self.assertEqual(after[conflict.id].status, ConflictStatus.RESOLVED)
        self.assertIn('PARTICIPANT_NOT_VALIDATED', after[conflict.id].resolution)
        self.assertEqual(state_of(after).open_conflict_ids, ())
        self.assertTrue(controller.coverage()['c1'].clean)
        self.assertIn('CONFLICT_RESOLVED', [e.type for e in self.repo.inspect('r').events])


class CrossScopeControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    async def test_review_authority_crosses_branches_while_worker_requests_do_not(self):
        tasks = [explore('ta', [1, 2, 3], group_id='ga'), explore('tb', [10, 20], group_id='gb')]
        setup_run(self.repo, tasks,
                  [agent('a', 'ga'), agent('b', 'gb'), agent('critic'), agent('validator')],
                  groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',)),
                          AgentGroup(id='gb', run_id='r', agent_ids=('b',), task_ids=('tb',))])
        seen = []
        provider = Provider(before=lambda role, context: seen.append((role, context)),
                            explorer=None)
        original = Provider._explore
        def explore_with_request(self, context, tool):
            response = original(self, context, tool)
            if tool is None:
                return response
            payload = json.loads(response.content)
            payload['task_requests'] = [{'objective': 'review the other branch instead'}]
            return ModelResponse(content=json.dumps(payload))
        provider._explore = explore_with_request.__get__(provider, Provider)
        controller = WorkEngine(self.repo, 'r', {'fake': provider}, TOOLS)
        await controller.run_until_idle()
        s = self.repo.snapshot('r')
        # Every review task the controller created is ungrouped and names one exact target.
        review_tasks = [t for t in s.values() if isinstance(t, Task) and t.target_finding_id]
        self.assertTrue(review_tasks)
        self.assertTrue(all(t.group_id is None for t in review_tasks))
        # An admitted worker request stays an inert proposal with no finding authority.
        from swarm.domain import TaskRequest
        requests = [r for r in s.values() if isinstance(r, TaskRequest)]
        self.assertTrue(requests)
        self.assertFalse(any(hasattr(r, 'target_finding_id') for r in requests))
        # Every Task is seeded work, a controller-created review, or Stage-6 reconsideration
        # the controller authored from a propagation. The requested objective is not among them.
        created = [t for t in s.values() if isinstance(t, Task)]
        authored = [t for t in created if t.source_propagation_id]
        self.assertEqual({t.id for t in created},
                         {t.id for t in tasks} | {t.id for t in review_tasks} | {t.id for t in authored})
        self.assertFalse(any(t.objective == 'review the other branch instead' for t in created))
        # A branch-A explorer never saw branch B's evidence.
        for role, context in seen:
            if role == 'explorer' and context['task']['id'] == 'ta':
                self.assertNotIn('10, 20', json.dumps(context))
