"""Review scheduling, independence, exact-revision targeting and review admission."""
import json
import unittest
from dataclasses import replace
from swarm.admission import check_assignment_admissibility, check_task_request
from swarm.context import ContextBuilder, ContextError
from swarm.contracts import ToolResult
from swarm.domain import (Agent, AgentGroup, Assignment, AssignmentStatus, Conflict, ConflictKind,
                          Criterion, Evidence, Finding, FindingStatus, ReviewDecision, ReviewKind,
                          ReviewRecord, Role, RoleName, Run, SwarmState, Task, TaskStatus)
from swarm.output import ExecutionResult, FindingDraft, ReviewDraft, TaskDraft, parse_output
from swarm.policies import compatible_review_agents, excluded_review_agents, role_for
from swarm.review import ReviewPolicy, admit_review, due_kind, plan_reviews, review_task
from swarm.roles import default_roles
from swarm.verification import VerificationRegistry

CRITERIA = (Criterion(id='c1', description='sums', verifier_kind='arithmetic'),)


def tool_evidence(numbers, expected, actual=None, reference='tool-1'):
    actual = sum(numbers) if actual is None else actual
    return Evidence(kind='tool_result', tool_name='arithmetic', reference=reference,
                    arguments_json=json.dumps({'expected': expected, 'numbers': numbers}, sort_keys=True),
                    value=json.dumps({'actual': actual, 'matches': actual == expected}))


def tool_result(numbers, expected, actual=None, identity='own-1', assignment='rev'):
    actual = sum(numbers) if actual is None else actual
    return ToolResult(success=True, id=identity, assignment_id=assignment, tool_name='arithmetic',
                      arguments_json=json.dumps({'expected': expected, 'numbers': numbers}, sort_keys=True),
                      value_json=json.dumps({'actual': actual, 'matches': actual == expected}))


def fixture(**overrides):
    """One generated candidate plus a pool of ungrouped reviewers."""
    roles = {r.id: r for r in default_roles(allowed_tools=('arithmetic',))}
    s = {'r': Run(id='r', objective='x', acceptance_criteria=CRITERIA, permissions=('arithmetic',))}
    s.update(roles)
    for identity in ('author', 'critic', 'validator', 'spare'):
        s[identity] = Agent(id=identity, run_id='r', permissions=('arithmetic',))
    s['t'] = Task(id='t', run_id='r', objective='explore', acceptance_criterion_ids=('c1',),
                  role_id='role:EXPLORER', status=TaskStatus.COMPLETED)
    s['gen'] = Assignment(id='gen', run_id='r', task_id='t', agent_id='author',
                          role_id='role:EXPLORER', provider_key='fake')
    s['f'] = Finding(id='f', run_id='r', task_id='t', assignment_id='gen', criterion_ids=('c1',),
                     claim='sum([1, 2, 3]) = 6', evidence=(tool_evidence([1, 2, 3], 6),))
    s['state'] = SwarmState(id='state', run_id='r', candidate_findings=('f',))
    s.update(overrides)
    return s


def plan_for(s, finding_id):
    return next(p for p in plan_reviews(s, 'r') if p.finding_id == finding_id)


def review_assignment(s, plan_kind='criticism', agent='critic', target='f', revision=None):
    task = review_task(plan_for(s, target), lambda kind: f'{kind}-1', 'r', s)
    task = replace(task, kind=plan_kind, status=TaskStatus.RUNNING, assignment_id='rev',
                   role_id='role:CRITIC' if plan_kind == 'criticism' else 'role:VALIDATOR')
    revision = s[target].revision if revision is None else revision
    assignment = Assignment(id='rev', run_id='r', task_id=task.id, agent_id=agent,
                            role_id=task.role_id, status=AssignmentStatus.RUNNING,
                            provider_key='fake', task_revision=task.revision,
                            input_finding_ids=(target,), input_finding_revisions=(revision,))
    s[task.id], s['rev'] = task, assignment
    s[agent] = replace(s[agent], status=Agent(id='x', run_id='r').status.RUNNING,
                       assignment_id='rev', role_id=task.role_id)
    return task, assignment


