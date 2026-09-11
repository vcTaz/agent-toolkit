import json
import unittest
from dataclasses import dataclass, replace
from swarm.domain import *
from swarm.context import ContextBuilder, ContextError
from swarm.messaging import route_message, unread_messages
from swarm.admission import check_assignment_admissibility, check_task_request
from swarm.policies import ready_decision, select_tasks
from swarm.output import ExecutionResult, TaskDraft
from swarm.scope import UNRESOLVED, owning_group


@dataclass(frozen=True, kw_only=True)
class FutureRecord(RunRecord):
    """Stands in for a record type a later stage adds without updating the scope rules."""


def fixture():
    run = Run(id='r', objective='work', permissions=())
    role = Role(id='e', name=RoleName.EXPLORER)
    a = Agent(id='a', run_id='r', group_id='g', role_id='e')
    b = Agent(id='b', run_id='r', group_id='g', role_id='e')
    outsider = Agent(id='out', run_id='r', role_id='e')
    group = AgentGroup(id='g', run_id='r', agent_ids=('a', 'b'), task_ids=('t',))
    task = Task(id='t', run_id='r', objective='work', group_id='g', role_id='e')
    return {r.id: r for r in (run, role, a, b, outsider, group, task)}


class MessagingTests(unittest.TestCase):
    def test_group_delivery_snapshot_and_unread_selection(self):
        s = fixture()
        m = Message(id='m', run_id='r', sender='agent:a', recipient='group:g', summary='insight')
        delivered, reason = route_message(m, s)
        self.assertIsNone(reason)
        self.assertEqual(delivered.delivered_to, ('a', 'b'))
        s['m'] = delivered
        s['g'] = replace(s['g'], agent_ids=('a', 'out'), revision=2)
        self.assertEqual([m.id for m in unread_messages(s, 'b')], ['m'])
        self.assertEqual(unread_messages(s, 'out'), ())

    def test_agent_orchestrator_and_rejected_targets(self):
        s = fixture()
        for recipient in ('agent:b', 'orchestrator'):
            delivered, reason = route_message(Message(id='m', run_id='r', sender='agent:a',
                                                     recipient=recipient, summary='x'), s)
            self.assertIsNone(reason)
            self.assertEqual(delivered.status, MessageStatus.DELIVERED)
        for recipient in ('broadcast', 'agent:missing', 'agent:out'):
            result, reason = route_message(Message(id='m', run_id='r', sender='agent:a',
                                                   recipient=recipient, summary='x'), s)
            self.assertIsNotNone(reason)
        s['g'] = replace(s['g'], status=GroupStatus.CLOSED)
        self.assertIsNotNone(route_message(Message(id='m', run_id='r', sender='system',
                                                  recipient='group:g', summary='x'), s)[1])

    def test_run_scoped_sender_with_a_dangling_group_is_rejected_not_crashed(self):
        s = fixture()
        s['wide'] = Role(id='wide', name=RoleName.COLLABORATOR, communication_scope='run')
        s['a'] = replace(s['a'], role_id='wide', group_id='ghost')
        result, reason = route_message(Message(id='m', run_id='r', sender='agent:a',
                                               recipient='agent:b', summary='x'), s)
        self.assertIsNone(result)
        self.assertEqual(reason, 'SENDER_NOT_MEMBER')

    def test_cross_run_and_unknown_references_rejected(self):
        s = fixture()
        for m in [Message(id='m', run_id='other', sender='system', recipient='agent:a', summary='x'),
                  Message(id='m', run_id='r', sender='system', recipient='agent:a', summary='x', reference_ids=('missing',))]:
            self.assertIsNotNone(route_message(m, s)[1])


