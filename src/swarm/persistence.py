"""Canonical records plus atomic audit events; no replay or resume engine."""
import json
import sqlite3
from dataclasses import dataclass, fields, replace
from .domain import (Record, Run, RunRecord, Role, Finding, Agent, AgentStatus, Conflict,
                     ConflictStatus, Cycle, Propagation, Result, ResultStatus, ReviewRecord,
                     TerminalReport, DomainError, validate_records, transition)
from .events import Event, EventDraft, EventType
from .serialization import dumps, loads, encode


class StorageError(RuntimeError):
    """Persistence failed; callers must stop authoritative progress."""


class ConflictError(StorageError):
    """An optimistic revision no longer matches stored state."""


@dataclass(frozen=True)
class Inspection:
    records: tuple[Record, ...]
    events: tuple[Event, ...]
    status: str


class SQLiteRepository:
    def __init__(self, path):
        try:
            self._db = sqlite3.connect(path, isolation_level=None)
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 4):
                self._db.close()
                raise StorageError('unsupported database schema version')
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.executescript('''
                CREATE TABLE IF NOT EXISTS records (
                    run_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
                    revision INTEGER NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(run_id, id));
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    id TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence));
                PRAGMA user_version=4;
            ''')
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def close(self):
        self._db.close()

    def _records(self, run_id):
        return tuple(loads(row[0]) for row in self._db.execute(
            'SELECT data FROM records WHERE run_id=? ORDER BY id', (run_id,)))

    def snapshot(self, run_id):
        try:
            return {record.id: record for record in self._records(run_id)}
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def get(self, run_id, identity):
        try:
            row = self._db.execute('SELECT data FROM records WHERE run_id=? AND id=?',
                                   (run_id, identity)).fetchone()
            return loads(row[0]) if row else None
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def commit(self, run_id: str, records, events):
        """Compare revisions, validate a snapshot, then commit records and events together."""
        records, events = tuple(records), tuple(events)
        begun = False
        try:
            self._db.execute('BEGIN IMMEDIATE')
            begun = True
            old = {r.id: r for r in self._records(run_id)}
            merged = dict(old)
            if len({r.id for r in records}) != len(records):
                raise DomainError('duplicate writes in transaction')
            for record in records:
                if isinstance(record, Run) and record.id != run_id:
                    raise DomainError('wrong run identity')
                if isinstance(record, RunRecord) and record.run_id != run_id:
                    raise DomainError('cross-run write')
                previous = old.get(record.id)
                if record.revision != (previous.revision + 1 if previous else 1):
                    raise ConflictError('stale or skipped record revision')
                merged[record.id] = record
            if not isinstance(merged.get(run_id), Run):
                raise DomainError('run record must exist')
            validate_records(merged.values())
            for record in records:
                previous = old.get(record.id)
                if previous:
                    self._validate_update(previous, record, merged)
                else:
                    self._validate_initial(record)
                if not any(e.record_id == record.id and e.record_revision == record.revision for e in events):
                    raise DomainError('each mutation requires a matching event')
            for event in events:
                if event.schema_version != 1 or not isinstance(event.type, EventType):
                    raise DomainError('invalid event version/type')
                if not isinstance(json.loads(event.detail_json), dict):
                    raise DomainError('event detail must be an object')
                if (event.record_id is None) != (event.record_revision is None):
                    raise DomainError('partial event revision reference')
                if event.record_id is not None:
                    written = next((r for r in records if r.id == event.record_id), None)
                    if written is None or written.revision != event.record_revision:
                        raise DomainError('event describes an unwritten revision')
            for record in records:
                self._db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)',
                                 (run_id, record.id, type(record).__name__, record.revision, dumps(record)))
            seq = self._db.execute('SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?',
                                   (run_id,)).fetchone()[0]
            for offset, draft in enumerate(events, 1):
                if draft.record_id is not None:
                    detail = json.loads(draft.detail_json)
                    detail['change'] = {'before': encode(old.get(draft.record_id)),
                                        'after': encode(merged[draft.record_id])}
                    draft = replace(draft, detail_json=json.dumps(detail, allow_nan=False))
                event = Event(**{f.name: getattr(draft, f.name) for f in fields(EventDraft)},
                              run_id=run_id, sequence=seq + offset)
                self._db.execute('INSERT INTO events VALUES (?,?,?,?)',
                                 (run_id, event.sequence, event.id, json.dumps(encode(event))))
            self._db.execute('COMMIT')
        except BaseException as exc:
            if begun:
                self._db.execute('ROLLBACK')
            if isinstance(exc, sqlite3.Error):
                raise StorageError(str(exc)) from exc
            raise

    @staticmethod
    def _validate_initial(record):
        from .domain import (Task, TaskStatus, Assignment, AssignmentStatus, AgentGroup,
                             GroupStatus, Message, MessageStatus, FindingStatus, RunState)
        defaults = {Task: TaskStatus.PENDING, Agent: AgentStatus.IDLE,
                    Assignment: AssignmentStatus.CREATED, AgentGroup: GroupStatus.ACTIVE,
                    Message: MessageStatus.QUEUED, Finding: FindingStatus.PROPOSED,
                    Conflict: ConflictStatus.OPEN, Result: ResultStatus.CANDIDATE}
        if type(record) in defaults and record.status != defaults[type(record)]:
            raise DomainError('new records must start in initial lifecycle state')
        if isinstance(record, Run) and record.state != RunState.RECEIVED:
            raise DomainError('new runs must start RECEIVED')

    @staticmethod
    def _validate_update(old, new, snapshot):
        if type(old) is not type(new):
            raise DomainError('record type cannot change')
        if isinstance(old, (Role, ReviewRecord)):
            raise DomainError('role versions and reviews are immutable; use a new identity')
        from .domain import Assignment, TaskRequest, Message, MessageStatus
        if isinstance(old, TaskRequest):
            raise DomainError('task requests are immutable proposals')
        if isinstance(old, TerminalReport):
            raise DomainError('a terminal report is written once')
        if isinstance(old, Result):
            # A reviewed result is history the moment it is reviewed: a revision creates a
            # new version rather than editing the one the reviewer actually judged.
            mutable = {'revision', 'status', 'review_id', 'decision', 'revision_kind'}
            if any(getattr(old, f.name) != getattr(new, f.name) for f in fields(old) if f.name not in mutable):
                raise DomainError('result versions are immutable; a revision is a new version')
            for name in ('review_id', 'decision', 'revision_kind'):
                if getattr(old, name) is not None and getattr(old, name) != getattr(new, name):
                    raise DomainError('a recorded result verdict is write-once')
        if isinstance(old, Message):
            mutable = {'revision', 'status', 'delivered_to', 'delivery_revision', 'read_by'}
            if any(getattr(old, f.name) != getattr(new, f.name) for f in fields(old) if f.name not in mutable):
                raise DomainError('message content is immutable')
            if old.status != MessageStatus.QUEUED and (old.delivered_to != new.delivered_to or old.delivery_revision != new.delivery_revision):
                raise DomainError('delivery snapshot is immutable')
            if not set(old.read_by) <= set(new.read_by) <= set(new.delivered_to):
                raise DomainError('invalid read receipts')
        if isinstance(old, Assignment):
            mutable = {'revision', 'status', 'started_at', 'ended_at'}
            if any(getattr(old, f.name) != getattr(new, f.name)
                   for f in fields(old) if f.name not in mutable):
                raise DomainError('assignment provenance is immutable')
        if isinstance(old, Finding):
            if new.review_ids[:len(old.review_ids)] != old.review_ids:
                raise DomainError('review history is append-only')
            mutable = {'revision', 'status', 'review_ids'}
            if any(getattr(old, f.name) != getattr(new, f.name)
                   for f in fields(old) if f.name not in mutable):
                raise DomainError('substantive finding content is immutable')
        if isinstance(old, Conflict):
            mutable = {'revision', 'status', 'resolution', 'resolved_at'}
            if any(getattr(old, f.name) != getattr(new, f.name) for f in fields(old) if f.name not in mutable):
                raise DomainError('conflict participants and reason are immutable')
        if isinstance(old, Propagation):
            # The decision — knowledge, target, score and matched features — is history the
            # moment it is taken; only its delivery lifecycle moves.
            mutable = {'revision', 'status', 'status_reason', 'outcome', 'outcome_reason',
                       'outcome_assignment_id', 'reconsideration_task_id', 'follow_up_task_id'}
            if any(getattr(old, f.name) != getattr(new, f.name) for f in fields(old) if f.name not in mutable):
                raise DomainError('propagation decisions are immutable')
            for name in ('outcome', 'outcome_assignment_id', 'reconsideration_task_id', 'follow_up_task_id'):
                if getattr(old, name) is not None and getattr(old, name) != getattr(new, name):
                    raise DomainError('recorded propagation outcomes and follow-ups are write-once')
        if isinstance(old, Cycle):
            mutable = {'revision', 'status', 'ended_at', 'task_ids', 'unresolved'}
            if any(getattr(old, f.name) != getattr(new, f.name) for f in fields(old) if f.name not in mutable):
                raise DomainError('cycle identity, number and trigger are immutable')
            if new.task_ids[:len(old.task_ids)] != old.task_ids:
                raise DomainError('cycle work is append-only')
        if isinstance(old, Agent) and old.role_id != new.role_id and old.status != AgentStatus.IDLE:
            raise DomainError('running agent cannot change roles')
        if isinstance(old, Run):
            # The run workflow is a guarded lifecycle like any other; the readiness
            # predicates that authorize a step live above this layer, in ``workflow``.
            if old.state != new.state:
                transition(old, new.state)
            if old.result_id is not None and old.result_id != new.result_id:
                raise DomainError('an accepted run result is write-once')
            if old.outcome_id is not None and old.outcome_id != new.outcome_id:
                raise DomainError('a terminal report reference is write-once')
            if {c.id for c in old.acceptance_criteria} != {c.id for c in new.acceptance_criteria}:
                raise DomainError('acceptance criteria cannot change inside a run')
        if hasattr(old, 'status') and old.status != new.status:
            review = None
            if isinstance(new, Finding) and new.review_ids:
                review = snapshot.get(new.review_ids[-1])
            transition(old, new.status, review=review)

    def runs(self):
        """Every run this database holds, newest first.

        Inspection needs an index: a host cannot be asked to remember the identity of a run
        it started. This is a read over stored ``Run`` records and writes nothing.
        """
        try:
            rows = self._db.execute("SELECT data FROM records WHERE kind='Run'").fetchall()
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc
        entries = []
        for row in rows:
            run = loads(row[0])
            entries.append({'run_id': run.id, 'state': str(run.state), 'objective': run.objective,
                            'stop_reason': run.stop_reason, 'result_id': run.result_id,
                            'created_at': run.created_at, 'updated_at': run.updated_at})
        return tuple(sorted(entries, key=lambda e: (e['created_at'], e['run_id']), reverse=True))

    def inspect(self, run_id) -> Inspection:
        try:
            records = self._records(run_id)
            if not records:
                raise DomainError('unknown run')
            events = []
            for row in self._db.execute('SELECT data FROM events WHERE run_id=? ORDER BY sequence', (run_id,)):
                data = json.loads(row[0])
                data['type'] = EventType(data['type'])
                events.append(Event(**data))
            run = next(r for r in records if isinstance(r, Run))
            from .domain import TERMINAL_RUN_STATES
            terminal = run.state in TERMINAL_RUN_STATES
            return Inspection(records, tuple(events), str(run.state) if terminal else 'INCOMPLETE')
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc
