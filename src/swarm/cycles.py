"""Bounded exploration waves, deterministic branch progress, and branch stopping.

Cycles are the controller's own accounting, not a model's request to keep going. A wave
opens only when the controller can actually admit bounded work for it, so "keep
investigating" never buys another round.

Progress is *measured*, never asserted. The measurement is a digest over the knowledge a
branch actually changed, which is why a duplicate claim, a reworded claim with the same
consolidation signature, a repeated NO_CHANGE and a redelivered propagation all leave the
signature untouched, while a new nonduplicate candidate, a promotion, newly verified
evidence, a resolved conflict and changed criterion coverage all move it.
"""
import json
from dataclasses import dataclass, replace
from .context import digest
from .domain import (AgentGroup, BranchStop, Conflict, ConflictStatus, Cycle, CycleStatus, Finding,
                     FindingStatus, GroupStatus, ReviewRecord, Task, TaskStatus, now, transition)
from .events import EventDraft, EventType
from .knowledge import KNOWN, criterion_coverage, duplicate_groups, duplicate_key, findings_of
from .policies import stopped
from .propagation import FOLLOW_UP_KIND, RECONSIDERATION_KIND, pending_follow_ups, undeliverable

TERMINAL_TASKS = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
OUTCOME_STOPS = (('TOOL_BUDGET', BranchStop.BUDGET_LIMIT), ('BUDGET', BranchStop.BUDGET_LIMIT),
                 ('DEPENDENCY', BranchStop.DEPENDENCY_FAILED), ('ATTEMPT_LIMIT', BranchStop.ATTEMPT_LIMIT))
"""Failure outcomes a stopped branch may be attributed to, checked in this order."""


def branch_tasks(snapshot, run_id, group_id):
    return tuple(sorted((t for t in snapshot.values() if isinstance(t, Task) and t.run_id == run_id
                         and t.group_id == group_id), key=lambda t: t.id))


def branch_findings(snapshot, run_id, group_id):
    identities = {t.id for t in branch_tasks(snapshot, run_id, group_id)}
    return tuple(f for f in findings_of(snapshot, run_id) if f.task_id in identities)


@dataclass(frozen=True)
class BranchMeasurement:
    """What a branch has actually contributed, in comparable, deterministic form."""
    group_id: str
    candidates: tuple[str, ...]
    validated: tuple[str, ...]
    verified_evidence: tuple[str, ...]
    resolved_conflicts: tuple[str, ...]
    coverage: tuple[tuple[str, int, bool], ...]

    @property
    def signature(self):
        return digest({'candidates': list(self.candidates), 'validated': list(self.validated),
                       'evidence': list(self.verified_evidence),
                       'resolved': list(self.resolved_conflicts),
                       'coverage': [list(entry) for entry in self.coverage]})

    def detail(self):
        return {'group_id': self.group_id, 'candidates': len(self.candidates),
                'validated': list(self.validated), 'verified_evidence': len(self.verified_evidence),
                'resolved_conflicts': list(self.resolved_conflicts),
                'coverage': [list(entry) for entry in self.coverage], 'signature': self.signature}


def measure_branch(snapshot, run_id, group):
    findings = branch_findings(snapshot, run_id, group.id)
    identities = {f.id for f in findings}
    coverage = criterion_coverage(snapshot, run_id)
    criteria = sorted({c for t in branch_tasks(snapshot, run_id, group.id)
                       for c in t.acceptance_criterion_ids})
    evidence = sorted({item.reference for r in snapshot.values() if isinstance(r, ReviewRecord)
                       and r.target_id in identities for item in r.evidence
                       if item.verified and item.reference})
    return BranchMeasurement(
        group.id,
        # A duplicate adds no key, so repeating a known claim is not progress.
        tuple(sorted({digest(list(duplicate_key(f))) for f in findings if f.status in KNOWN})),
        tuple(sorted(f.id for f in findings if f.status == FindingStatus.VALIDATED)),
        tuple(evidence),
        tuple(sorted(c.id for c in snapshot.values() if isinstance(c, Conflict)
                     and c.run_id == run_id and c.status == ConflictStatus.RESOLVED
                     and set(c.finding_ids) & identities)),
        tuple((i, len(coverage[i].supporting_ids), coverage[i].clean)
              for i in criteria if i in coverage))