class ContextTests(unittest.TestCase):
    def test_explicit_selection_excludes_private_and_unrelated_history(self):
        s = fixture()
        s['x'] = Assignment(id='x', run_id='r', task_id='t', agent_id='a', role_id='e')
        for i in range(12):
            s[f'f{i:02}'] = Finding(id=f'f{i:02}', run_id='r', task_id='t', assignment_id='x',
                                    claim=f'claim{i}', status=FindingStatus.VALIDATED, tags=('topic',))
        s['state'] = SwarmState(id='state', run_id='r', validated_findings=tuple(f'f{i:02}' for i in range(12)),
                                failed_approaches=('one', 'two', 'three', 'four'))
        s['t'] = replace(s['t'], tags=('topic',))
        unrelated, _ = route_message(Message(id='m', run_id='r', sender='system', recipient='agent:out',
                                             summary='PRIVATE_OTHER_AGENT_TRANSCRIPT'), s)
        s['m'] = unrelated
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertEqual(len(context.finding_ids), 8)
        self.assertNotIn('PRIVATE_OTHER_AGENT_TRANSCRIPT', context.json)
        self.assertEqual(context.finding_ids, tuple(f'f{i:02}' for i in range(8)))
        self.assertIn('f11', context.omitted_ids)
        self.assertLessEqual(context.size, 24000)
        self.assertEqual(context.hash, ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new').hash)

    def test_required_evidence_retained_and_overflow_explicit(self):
        s = fixture()
        s['f'] = Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim='exact target',
                         evidence=(Evidence(kind='assertion', value='required evidence'),))
        s['t'] = replace(s['t'], required_finding_ids=('f',), candidate_finding_ids=('f',))
        selected = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertIn('required evidence', selected.json)
        s['f'] = replace(s['f'], evidence=(Evidence(kind='assertion', value='z' * 25000),))
        with self.assertRaises(ContextError):
            ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')


class PolicyTests(unittest.TestCase):
    def test_dependencies_not_parenthood_control_readiness(self):
        s = fixture()
        parent = Task(id='p', run_id='r', objective='parent', role_id='e')
        s['p'] = parent
        child = replace(s['t'], parent_task_id='p')
        self.assertTrue(ready_decision(child, s).allowed)
        dependent = replace(child, dependency_ids=('p',))
        self.assertEqual(ready_decision(dependent, s).reason, 'DEPENDENCY_PENDING')
        s['p'] = replace(parent, status=TaskStatus.COMPLETED)
        self.assertTrue(ready_decision(dependent, s).allowed)
        s['p'] = replace(parent, status=TaskStatus.FAILED)
        self.assertEqual(ready_decision(dependent, s).reason, 'DEPENDENCY_FAILED')

    def test_selection_priority_then_stable_order(self):
        base = fixture()['t']
        tasks = [replace(base, id='b', priority=2), replace(base, id='a', priority=2), replace(base, id='c', priority=1)]
        self.assertEqual([t.id for t in select_tasks(tasks)], ['a', 'b', 'c'])