def envelope(target, revision, decision, *, results=(), **extra):
    return ExecutionResult('SUCCEEDED', 'ok', review=ReviewDraft(target, revision, decision, 'summary',
                                                                 **extra),
                           assignment_id='rev', tool_results=tuple(results))


class PlanningTests(unittest.TestCase):
    def test_criticism_is_due_first_then_validation_then_nothing(self):
        s = fixture()
        self.assertEqual([(p.finding_id, p.task_kind) for p in plan_reviews(s, 'r')], [('f', 'criticism')])
        s['f'] = replace(s['f'], status=FindingStatus.CRITIQUED, revision=2)
        self.assertEqual([p.task_kind for p in plan_reviews(s, 'r')], ['validation'])
        s['f'] = replace(s['f'], status=FindingStatus.VALIDATED, revision=3)
        self.assertEqual(plan_reviews(s, 'r'), ())

    def test_attempts_are_bounded_so_a_gap_is_recorded_not_requeued(self):
        s = fixture()
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        s[task.id] = replace(task, status=TaskStatus.FAILED, outcome='NO_INDEPENDENT_REVIEWER')
        self.assertEqual(plan_reviews(s, 'r'), ())

    def test_unregistered_review_role_is_not_scheduled(self):
        s = fixture()
        del s['role:CRITIC']
        self.assertEqual(plan_reviews(s, 'r'), ())

    def test_validation_waits_while_a_dependency_is_unvalidated_or_gone(self):
        s = fixture()
        s['dep'] = Finding(id='dep', run_id='r', task_id='t', assignment_id='gen', claim='dep')
        s['f'] = replace(s['f'], status=FindingStatus.CRITIQUED, revision=2,
                         dependency_finding_ids=('dep',))
        planned = lambda: [p.finding_id for p in plan_reviews(s, 'r')]
        self.assertEqual(planned(), ['dep'])
        s['dep'] = replace(s['dep'], status=FindingStatus.VALIDATED, revision=2)
        self.assertEqual([p.task_kind for p in plan_reviews(s, 'r')], ['validation'])
        s['dep'] = replace(s['dep'], status=FindingStatus.INVALIDATED, revision=3)
        self.assertEqual(planned(), ['dep'])

    def test_review_task_pins_the_target_and_its_transitive_evidence(self):
        s = fixture()
        s['deep'] = Finding(id='deep', run_id='r', task_id='t', assignment_id='gen', claim='deep')
        s['dep'] = Finding(id='dep', run_id='r', task_id='t', assignment_id='gen', claim='dep',
                           dependency_finding_ids=('deep',))
        s['f'] = replace(s['f'], dependency_finding_ids=('dep',), revision=2)
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        self.assertEqual(task.target_finding_id, 'f')
        self.assertEqual(task.required_finding_ids, ('f', 'dep', 'deep'))
        self.assertEqual(task.candidate_finding_ids, ('dep', 'deep'))
        self.assertEqual(task.kind, 'criticism')
        self.assertIs(role_for(task, s), s['role:CRITIC'])