def _outcome_stop(tasks):
    for prefix, reason in OUTCOME_STOPS:
        if any(t.outcome and t.outcome.startswith(prefix) for t in tasks
               if t.status in (TaskStatus.FAILED, TaskStatus.CANCELLED)):
            return reason
    return None


def _all_superseded(snapshot, run_id, findings):
    """Every claim this branch still holds is a duplicate represented elsewhere."""
    known = [f for f in findings if f.status in KNOWN]
    if not known and not any(f.status == FindingStatus.SUPERSEDED for f in findings):
        return False
    canonical = {g.canonical_id for g in duplicate_groups(snapshot, run_id)}
    return all(f.id not in canonical for f in known)


def branch_stop_reason(snapshot, run_id, group, measurement, *, cycle_exhausted=False, unresolved=()):
    """The first applicable stop reason, or None while the branch may still contribute.

    Only the first three reasons cancel work that is still open; the rest are recorded once
    the branch has nothing left running, so an independent branch is never collateral.
    """
    run = snapshot[run_id]
    tasks = branch_tasks(snapshot, run_id, group.id)
    if stopped(run):
        return BranchStop.CANCELLED
    if group.idle_cycles >= run.no_progress_limit:
        return BranchStop.NO_PROGRESS
    if cycle_exhausted and any(p.target_group_id == group.id for p in unresolved):
        return BranchStop.CYCLE_LIMIT
    open_work = [t for t in tasks if t.status not in TERMINAL_TASKS]
    if open_work:
        # Work that has become redundant is stopped; work that may still contribute is not.
        if _all_superseded(snapshot, run_id, branch_findings(snapshot, run_id, group.id)):
            return BranchStop.SUPERSEDED
        if measurement.coverage and all(clean for _, _, clean in measurement.coverage):
            return BranchStop.CRITERION_COVERED
        return None
    # Nothing is open. A branch that simply finished stays available to the host; only one
    # that ran into a limit is closed, so its reason is recorded rather than left implicit.
    return _outcome_stop(tasks)


def progress_records(snapshot, run_id, group, cycle_number):
    """Fold one cycle's measurement into the branch, returning the record and its event."""
    measurement = measure_branch(snapshot, run_id, group)
    signature = measurement.signature
    advanced = signature != group.progress_signature
    idle = 0 if advanced else group.idle_cycles + 1
    updated = replace(group, revision=group.revision + 1, progress_signature=signature,
                      progress_cycle=cycle_number, idle_cycles=idle)
    event = EventDraft(type=EventType.BRANCH_PROGRESS, record_id=updated.id,
                       record_revision=updated.revision, group_id=group.id,
                       detail_json=json.dumps({'cycle': cycle_number, 'progress': advanced,
                                               'idle_cycles': idle,
                                               'previous_signature': group.progress_signature,
                                               **measurement.detail()}))
    return updated, event, measurement


def stop_records(snapshot, run_id, group, reason):
    """Close a branch: cancel its schedulable work, keep everything it established."""
    records, events = [], []
    for task in branch_tasks(snapshot, run_id, group.id):
        if task.status in (TaskStatus.PENDING, TaskStatus.READY):
            cancelled = replace(transition(task, TaskStatus.CANCELLED), assignment_id=None,
                                outcome=f'BRANCH_STOPPED: {reason}')
            records.append(cancelled)
            events.append(EventDraft(type=EventType.TASK_CANCELLED, record_id=cancelled.id,
                                     record_revision=cancelled.revision, task_id=cancelled.id,
                                     group_id=group.id,
                                     detail_json=json.dumps({'reason': cancelled.outcome})))
    closed = replace(transition(group, GroupStatus.CLOSED), stop_reason=str(reason))
    records.append(closed)
    events.append(EventDraft(type=EventType.BRANCH_TERMINATED, record_id=closed.id,
                             record_revision=closed.revision, group_id=group.id,
                             detail_json=json.dumps(
                                 {'reason': str(reason),
                                  'cancelled_task_ids': [r.id for r in records if isinstance(r, Task)],
                                  'validated_findings': sorted(
                                      f.id for f in branch_findings(snapshot, run_id, group.id)
                                      if f.status == FindingStatus.VALIDATED)})))
    return records, events