class AdmissionTests(unittest.TestCase):
    def pinned(self):
        s = fixture()
        s['t'] = replace(s['t'], status=TaskStatus.RUNNING, revision=3, assignment_id='x')
        s['a'] = replace(s['a'], status=AgentStatus.RUNNING, assignment_id='x')
        assignment = Assignment(id='x', run_id='r', task_id='t', task_revision=3, agent_id='a',
                                provider_key='fake', role_id='e', group_id='g', status=AssignmentStatus.RUNNING)
        s['x'] = assignment
        return s, assignment, ExecutionResult('SUCCEEDED', 'done', assignment_id='x')

    def test_invalidated_selected_finding_is_stale(self):
        s, a, output = self.pinned()
        s['f'] = Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim='known',
                         status=FindingStatus.VALIDATED)
        a = replace(a, input_finding_ids=('f',), input_finding_revisions=(1,))
        s['x'] = a
        self.assertTrue(check_assignment_admissibility(a, output, s).allowed)
        s['f'] = transition(s['f'], FindingStatus.INVALIDATED)
        self.assertEqual(check_assignment_admissibility(a, output, s).reason, 'INPUT_FINDING_CHANGED')

    def test_unrelated_revision_and_other_read_receipt_are_not_stale(self):
        s, a, output = self.pinned()
        m, _ = route_message(Message(id='m', run_id='r', sender='system', recipient='group:g', summary='x'), s)
        s['m'] = m
        a = replace(a, message_ids=('m',), message_revisions=(m.delivery_revision,))
        s['x'] = a
        s['m'] = replace(m, read_by=('b',), revision=m.revision + 1)
        s['r'] = replace(s['r'], provider_requests=10, revision=5)
        self.assertTrue(check_assignment_admissibility(a, output, s).allowed)

    def test_context_pin_does_not_allow_forged_assignment_snapshot(self):
        s, a, output = self.pinned()
        forged = replace(a, task_revision=4)
        s['t'] = replace(s['t'], revision=4)
        decision = check_assignment_admissibility(forged, output, s)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, 'ASSIGNMENT_PROVENANCE_MISMATCH')
        # The stored pin, not the caller's copy, decides admissibility.
        self.assertEqual(check_assignment_admissibility(s['x'], output, s).reason, 'TASK_REVISION_CHANGED')

    def test_task_requests_validate_cycles_count_criteria_and_duplicates(self):
        s, a, _ = self.pinned()
        self.assertTrue(check_task_request(TaskDraft('follow up'), a, s).allowed)
        self.assertEqual(check_task_request(TaskDraft('x', dependency_ids=('missing',)), a, s).reason, 'INVALID_REQUEST_DEPENDENCY')
        self.assertEqual(check_task_request(TaskDraft('x', dependency_ids=('new',)), a, s, candidate_id='new').reason, 'REQUEST_CYCLE')
        self.assertEqual(check_task_request(TaskDraft('x', criterion_ids=('missing',)), a, s).reason, 'INVALID_REQUEST_CRITERIA')
        s['r'] = replace(s['r'], task_limit=1)
        self.assertEqual(check_task_request(TaskDraft('x'), a, s).reason, 'TASK_LIMIT')

    def test_nested_input_dependency_revision_is_pinned(self):
        s = fixture()
        s['root'] = Finding(id='root', run_id='r', task_id='t', assignment_id='old', claim='root')
        s['f'] = Finding(id='f', run_id='r', task_id='t', assignment_id='old', claim='summary',
                         dependency_finding_ids=('root',))
        s['t'] = replace(s['t'], candidate_finding_ids=('f',))
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertIn('root', context.finding_ids)

    def test_message_referenced_finding_is_pinned(self):
        s = fixture()
        s['f'] = Finding(id='f', run_id='r', task_id='t', assignment_id='old', claim='candidate')
        m, _ = route_message(Message(id='m', run_id='r', sender='system', recipient='agent:a',
                                     summary='consider candidate', reference_ids=('f',)), s)
        s['m'] = m
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertIn('f', context.finding_ids)

    def test_message_reference_cannot_disclose_other_group(self):
        s = fixture()
        s['foreign-task'] = Task(id='foreign-task', run_id='r', objective='secret', group_id='other')
        s['secret'] = Finding(id='secret', run_id='r', task_id='foreign-task', assignment_id='old', claim='secret')
        _, reason = route_message(Message(id='m', run_id='r', sender='agent:a', recipient='group:g',
                                          summary='leak', reference_ids=('secret',)), s)
        self.assertIsNotNone(reason)