class IndependenceTests(unittest.TestCase):
    def test_the_generating_agent_may_never_critic_or_validate_its_own_finding(self):
        s = fixture()
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        self.assertEqual(excluded_review_agents(task, s), frozenset({'author'}))
        selected = compatible_review_agents(task, s['role:CRITIC'], s, ('arithmetic',), ('fake',))
        self.assertNotIn('author', [a.id for a in selected])
        self.assertEqual([a.id for a in selected], ['critic', 'spare', 'validator'])

    def test_the_critic_may_not_also_validate_the_same_finding(self):
        s = fixture()
        s['f'] = replace(s['f'], status=FindingStatus.CRITIQUED, revision=2, review_ids=('cr',))
        s['crit'] = Assignment(id='crit', run_id='r', task_id='t', agent_id='critic', role_id='role:CRITIC')
        s['cr'] = ReviewRecord(id='cr', run_id='r', assignment_id='crit', target_id='f',
                               target_revision=1, kind=ReviewKind.CRITICISM, decision=ReviewDecision.PASS)
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        self.assertEqual(excluded_review_agents(task, s), frozenset({'author', 'critic'}))
        self.assertEqual([a.id for a in compatible_review_agents(task, s['role:VALIDATOR'], s,
                                                                 ('arithmetic',), ('fake',))],
                         ['spare', 'validator'])

    def test_no_independent_agent_yields_an_empty_selection_rather_than_self_review(self):
        s = fixture()
        for identity in ('critic', 'validator', 'spare'):
            del s[identity]
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        self.assertEqual(compatible_review_agents(task, s['role:CRITIC'], s, ('arithmetic',), ('fake',)), ())

    def test_domain_refuses_a_committed_self_review_or_critic_validator_overlap(self):
        s = fixture()
        s['crit'] = Assignment(id='crit', run_id='r', task_id='t', agent_id='critic', role_id='role:CRITIC')
        base = dict(run_id='r', target_id='f', target_revision=1)
        from swarm.domain import DomainError, validate_records
        records = list(s.values()) + [
            ReviewRecord(id='self', assignment_id='gen', kind=ReviewKind.CRITICISM,
                         decision=ReviewDecision.PASS, **base)]
        with self.assertRaises(DomainError):
            validate_records(records)
        records = list(s.values()) + [
            ReviewRecord(id='cr', assignment_id='crit', kind=ReviewKind.CRITICISM,
                         decision=ReviewDecision.PASS, **base),
            ReviewRecord(id='va', assignment_id='crit', kind=ReviewKind.VALIDATION,
                         decision=ReviewDecision.PASS, **base)]
        with self.assertRaises(DomainError):
            validate_records(records)


class DomainInvariantTests(unittest.TestCase):
    """The commit-time backstops behind the review workflow, bound on their own."""

    def promoted(self, *, blocking=(), resolved=()):
        s = fixture()
        s['crit'] = Assignment(id='crit', run_id='r', task_id='t', agent_id='critic',
                               role_id='role:CRITIC', provider_key='fake')
        s['val'] = Assignment(id='val', run_id='r', task_id='t', agent_id='validator',
                              role_id='role:VALIDATOR', provider_key='fake')
        s['cr'] = ReviewRecord(id='cr', run_id='r', assignment_id='crit', target_id='f',
                               target_revision=1, kind=ReviewKind.CRITICISM,
                               decision=ReviewDecision.CHALLENGE if blocking else ReviewDecision.PASS,
                               blocking_issues=tuple(blocking))
        s['va'] = ReviewRecord(id='va', run_id='r', assignment_id='val', target_id='f',
                               target_revision=2, kind=ReviewKind.VALIDATION,
                               decision=ReviewDecision.PASS, resolved_issues=tuple(resolved),
                               evidence=(replace(tool_evidence([1, 2, 3], 6), verified=True),))
        s['f'] = replace(s['f'], status=FindingStatus.VALIDATED, revision=3, review_ids=('cr', 'va'))
        s['state'] = SwarmState(id='state', run_id='r', validated_findings=('f',))
        return s

    def test_a_snapshot_with_an_unresolved_blocking_critique_cannot_be_committed(self):
        from swarm.domain import DomainError, validate_records
        validate_records(self.promoted().values())
        contested = self.promoted(blocking=('operands unchecked',))
        with self.assertRaises(DomainError) as caught:
            validate_records(contested.values())
        self.assertIn('unresolved blocking critique', str(caught.exception))
        validate_records(self.promoted(blocking=('operands unchecked',), resolved=('cr#0',)).values())

    def test_shared_state_classification_must_agree_with_finding_status(self):
        from swarm.domain import DomainError, validate_records
        s = self.promoted()
        s['state'] = replace(s['state'], validated_findings=(), candidate_findings=('f',))
        with self.assertRaises(DomainError) as caught:
            validate_records(s.values())
        self.assertIn('classification mismatch', str(caught.exception))


