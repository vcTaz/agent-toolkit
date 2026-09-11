"""Run metrics derived from authoritative state, not from a parallel telemetry system.

Every number here is recomputed from the committed records and the run's own durable
counters. Nothing is incremented as a side effect of doing work, so a metric can never
disagree with the state it describes.
"""
from datetime import datetime
from .domain import (Agent, AgentGroup, Assignment, AssignmentStatus, Conflict, ConflictStatus,
                     Cycle, CycleStatus, Finding, FindingStatus, GroupStatus, Message,
                     Propagation, PropagationStatus, ReconsiderationOutcome, Result, ResultStatus,
                     ReviewKind, ReviewRecord, Task, TaskRequest, TaskStatus, TerminalReport)


def _count(records, kind, attribute, values):
    counts = dict.fromkeys((str(v) for v in values), 0)
    for record in records:
        if isinstance(record, kind):
            counts[str(getattr(record, attribute))] += 1
    return counts


def _moment(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def duration_seconds(snapshot, run_id, events=()):
    """Wall-clock span from the run record to the last thing that happened to it."""
    run = snapshot[run_id]
    start = _moment(run.created_at)
    report = next((r for r in snapshot.values() if isinstance(r, TerminalReport)
                   and r.run_id == run_id), None)
    latest = _moment(report.created_at) if report is not None else None
    if latest is None and events:
        latest = _moment(events[-1].timestamp)
    if latest is None:
        latest = _moment(run.updated_at)
    if start is None or latest is None:
        return None
    return round(max(0.0, (latest - start).total_seconds()), 3)


def metrics(snapshot, run_id, events=()):
    """One run's architecture-level metrics, in a stable, JSON-serialisable shape."""
    run = snapshot[run_id]
    records = [r for r in snapshot.values()
               if getattr(r, 'run_id', run_id) == run_id or r.id == run_id]
    tasks = [r for r in records if isinstance(r, Task)]
    findings = [r for r in records if isinstance(r, Finding)]
    reviews = [r for r in records if isinstance(r, ReviewRecord)]
    propagations = [r for r in records if isinstance(r, Propagation)]
    kinds = {}
    for task in tasks:
        kinds[task.kind] = kinds.get(task.kind, 0) + 1
    return {
        'terminal_state': str(run.state),
        'stop_reason': run.stop_reason,
        'duration_seconds': duration_seconds(snapshot, run_id, events),
        'provider_requests': run.provider_requests,
        'provider_request_limit': run.provider_request_limit,
        'tool_calls': run.tool_calls,
        'tool_call_limit': run.tool_call_limit,
        'cycles_charged': run.cycle,
        'cycle_limit': run.cycle_limit,
        'repair_rounds': run.repair_rounds,
        'presentation_revisions': run.presentation_revisions,
        'synthesis_attempts': run.synthesis_attempts,
        'tasks': {'total': len(tasks), 'by_kind': dict(sorted(kinds.items())),
                  **_count(tasks, Task, 'status', TaskStatus)},
        'task_requests': sum(isinstance(r, TaskRequest) for r in records),
        'assignments': {'total': sum(isinstance(r, Assignment) for r in records),
                        **_count(records, Assignment, 'status', AssignmentStatus)},
        'agents': {'total': sum(isinstance(r, Agent) for r in records)},
        'groups': {'total': sum(isinstance(r, AgentGroup) for r in records),
                   'active': sum(isinstance(r, AgentGroup) and r.status == GroupStatus.ACTIVE
                                 for r in records),
                   'closed': sum(isinstance(r, AgentGroup) and r.status == GroupStatus.CLOSED
                                 for r in records)},
        'findings': {'total': len(findings), 'candidates': sum(
            f.status in (FindingStatus.PROPOSED, FindingStatus.CRITIQUED) for f in findings),
            **_count(findings, Finding, 'status', FindingStatus)},
        'reviews': {'total': len(reviews),
                    'criticism': sum(r.kind == ReviewKind.CRITICISM for r in reviews),
                    'validation': sum(r.kind == ReviewKind.VALIDATION for r in reviews),
                    'final': sum(r.kind == ReviewKind.FINAL for r in reviews),
                    'verified_evidence': sum(1 for r in reviews for e in r.evidence if e.verified)},
        'propagations': {'total': len(propagations),
                         **_count(propagations, Propagation, 'status', PropagationStatus),
                         'insights': sum(p.retracts_id is None for p in propagations),
                         'retractions': sum(p.retracts_id is not None for p in propagations)},
        'reconsiderations': {str(outcome): sum(p.outcome == outcome for p in propagations)
                             for outcome in ReconsiderationOutcome},
        'conflicts': {'total': sum(isinstance(r, Conflict) for r in records),
                      'open': sum(isinstance(r, Conflict) and r.status == ConflictStatus.OPEN
                                  for r in records),
                      'resolved': sum(isinstance(r, Conflict) and r.status == ConflictStatus.RESOLVED
                                      for r in records)},
        'cycles': {'total': sum(isinstance(r, Cycle) for r in records),
                   'open': sum(isinstance(r, Cycle) and r.status == CycleStatus.OPEN
                               for r in records),
                   'closed': sum(isinstance(r, Cycle) and r.status == CycleStatus.CLOSED
                                 for r in records)},
        'results': {'versions': sum(isinstance(r, Result) for r in records),
                    **_count(records, Result, 'status', ResultStatus)},
        'messages': sum(isinstance(r, Message) for r in records),
        'records': len(records),
        'events': len(events),
    }