class DisclosureTests(unittest.TestCase):
    def candidate(self, identity, **kwargs):
        return Finding(id=identity, run_id='r', task_id='t', assignment_id='old', claim=identity, **kwargs)

    def test_candidate_closure_is_dropped_atomically_at_the_count_limit(self):
        s = fixture()
        for identity in ('a1', 'a2', 'a3'):
            s[identity] = self.candidate(identity)
        s['z0'] = self.candidate('z0')
        s['z'] = self.candidate('z', dependency_finding_ids=('z0',))
        s['t'] = replace(s['t'], candidate_finding_ids=('a1', 'a2', 'a3', 'z'))
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertEqual(context.finding_ids, ('a1', 'a2', 'a3'))
        self.assertNotIn('z0', context.json)
        self.assertEqual({'z', 'z0'}, set(context.omitted_ids))
        self.assertIn('z:GROUP_DROPPED', context.reasons)

    def test_candidate_with_unavailable_dependency_is_not_disclosed(self):
        s = fixture()
        s['bad'] = self.candidate('bad', status=FindingStatus.INVALIDATED)
        s['c'] = self.candidate('c', dependency_finding_ids=('bad',))
        s['t'] = replace(s['t'], candidate_finding_ids=('c',))
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertEqual(context.finding_ids, ())
        self.assertIn('c:NOT_DISCLOSABLE', context.reasons)

    def test_candidate_outside_the_branch_is_not_disclosed(self):
        s = fixture()
        s['foreign-task'] = Task(id='foreign-task', run_id='r', objective='other', group_id='other')
        s['secret'] = Finding(id='secret', run_id='r', task_id='foreign-task', assignment_id='old', claim='secret')
        s['t'] = replace(s['t'], candidate_finding_ids=('secret',))
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='new')
        self.assertEqual(context.finding_ids, ())
        self.assertNotIn('secret', context.json)

    def test_message_reference_to_an_undelivered_message_is_rejected(self):
        s = fixture()
        direct, _ = route_message(Message(id='direct', run_id='r', sender='system',
                                          recipient='agent:a', summary='private'), s)
        s['direct'] = direct
        _, reason = route_message(Message(id='m', run_id='r', sender='agent:a', recipient='group:g',
                                          summary='forward', reference_ids=('direct',)), s)
        self.assertEqual(reason, 'REFERENCE_NOT_DELIVERED')

    def test_pinned_nested_dependency_makes_dependent_output_stale(self):
        s = fixture()
        s['root'] = Finding(id='root', run_id='r', task_id='t', assignment_id='old', claim='root')
        s['f'] = Finding(id='f', run_id='r', task_id='t', assignment_id='old', claim='summary',
                         dependency_finding_ids=('root',))
        s['t'] = replace(s['t'], candidate_finding_ids=('f',))
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='x')
        s['t'] = replace(s['t'], status=TaskStatus.RUNNING, revision=3, assignment_id='x')
        s['a'] = replace(s['a'], status=AgentStatus.RUNNING, assignment_id='x')
        assignment = Assignment(id='x', run_id='r', task_id='t', task_revision=3, agent_id='a',
                                provider_key='fake', role_id='e', group_id='g',
                                status=AssignmentStatus.RUNNING,
                                input_finding_ids=context.finding_ids,
                                input_finding_revisions=context.finding_revisions)
        s['x'] = assignment
        output = ExecutionResult('SUCCEEDED', 'done', assignment_id='x')
        self.assertTrue(check_assignment_admissibility(assignment, output, s).allowed)
        s['root'] = transition(s['root'], FindingStatus.REJECTED)
        self.assertEqual(check_assignment_admissibility(assignment, output, s).reason, 'INPUT_FINDING_CHANGED')