class AdmissibilityTests(unittest.TestCase):
    def check(self, s, assignment, result):
        return check_assignment_admissibility(assignment, result, s)

    def test_a_review_is_admissible_only_in_a_review_role_on_its_own_target(self):
        s = fixture()
        task, assignment = review_assignment(s)
        self.assertTrue(self.check(s, assignment, envelope('f', 1, 'PASS')).allowed)
        self.assertEqual(self.check(s, assignment, envelope('other', 1, 'PASS')).reason,
                         'REVIEW_TARGET_MISMATCH')
        self.assertEqual(self.check(s, assignment, envelope('f', 2, 'PASS')).reason,
                         'REVIEW_TARGET_MISMATCH')
        missing = ExecutionResult('SUCCEEDED', 'ok', assignment_id='rev')
        self.assertEqual(self.check(s, assignment, missing).reason, 'REVIEW_MISSING')

    def test_a_reviewer_may_not_smuggle_findings_or_task_requests(self):
        s = fixture()
        task, assignment = review_assignment(s)
        result = replace(envelope('f', 1, 'PASS'), findings=(FindingDraft('extra'),))
        self.assertEqual(self.check(s, assignment, result).reason, 'REVIEW_SCOPE_VIOLATION')

    def test_an_explorer_cannot_return_an_authoritative_review(self):
        s = fixture()
        s['t'] = replace(s['t'], status=TaskStatus.RUNNING, assignment_id='gen', revision=2)
        s['author'] = replace(s['author'], status=s['author'].status.RUNNING, assignment_id='gen',
                              role_id='role:EXPLORER')
        assignment = replace(s['gen'], status=AssignmentStatus.RUNNING, task_revision=2, revision=2)
        s['gen'] = assignment
        result = ExecutionResult('SUCCEEDED', 'ok', review=ReviewDraft('f', 1, 'PASS', 's'),
                                 assignment_id='gen')
        self.assertEqual(self.check(s, assignment, result).reason, 'REVIEW_PROPOSAL_FORBIDDEN')
        # The role's output allowlist already refuses to parse the field at all.
        with self.assertRaises(ValueError):
            parse_output(json.dumps({'status': 'SUCCEEDED', 'summary': 's',
                                     'review': {'target_id': 'f', 'target_revision': 1,
                                                'decision': 'PASS', 'summary': 's'}}),
                         s['role:EXPLORER'], ())

    def test_a_review_role_may_not_run_an_ordinary_task_and_vice_versa(self):
        s = fixture()
        task, assignment = review_assignment(s, agent='critic')
        s[task.id] = replace(s[task.id], kind='validation')
        self.assertEqual(self.check(s, assignment, envelope('f', 1, 'PASS')).reason, 'REVIEW_ROLE_MISMATCH')

    def test_a_target_revision_that_moved_during_execution_is_stale(self):
        s = fixture()
        task, assignment = review_assignment(s)
        s['f'] = replace(s['f'], status=FindingStatus.CRITIQUED, revision=2)
        self.assertEqual(self.check(s, assignment, envelope('f', 1, 'PASS')).reason,
                         'INPUT_FINDING_CHANGED')

    def test_an_ineligible_target_state_is_refused(self):
        s = fixture()
        task, assignment = review_assignment(s)
        # A pin that still matches, on a finding that is no longer awaiting criticism.
        s['f'] = replace(s['f'], status=FindingStatus.VALIDATED)
        self.assertEqual(self.check(s, assignment, envelope('f', 1, 'PASS')).reason,
                         'REVIEW_TARGET_INELIGIBLE')

    def test_a_review_whose_target_was_never_pinned_is_refused(self):
        s = fixture()
        task, assignment = review_assignment(s)
        # Nothing pinned the target, so no revision was fixed at preparation time.
        s['rev'] = replace(assignment, input_finding_ids=(), input_finding_revisions=())
        self.assertEqual(self.check(s, s['rev'], envelope('f', 1, 'PASS')).reason,
                         'REVIEW_TARGET_REVISION_CHANGED')

    def test_a_review_task_may_not_propose_a_result(self):
        from swarm.output import ResultDraft
        s = fixture()
        task, assignment = review_assignment(s)
        result = replace(envelope('f', 1, 'PASS'), result=ResultDraft('answer'))
        self.assertEqual(self.check(s, assignment, result).reason, 'RESULT_PROPOSAL_FORBIDDEN')


