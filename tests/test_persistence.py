import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from swarm.domain import Run, Task, TaskStatus, transition, DomainError
from swarm.events import EventDraft, EventType
from swarm.persistence import SQLiteRepository, StorageError, ConflictError


def event(record):
    return EventDraft(type=EventType.RECORD_CHANGED, record_id=record.id,
                      record_revision=record.revision)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'runs.sqlite'
        self.repo = SQLiteRepository(self.path)
        self.run = Run(id='r', objective='work')
        self.repo.commit('r', [self.run], [event(self.run)])

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_reload_and_incomplete_inspection(self):
        self.repo.close()
        self.repo = SQLiteRepository(self.path)
        view = self.repo.inspect('r')
        self.assertEqual(view.records[0], self.run)
        self.assertEqual(view.status, 'INCOMPLETE')
        self.assertEqual(view.events[0].sequence, 1)

    def test_record_event_consistency_and_revisions(self):
        task = Task(id='t', run_id='r', objective='work')
        with self.assertRaises(DomainError):
            self.repo.commit('r', [task], [])
        self.repo.commit('r', [task], [event(task)])
        ready = transition(task, TaskStatus.READY)
        self.repo.commit('r', [ready], [event(ready)])
        with self.assertRaises(ConflictError):
            self.repo.commit('r', [ready], [event(ready)])
        self.assertEqual(self.repo.get('r', 't').revision, 2)
        self.assertEqual([e.sequence for e in self.repo.inspect('r').events], [1, 2, 3])

    def test_atomic_rollback_on_late_database_failure(self):
        task = Task(id='t', run_id='r', objective='work')
        # Duplicate event IDs fail after the record SQL write has occurred.
        duplicate = replace(event(task), id=self.repo.inspect('r').events[0].id)
        with self.assertRaises(StorageError):
            self.repo.commit('r', [task], [duplicate])
        self.assertIsNone(self.repo.get('r', 't'))
        self.repo.commit('r', [task], [event(task)])
        self.assertEqual([e.sequence for e in self.repo.inspect('r').events], [1, 2])

    def test_runs_have_independent_sequences(self):
        other = Run(id='other', objective='separate')
        self.repo.commit('other', [other], [event(other)])
        self.assertEqual(self.repo.inspect('other').events[0].sequence, 1)
        self.assertEqual(len(self.repo.inspect('r').records), 1)

    def test_closed_storage_raises_normalized_error(self):
        self.repo.close()
        with self.assertRaises(StorageError):
            self.repo.commit('r', [], [EventDraft(type=EventType.PROVIDER_REQUESTED)])

    def test_illegal_update_cannot_bypass_domain_service(self):
        task = Task(id='t', run_id='r', objective='work')
        self.repo.commit('r', [task], [event(task)])
        changed = replace(task, status=TaskStatus.COMPLETED, revision=2)
        with self.assertRaises(DomainError):
            self.repo.commit('r', [changed], [event(changed)])
        self.assertEqual(self.repo.get('r', 't'), task)

    def test_event_cannot_claim_unwritten_revision(self):
        with self.assertRaises(DomainError):
            self.repo.commit('r', [], [EventDraft(type=EventType.RECORD_CHANGED,
                                                 record_id='r', record_revision=999)])

    def test_cannot_insert_completed_task(self):
        task = Task(id='t', run_id='r', objective='work', status=TaskStatus.COMPLETED)
        with self.assertRaises(DomainError):
            self.repo.commit('r', [task], [event(task)])

    def test_existing_unknown_database_version_is_not_overwritten(self):
        import sqlite3
        other = Path(self.tmp.name) / 'future.sqlite'
        db = sqlite3.connect(other)
        db.execute('PRAGMA user_version=99')
        db.close()
        with self.assertRaises(StorageError):
            SQLiteRepository(other)

    def test_assignment_provenance_is_immutable(self):
        from swarm.domain import Agent, Role, RoleName, Assignment
        a, b = Agent(id='a', run_id='r'), Agent(id='b', run_id='r')
        role = Role(id='e', name=RoleName.EXPLORER)
        task = Task(id='t', run_id='r', objective='x')
        assignment = Assignment(id='x', run_id='r', task_id='t', agent_id='a', role_id='e')
        records = [a, b, role, task, assignment]
        self.repo.commit('r', records, [event(r) for r in records])
        changed = replace(assignment, agent_id='b', revision=2)
        with self.assertRaises(DomainError):
            self.repo.commit('r', [changed], [event(changed)])

    def test_mutation_event_contains_before_and_after(self):
        import json
        changed = replace(self.run, provider_requests=1, revision=2)
        self.repo.commit('r', [changed], [event(changed)])
        detail = json.loads(self.repo.inspect('r').events[-1].detail_json)
        self.assertEqual(detail['change']['before']['provider_requests'], 0)
        self.assertEqual(detail['change']['after']['provider_requests'], 1)

    def test_validated_review_history_and_claim_cannot_be_erased(self):
        from swarm.domain import Agent, Role, RoleName, Assignment, Finding, FindingStatus, ReviewDecision, ReviewRecord, Evidence
        a, b = Agent(id='a', run_id='r'), Agent(id='b', run_id='r')
        role = Role(id='e', name=RoleName.EXPLORER)
        task = Task(id='t', run_id='r', objective='x')
        gen = Assignment(id='x', run_id='r', task_id='t', agent_id='a', role_id='e')
        checker = replace(gen, id='y', agent_id='b')
        f = Finding(id='f', run_id='r', task_id='t', assignment_id='x', claim='sum is 3')
        records = [a, b, role, task, gen, checker, f]
        self.repo.commit('r', records, [event(r) for r in records])
        f = transition(f, FindingStatus.CRITIQUED)
        self.repo.commit('r', [f], [event(f)])
        review = ReviewRecord(id='v', run_id='r', assignment_id='y', target_id='f', target_revision=2,
            decision=ReviewDecision.PASS, evidence=(Evidence(kind='tool_result', reference='tool-1', verified=True),))
        f = transition(f, FindingStatus.VALIDATED, review=review)
        self.repo.commit('r', [review, f], [event(review), event(f)])
        for changed in [replace(f, review_ids=(), revision=4), replace(f, claim='sum is 4', revision=4)]:
            with self.subTest(changed=changed), self.assertRaises(DomainError):
                self.repo.commit('r', [changed], [event(changed)])
        self.assertEqual(self.repo.get('r', 'f').status, FindingStatus.VALIDATED)
        invalid = transition(f, FindingStatus.INVALIDATED)
        self.repo.commit('r', [invalid], [event(invalid)])
        self.assertEqual(self.repo.get('r', 'f').status, FindingStatus.INVALIDATED)