def active_groups(snapshot, run_id):
    return tuple(sorted((g for g in snapshot.values() if isinstance(g, AgentGroup)
                         and g.run_id == run_id and g.status == GroupStatus.ACTIVE), key=lambda g: g.id))


# --- cycles ---------------------------------------------------------------------

@dataclass(frozen=True)
class CycleTrigger:
    """Why another bounded wave is justified, and the exact work it would admit."""
    kind: str
    propagation_id: str
    task_kind: str

    @property
    def reason(self):
        return f'{self.kind}: {self.propagation_id}'


def cycle_triggers(snapshot, run_id):
    """Deterministic triggers, each of which names one admissible bounded task.

    A trigger exists only where controller-authored work is possible, so a wave can never
    open on sentiment. Coverage loss is recorded as a gap rather than used as a trigger:
    naming the work that would repair it belongs to the synthesis gate, not to Stage 6.
    """
    triggers = [CycleTrigger('RETRACTION' if p.retracts_id else 'NEW_KNOWLEDGE', p.id,
                             RECONSIDERATION_KIND) for p in undeliverable(snapshot, run_id)]
    triggers += [CycleTrigger('FOLLOW_UP_REQUESTED', p.id, FOLLOW_UP_KIND)
                 for p in pending_follow_ups(snapshot, run_id)]
    return tuple(triggers)


def coverage_gaps(snapshot, run_id):
    """Criteria that no clean validated knowledge currently supports, with why."""
    coverage = criterion_coverage(snapshot, run_id)
    lost = {f.id for f in findings_of(snapshot, run_id) if f.status == FindingStatus.INVALIDATED}
    gaps = []
    for identity in sorted(coverage):
        entry = coverage[identity]
        if entry.clean:
            continue
        withdrawn = sorted(i for i in lost if identity in snapshot[i].criterion_ids)
        gaps.append({'criterion_id': identity, 'supporting_ids': list(entry.supporting_ids),
                     'conflict_ids': list(entry.conflict_ids), 'invalidated_support': withdrawn,
                     'reason': 'CONFLICTED' if entry.conflict_ids else
                               'COVERAGE_LOST' if withdrawn else 'UNSUPPORTED'})
    return tuple(gaps)


def open_records(identity, run_id, number, triggers, task_ids=()):
    cycle = Cycle(id=identity('cycle'), run_id=run_id, number=number,
                  trigger=triggers[0].kind if triggers else 'INITIAL',
                  trigger_ids=tuple(t.propagation_id for t in triggers),
                  reason='; '.join(t.reason for t in triggers) or 'initial exploration wave',
                  task_ids=tuple(task_ids))
    return cycle, EventDraft(type=EventType.CYCLE_STARTED, record_id=cycle.id,
                             record_revision=cycle.revision,
                             detail_json=json.dumps({'number': number, 'trigger': cycle.trigger,
                                                     'trigger_ids': list(cycle.trigger_ids),
                                                     'reason': cycle.reason,
                                                     'task_ids': list(cycle.task_ids)}))


def close_records(cycle, unresolved, gaps):
    closed = replace(transition(cycle, CycleStatus.CLOSED), ended_at=now(),
                     unresolved=tuple(sorted(unresolved)))
    return closed, EventDraft(type=EventType.CYCLE_COMPLETED, record_id=closed.id,
                              record_revision=closed.revision,
                              detail_json=json.dumps({'number': closed.number,
                                                      'trigger': closed.trigger,
                                                      'task_ids': list(closed.task_ids),
                                                      'unresolved': list(closed.unresolved),
                                                      'coverage_gaps': list(gaps)}))