class AdmitReviewTests(unittest.TestCase):
    def admit(self, s, result):
        return admit_review(s['rev'], result, s, lambda kind: f'{kind}-1', VerificationRegistry())

    def critiqued(self, blocking=()):
        s = fixture()
        s['crit'] = Assignment(id='crit', run_id='r', task_id='t', agent_id='critic', role_id='role:CRITIC')
        s['cr'] = ReviewRecord(id='cr', run_id='r', assignment_id='crit', target_id='f',
                               target_revision=1, kind=ReviewKind.CRITICISM,
                               decision=ReviewDecision.CHALLENGE if blocking else ReviewDecision.PASS,
                               blocking_issues=tuple(blocking))
        s['f'] = replace(s['f'], status=FindingStatus.CRITIQUED, revision=2, review_ids=('cr',))
        review_assignment(s, 'validation', agent='validator')
        return s

    def test_criticism_moves_a_candidate_to_critiqued_and_records_its_issues(self):
        s = fixture()
        review_assignment(s)
        records, events, review = self.admit(s, envelope('f', 1, 'CHALLENGE',
                                                         blocking_issues=('operand list unchecked',),
                                                         nonblocking_issues=('wording',)))
        self.assertEqual(review.kind, ReviewKind.CRITICISM)
        self.assertEqual(review.decision, ReviewDecision.CHALLENGE)
        self.assertEqual(review.blocking_issues, ('operand list unchecked',))
        finding = next(r for r in records if isinstance(r, Finding))
        self.assertEqual((finding.status, finding.revision, finding.review_ids),
                         (FindingStatus.CRITIQUED, 2, ('review-1',)))

    def test_an_inconclusive_critique_records_history_without_promoting_anything(self):
        s = fixture()
        review_assignment(s)
        records, events, review = self.admit(s, envelope('f', 1, 'INCONCLUSIVE'))
        finding = next(r for r in records if isinstance(r, Finding))
        self.assertEqual(finding.status, FindingStatus.PROPOSED)
        self.assertEqual(finding.revision, 2)  # the pin still moves, so late output is stale
        self.assertEqual([e.type for e in events][-1], 'REVIEW_REJECTED')

    def test_a_verified_validation_promotes_and_carries_host_evidence(self):
        s = self.critiqued()
        records, events, review = self.admit(
            s, envelope('f', 2, 'PASS', results=(tool_result([1, 2, 3], 6),), evidence_ids=('own-1',)))
        self.assertEqual(review.decision, ReviewDecision.PASS)
        self.assertTrue(any(e.verified and e.reference for e in review.evidence))
        self.assertIn('TOOL_RESULT_ENTAILS_CLAIM', review.verification)
        finding = next(r for r in records if isinstance(r, Finding))
        self.assertEqual(finding.status, FindingStatus.VALIDATED)
        self.assertEqual([e.type for e in events],
                         ['REVIEW_COMPLETED', 'FINDING_VALIDATED', 'KNOWLEDGE_PROMOTED'])

    def test_a_confident_model_pass_without_entailing_evidence_never_promotes(self):
        s = self.critiqued()
        s['f'] = replace(s['f'], evidence=(Evidence(kind='assertion', value='I am certain'),))
        records, events, review = self.admit(s, envelope('f', 2, 'PASS'))
        self.assertEqual(review.decision, ReviewDecision.INCONCLUSIVE)
        self.assertEqual(next(r for r in records if isinstance(r, Finding)).status,
                         FindingStatus.CRITIQUED)
        self.assertFalse(any(e.verified for e in review.evidence))

    def test_a_wrong_claim_is_rejected_even_when_its_tool_call_succeeded(self):
        s = self.critiqued()
        s['f'] = replace(s['f'], claim='sum([1, 2, 3]) = 99',
                         evidence=(tool_evidence([1, 2, 3], 99),))
        records, events, review = self.admit(
            s, envelope('f', 2, 'PASS', results=(tool_result([1, 2, 3], 99),), evidence_ids=('own-1',)))
        self.assertEqual(review.decision, ReviewDecision.FAIL)
        self.assertEqual(next(r for r in records if isinstance(r, Finding)).status,
                         FindingStatus.REJECTED)

    def test_an_unresolved_blocking_critique_blocks_promotion(self):
        s = self.critiqued(blocking=('the operand list was never checked',))
        args = dict(results=(tool_result([1, 2, 3], 6),), evidence_ids=('own-1',))
        records, _, review = self.admit(s, envelope('f', 2, 'PASS', **args))
        self.assertEqual(review.decision, ReviewDecision.INCONCLUSIVE)
        self.assertIn('UNRESOLVED_BLOCKING_CRITIQUE', review.verification)
        self.assertEqual(next(r for r in records if isinstance(r, Finding)).status,
                         FindingStatus.CRITIQUED)
        # Naming the exact issue the critic raised, with host verification, promotes it.
        records, _, review = self.admit(s, envelope('f', 2, 'PASS', resolved_issues=('cr#0',), **args))
        self.assertEqual((review.decision, review.resolved_issues), (ReviewDecision.PASS, ('cr#0',)))
        self.assertEqual(next(r for r in records if isinstance(r, Finding)).status,
                         FindingStatus.VALIDATED)

    def test_an_invented_issue_key_cannot_stand_in_for_a_real_one(self):
        s = self.critiqued(blocking=('the operand list was never checked',))
        _, _, review = self.admit(s, envelope('f', 2, 'PASS', resolved_issues=('made-up#7',),
                                              results=(tool_result([1, 2, 3], 6),),
                                              evidence_ids=('own-1',)))
        self.assertEqual(review.decision, ReviewDecision.INCONCLUSIVE)
        self.assertEqual(review.resolved_issues, ())

    def test_a_validation_pass_may_not_rest_on_an_unvalidated_dependency(self):
        s = self.critiqued()
        s['dep'] = Finding(id='dep', run_id='r', task_id='t', assignment_id='gen', claim='dep')
        s['f'] = replace(s['f'], dependency_finding_ids=('dep',), revision=3)
        s['rev'] = replace(s['rev'], input_finding_revisions=(3,))
        _, _, review = self.admit(s, envelope('f', 3, 'PASS', results=(tool_result([1, 2, 3], 6),),
                                              evidence_ids=('own-1',)))
        self.assertEqual(review.decision, ReviewDecision.INCONCLUSIVE)
        self.assertIn('DEPENDENCY_NOT_VALIDATED', review.verification)

    def test_a_stale_review_cannot_target_a_newer_revision(self):
        s = self.critiqued()
        s['f'] = replace(s['f'], revision=3)
        with self.assertRaises(ValueError) as caught:
            self.admit(s, envelope('f', 2, 'PASS'))
        self.assertEqual(str(caught.exception), 'REVIEW_TARGET_REVISION_MISMATCH')

    def test_a_decision_outside_the_kind_enum_is_refused(self):
        s = fixture()
        review_assignment(s)
        with self.assertRaises(ValueError) as caught:
            self.admit(s, envelope('f', 1, 'FAIL'))
        self.assertEqual(str(caught.exception), 'REVIEW_DECISION_NOT_ADMISSIBLE')

    def test_rejecting_a_claim_invalidates_the_validated_findings_that_rested_on_it(self):
        s = self.critiqued()
        s['f'] = replace(s['f'], claim='sum([1, 2, 3]) = 99', evidence=(tool_evidence([1, 2, 3], 99),))
        s['down'] = Finding(id='down', run_id='r', task_id='t', assignment_id='gen', claim='downstream',
                            status=FindingStatus.VALIDATED, dependency_finding_ids=('f',))
        records, events, _ = self.admit(
            s, envelope('f', 2, 'PASS', results=(tool_result([1, 2, 3], 99),), evidence_ids=('own-1',)))
        statuses = {r.id: r.status for r in records if isinstance(r, Finding)}
        self.assertEqual(statuses, {'f': FindingStatus.REJECTED, 'down': FindingStatus.INVALIDATED})
        self.assertIn('KNOWLEDGE_REMOVED', [e.type for e in events])