class ScopeTests(unittest.TestCase):
    """Disclosure boundaries must fail closed for records the scope rules do not classify."""

    def foreign(self):
        s = fixture()
        s['t2'] = Task(id='t2', run_id='r', objective='other', group_id='other')
        s['secret'] = Finding(id='secret', run_id='r', task_id='t2', assignment_id='old',
                              claim='GROUP_B_SECRET', status=FindingStatus.VALIDATED,
                              evidence=(Evidence(kind='assertion', value='B_EVIDENCE'),))
        return s

    def reference(self, s, identity):
        return route_message(Message(id='m', run_id='r', sender='agent:a', recipient='group:g',
                                     summary='look', reference_ids=(identity,)), s)[1]

    def test_review_and_request_references_follow_their_target_group(self):
        s = self.foreign()
        s['rev'] = ReviewRecord(id='rev', run_id='r', assignment_id='old', target_id='secret',
                                target_revision=1, decision=ReviewDecision.PASS)
        s['req'] = TaskRequest(id='req', run_id='r', assignment_id='old', parent_task_id='t2', objective='o')
        self.assertEqual(self.reference(s, 'rev'), 'REFERENCE_OUT_OF_SCOPE')
        self.assertEqual(self.reference(s, 'req'), 'REFERENCE_OUT_OF_SCOPE')
        s['own'] = ReviewRecord(id='own', run_id='r', assignment_id='old', target_id='mine',
                                target_revision=1, decision=ReviewDecision.PASS)
        s['mine'] = Finding(id='mine', run_id='r', task_id='t', assignment_id='old', claim='local')
        self.assertIsNone(self.reference(s, 'own'))

    def test_unknown_record_types_are_undisclosable_by_default(self):
        self.assertIs(owning_group(FutureRecord(id='x', run_id='r'), {}), UNRESOLVED)
        s = fixture()
        s['x'] = FutureRecord(id='x', run_id='r')
        self.assertEqual(self.reference(s, 'x'), 'REFERENCE_OUT_OF_SCOPE')

    def test_unclassified_reference_types_fail_closed(self):
        s = self.foreign()
        s['orphan'] = ReviewRecord(id='orphan', run_id='r', assignment_id='old', target_id='gone',
                                   target_revision=1, decision=ReviewDecision.PASS)
        self.assertEqual(self.reference(s, 'orphan'), 'REFERENCE_OUT_OF_SCOPE')
        # A run-scoped projection is legitimately shared and stays allowed.
        s['state'] = SwarmState(id='state', run_id='r')
        self.assertIsNone(self.reference(s, 'state'))

    def test_host_assigned_evidence_crosses_groups_but_automatic_selection_does_not(self):
        s = self.foreign()
        s['t'] = replace(s['t'], required_finding_ids=('secret',))
        selected = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='n')
        self.assertEqual(selected.finding_ids, ('secret',))
        self.assertIn('B_EVIDENCE', selected.json)
        # The same finding offered only as an optional candidate is not disclosable.
        s['t'] = replace(s['t'], required_finding_ids=(), candidate_finding_ids=('secret',))
        optional = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='n')
        self.assertEqual(optional.finding_ids, ())
        self.assertNotIn('B_EVIDENCE', optional.json)

    def test_deep_dependency_chain_is_bounded_not_a_crash(self):
        s = fixture()
        depth = 2000
        for i in range(depth):
            s[f'c{i:05}'] = Finding(id=f'c{i:05}', run_id='r', task_id='t', assignment_id='old',
                                    claim=str(i), dependency_finding_ids=(f'c{i - 1:05}',) if i else ())
        s['t'] = replace(s['t'], candidate_finding_ids=(f'c{depth - 1:05}',))
        context = ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='n')
        self.assertEqual(context.finding_ids, ())
        self.assertIn(f'c{depth - 1:05}:GROUP_DROPPED', context.reasons)

    def test_ambiguous_shared_state_fails_instead_of_serving_the_oldest(self):
        s = fixture()
        s['state-1'] = SwarmState(id='state-1', run_id='r', failed_approaches=('STALE',))
        s['state-2'] = SwarmState(id='state-2', run_id='r', failed_approaches=('CURRENT',))
        with self.assertRaises(ContextError) as caught:
            ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='n')
        self.assertEqual(str(caught.exception), 'AMBIGUOUS_SWARM_STATE')

    def test_required_finding_failure_reason_is_order_independent(self):
        s = fixture()
        s['zzz'] = Finding(id='zzz', run_id='r', task_id='t', assignment_id='old', claim='gone',
                           status=FindingStatus.REJECTED)
        s['t'] = replace(s['t'], required_finding_ids=('aaa-missing', 'zzz'))
        with self.assertRaises(ContextError) as caught:
            ContextBuilder().build(s, s['t'], s['a'], s['e'], (), assignment_id='n')
        # The lexicographically first offender is reported regardless of set iteration order.
        self.assertEqual(str(caught.exception), 'REQUIRED_FINDING_MISSING')
