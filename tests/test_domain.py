import unittest
from dataclasses import FrozenInstanceError, replace

from swarm.domain import (
    Agent, AgentStatus, Role, RoleName, Task, TaskStatus, Finding, FindingStatus,
    Run, RunState, Message, SwarmState, AgentGroup, Assignment, ReviewDecision, ReviewRecord,
    Evidence, DomainError, transition, assign_role, validate_records, invalidate,
    revise_finding,
)
from swarm.serialization import dumps, loads


class DomainTests(unittest.TestCase):
    def test_round_trip_preserves_types_and_nested_values(self):
        records = [Run(id='r', objective='calculate'), Agent(id='a', run_id='r'),
                   Role(id='explorer', name=RoleName.EXPLORER),
                   Task(id='t', run_id='r', objective='sum'),
                   Finding(id='f', run_id='r', task_id='t', assignment_id='x',
                           claim='sum is 3', evidence=(Evidence(kind='assertion', value='3'),)),
                   Message(id='m', run_id='r', sender='system', recipient='orchestrator'),
                   SwarmState(id='state', run_id='r'), AgentGroup(id='g', run_id='r'),
                   Assignment(id='x', run_id='r', task_id='t', agent_id='a', role_id='explorer'),
                   ReviewRecord(id='review', run_id='r', assignment_id='x', target_id='f',
                                target_revision=1, decision=ReviewDecision.INCONCLUSIVE)]
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertEqual(loads(dumps(record)), record)
        with self.assertRaises(DomainError):
            loads(dumps(records[0]).replace('"schema_version":4', '"schema_version":99'))

    def test_illegal_transitions_and_revision(self):
        task = Task(id='t', run_id='r', objective='sum')
        with self.assertRaises(DomainError):
            transition(task, TaskStatus.COMPLETED)
        ready = transition(task, TaskStatus.READY)
        self.assertEqual(ready.revision, 2)
        self.assertEqual(task.status, TaskStatus.PENDING)
        with self.assertRaises(DomainError):
            transition(ready, FindingStatus.REJECTED)

    def test_role_changes_only_while_idle(self):
        role = Role(id='critic', name=RoleName.CRITIC)
        agent = Agent(id='a', run_id='r')
        self.assertEqual(assign_role(agent, role).role_id, 'critic')
        with self.assertRaises(DomainError):
            assign_role(replace(agent, status=AgentStatus.RUNNING), role)

    def test_task_cycles_and_cross_run_references(self):
        run = Run(id='r', objective='work')
        t1 = Task(id='a', run_id='r', objective='a', dependency_ids=('b',))
        t2 = Task(id='b', run_id='r', objective='b', dependency_ids=('a',))
        with self.assertRaises(DomainError):
            validate_records([run, t1, t2])
        with self.assertRaises(DomainError):
            validate_records([run, t1, replace(t2, run_id='other', dependency_ids=())])
        with self.assertRaises(DomainError):
            validate_records([run, t1])

    def fixture(self):
        return [Run(id='r', objective='work'), Agent(id='a', run_id='r'),
                Role(id='e', name=RoleName.EXPLORER), Task(id='t', run_id='r', objective='work'),
                Assignment(id='x', run_id='r', task_id='t', agent_id='a', role_id='e')]

    def test_finding_cycles(self):
        a = Finding(id='f1', run_id='r', task_id='t', assignment_id='x', claim='a',
                    dependency_finding_ids=('f2',))
        b = replace(a, id='f2', dependency_finding_ids=('f1',))
        with self.assertRaises(DomainError):
            validate_records(self.fixture() + [a, b])

    def test_invalidation_cascades_and_requires_recriticism(self):
        a = Finding(id='a', run_id='r', task_id='t', assignment_id='x', claim='a',
                    status=FindingStatus.VALIDATED)
        b = replace(a, id='b', dependency_finding_ids=('a',))
        result = invalidate((a, b), 'a')
        self.assertEqual([f.status for f in result], [FindingStatus.INVALIDATED] * 2)
        with self.assertRaises(DomainError):
            transition(result[0], FindingStatus.VALIDATED)
        self.assertEqual(transition(result[0], FindingStatus.CRITIQUED).status, FindingStatus.CRITIQUED)

    def test_claim_is_immutable_and_revision_creates_new_identity(self):
        original = Finding(id='a', run_id='r', task_id='t', assignment_id='x', claim='wrong')
        with self.assertRaises(FrozenInstanceError):
            original.claim = 'right'
        revised = revise_finding(original, new_id='b', claim='right', evidence=())
        self.assertEqual(revised.supersedes_id, 'a')
        self.assertEqual(revised.status, FindingStatus.PROPOSED)
        self.assertEqual(original.claim, 'wrong')
        with self.assertRaises(DomainError):
            revise_finding(original, new_id='a', claim='right', evidence=())

    def test_review_alone_cannot_validate(self):
        finding = Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim='3',
                          status=FindingStatus.CRITIQUED)
        with self.assertRaises(DomainError):
            transition(finding, FindingStatus.VALIDATED)

    def test_run_completion_requires_workflow_authority(self):
        with self.assertRaises(DomainError):
            transition(Run(id='r', objective='work'), RunState.COMPLETED)

    def test_constructors_reject_mutable_and_invalid_values(self):
        for make in [lambda: Task(id='t', run_id='r', objective='x', dependency_ids=[]),
                     lambda: Agent(id='a', run_id='r', status='IDLE'),
                     lambda: Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim=''),
                     lambda: Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim='x', confidence=2),
                     lambda: Run(id='r', objective='x', provider_requests=-1)]:
            with self.subTest(make=make), self.assertRaises(DomainError):
                make()

    def test_tool_backed_independent_review_allows_transition(self):
        f = Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim='3',
                    status=FindingStatus.CRITIQUED)
        review = ReviewRecord(id='v', run_id='r', assignment_id='y', target_id='f',
                              target_revision=1, decision=ReviewDecision.PASS,
                              evidence=(Evidence(kind='tool_result', reference='tool-1', verified=True),))
        for bad in [replace(review, target_revision=2), replace(review, decision=ReviewDecision.FAIL),
                    replace(review, blocking_issues=('unaddressed',)),
                    replace(review, assignment_id='x'),
                    replace(review, evidence=(Evidence(kind='assertion', value='trust me'),)),
                    replace(review, evidence=(Evidence(kind='tool_result', reference='t'),))]:
            with self.subTest(review=bad), self.assertRaises(DomainError):
                transition(f, FindingStatus.VALIDATED, review=bad)
        validated = transition(f, FindingStatus.VALIDATED, review=review)
        self.assertEqual(validated.status, FindingStatus.VALIDATED)
        self.assertEqual(validated.review_ids, ('v',))
        self.assertEqual(transition(validated, FindingStatus.SUPERSEDED).status, FindingStatus.SUPERSEDED)

    def test_task_assignment_and_message_references_checked(self):
        fixture = self.fixture()
        for record in [replace(fixture[3], assignment_id='missing'),
                       Message(id='m', run_id='r', sender='agent:missing', recipient='orchestrator')]:
            source = [r for r in fixture if r.id != record.id] + [record]
            with self.subTest(record=record), self.assertRaises(DomainError):
                validate_records(source)

    def test_review_cannot_target_other_run(self):
        records = self.fixture() + [Run(id='other', objective='other'),
            ReviewRecord(id='v', run_id='r', assignment_id='x', target_id='other',
                         target_revision=1, decision=ReviewDecision.PASS)]
        with self.assertRaises(DomainError):
            validate_records(records)

    def test_deep_dependency_chains_return_a_decision_rather_than_overflowing(self):
        records = self.fixture()
        chain = [Finding(id=f'c{i:05}', run_id='r', task_id='t', assignment_id='x',
                         claim=str(i), dependency_finding_ids=(f'c{i - 1:05}',) if i else ())
                 for i in range(3000)]
        validate_records(records + chain)
        cyclic = replace(chain[0], dependency_finding_ids=('c02999',))
        with self.assertRaises(DomainError) as caught:
            validate_records(records + [cyclic] + chain[1:])
        self.assertEqual(str(caught.exception), 'dependency cycle')

    def test_one_active_assignment_per_agent_and_task(self):
        from swarm.domain import AssignmentStatus
        records = self.fixture()
        x = replace(records[-1], status=AssignmentStatus.RUNNING)
        y = replace(x, id='y')
        with self.assertRaises(DomainError):
            validate_records(records[:-1] + [x, y])