class ContextTests(unittest.TestCase):
    def target_context(self, s, task):
        return json.loads(ContextBuilder().build(s, task, s['critic'], s['role:CRITIC'], (),
                                                 assignment_id='n').json)

    def test_a_review_context_carries_the_exact_revision_and_keyed_blocking_issues(self):
        s = fixture()
        s['crit'] = Assignment(id='crit', run_id='r', task_id='t', agent_id='critic', role_id='role:CRITIC')
        s['cr'] = ReviewRecord(id='cr', run_id='r', assignment_id='crit', target_id='f',
                               target_revision=1, kind=ReviewKind.CRITICISM,
                               decision=ReviewDecision.CHALLENGE, blocking_issues=('unchecked operands',),
                               summary='challenged')
        s['f'] = replace(s['f'], status=FindingStatus.CRITIQUED, revision=2, review_ids=('cr',))
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        payload = self.target_context(s, task)
        self.assertEqual((payload['target_id'], payload['target_revision']), ('f', 2))
        self.assertEqual(payload['reviews'][0]['blocking_issues'],
                         [{'key': 'cr#0', 'issue': 'unchecked operands'}])
        self.assertEqual(payload['findings'][0]['evidence'][0]['tool_name'], 'arithmetic')

    def test_only_the_review_target_may_be_invalidated_never_its_supporting_evidence(self):
        s = fixture()
        s['dep'] = Finding(id='dep', run_id='r', task_id='t', assignment_id='gen', claim='support')
        s['f'] = replace(s['f'], dependency_finding_ids=('dep',), revision=2)
        task = review_task(plan_for(s, 'f'), lambda k: 'rt', 'r', s)
        # Re-criticism of an invalidated target is legitimate.
        s['f'] = replace(s['f'], status=FindingStatus.INVALIDATED, revision=3)
        payload = self.target_context(s, task)
        self.assertEqual({entry['id'] for entry in payload['findings']}, {'f', 'dep'})
        # Supporting evidence that is no longer available is not.
        s['dep'] = replace(s['dep'], status=FindingStatus.INVALIDATED, revision=2)
        with self.assertRaises(ContextError) as caught:
            self.target_context(s, task)
        self.assertEqual(str(caught.exception), 'REQUIRED_FINDING_UNAVAILABLE')

    def test_a_contested_finding_is_never_presented_as_uncontested(self):
        s = fixture()
        s['f'] = replace(s['f'], status=FindingStatus.VALIDATED, revision=2)
        s['g'] = Finding(id='g', run_id='r', task_id='t', assignment_id='gen', claim='sum([1, 2, 3]) = 7',
                         status=FindingStatus.VALIDATED, criterion_ids=('c1',))
        s['k'] = Conflict(id='k', run_id='r', finding_ids=('f', 'g'), finding_revisions=(2, 1),
                          kind=ConflictKind.CONTRADICTORY_VALUE, signature='sig', reason='4 != 7')
        s['state'] = SwarmState(id='state', run_id='r', validated_findings=('f', 'g'),
                                open_conflict_ids=('k',))
        s['t2'] = Task(id='t2', run_id='r', objective='use knowledge', acceptance_criterion_ids=('c1',),
                       role_id='role:CRITIC')
        payload = self.target_context(s, s['t2'])
        selected = {f['id']: f for f in payload['findings']}
        self.assertEqual(sorted(selected), ['f', 'g'])
        self.assertEqual(selected['f']['conflicts'][0]['with'], ['g'])
        self.assertEqual(selected['g']['conflicts'][0]['id'], 'k')

    def test_the_conflicted_pair_is_admitted_together_or_not_at_all(self):
        s = fixture()
        s['f'] = replace(s['f'], status=FindingStatus.VALIDATED, revision=2)
        s['g'] = Finding(id='g', run_id='r', task_id='t', assignment_id='gen',
                         claim='sum([1, 2, 3]) = 7', status=FindingStatus.VALIDATED,
                         criterion_ids=('c1',))
        s['k'] = Conflict(id='k', run_id='r', finding_ids=('f', 'g'), finding_revisions=(2, 1),
                          kind=ConflictKind.CONTRADICTORY_VALUE, signature='sig')
        s['state'] = SwarmState(id='state', run_id='r', validated_findings=('f', 'g'),
                                open_conflict_ids=('k',))
        s['t2'] = Task(id='t2', run_id='r', objective='use knowledge', acceptance_criterion_ids=('c1',),
                       role_id='role:CRITIC')
        # Room for exactly one validated finding: rather than show one side alone, drop both.
        context = ContextBuilder(max_validated=1).build(s, s['t2'], s['critic'], s['role:CRITIC'], (),
                                                        assignment_id='n')
        self.assertEqual(context.finding_ids, ())
        self.assertIn('f:GROUP_DROPPED', context.reasons)
        self.assertIn('g:GROUP_DROPPED', context.reasons)


class CrossScopeTests(unittest.TestCase):
    """Host-assigned review targets cross branch scope; nothing model-reachable does."""

    def branched(self):
        s = fixture()
        s['gb'] = AgentGroup(id='gb', run_id='r', agent_ids=('author',), task_ids=('t',))
        s['t'] = replace(s['t'], group_id='gb', revision=2)
        s['author'] = replace(s['author'], group_id='gb', revision=2)
        s['gen'] = replace(s['gen'], group_id='gb', revision=2)
        s['secret'] = Finding(id='secret', run_id='r', task_id='t', assignment_id='gen',
                              claim='BRANCH_B_ONLY', evidence=(Evidence(kind='assertion',
                                                                        value='B_EVIDENCE'),))
        return s

    def test_a_controller_review_task_may_read_its_target_across_the_branch(self):
        s = self.branched()
        task = review_task(plan_for(s, 'secret'), lambda k: 'rt', 'r', s)
        self.assertIsNone(task.group_id)
        context = ContextBuilder().build(s, task, s['critic'], s['role:CRITIC'], (), assignment_id='n')
        self.assertEqual(context.finding_ids, ('secret',))
        self.assertIn('B_EVIDENCE', context.json)

    def test_an_ordinary_task_cannot_reach_the_same_evidence(self):
        s = self.branched()
        outsider = Task(id='t3', run_id='r', objective='peek', role_id='role:EXPLORER',
                        candidate_finding_ids=('secret',))
        context = ContextBuilder().build(s, outsider, s['critic'], s['role:EXPLORER'], (),
                                         assignment_id='n')
        self.assertEqual(context.finding_ids, ())
        self.assertNotIn('B_EVIDENCE', context.json)

    def test_a_worker_task_request_cannot_manufacture_a_review_target(self):
        s = self.branched()
        s['t'] = replace(s['t'], status=TaskStatus.RUNNING, assignment_id='gen', revision=3)
        # The draft type simply has no finding fields, and admission keeps it a proposal.
        self.assertFalse({'target_finding_id', 'required_finding_ids', 'candidate_finding_ids'}
                         & set(vars(TaskDraft('objective'))))
        draft = TaskDraft('review the other branch', criterion_ids=())
        self.assertTrue(check_task_request(draft, s['gen'], s).allowed)
        with self.assertRaises(ValueError):
            parse_output(json.dumps({'status': 'SUCCEEDED', 'summary': 's', 'task_requests': [
                {'objective': 'o', 'target_finding_id': 'secret'}]}), s['role:EXPLORER'], ())
