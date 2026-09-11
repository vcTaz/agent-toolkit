"""The run-level state machine: guarded phases and terminal outcomes.

This is a *coordinator*, not a replacement for the services beneath it. EXPLORING still
means the Stage-4 scheduler and the Stage-6 cycle records; EVALUATING still means Stage-5
criticism and validation; CONSOLIDATING still means the Stage-5/6 knowledge, conflict and
propagation services. The state machine only says which of them the run is currently in,
and refuses a step whose guard does not hold.

Every guard is a pure predicate over one snapshot, so a transition can be tested without a
controller, and no transition can be taken because a model asked for it.
"""
import json
from dataclasses import dataclass, replace
from .completion import unconsumed_knowledge
from .domain import (AgentGroup, Assignment, AssignmentStatus, Finding, FindingStatus, GateStatus,
                     GroupStatus, Result, ResultStatus, RunState, Task, TaskStatus, TerminalReport,
                     ReviewKind, ReviewRecord, RUN_TRANSITIONS, TERMINAL_RUN_STATES, now,
                     transition)
from .events import EventDraft, EventType
from .policies import (FINDING_REVIEW_KINDS, REVIEW_TASK_KINDS, SYNTHESIS_KIND,
                       remaining_seconds, review_kind, stopped)

OPEN_TASKS = (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)
TERMINAL_EVENTS = {RunState.COMPLETED: EventType.RUN_COMPLETED,
                   RunState.EXHAUSTED: EventType.RUN_EXHAUSTED,
                   RunState.FAILED: EventType.RUN_FAILED,
                   RunState.CANCELLED: EventType.RUN_CANCELLED}


@dataclass(frozen=True)
class Guard:
    allowed: bool
    reason: str = ''


def _tasks(snapshot, run_id):
    return [t for t in snapshot.values() if isinstance(t, Task) and t.run_id == run_id]


def _active_assignments(snapshot, run_id):
    return [a for a in snapshot.values() if isinstance(a, Assignment) and a.run_id == run_id
            and a.status in (AssignmentStatus.CREATED, AssignmentStatus.RUNNING)]


def wave_settled(snapshot, run_id):
    """No assignment in flight and no schedulable exploration work left in this wave."""
    if _active_assignments(snapshot, run_id):
        return Guard(False, 'ASSIGNMENTS_IN_FLIGHT')
    open_work = sorted(t.id for t in _tasks(snapshot, run_id)
                       if t.status in OPEN_TASKS and review_kind(t) is None
                       and t.kind != SYNTHESIS_KIND)
    return Guard(not open_work, 'EXPLORATION_WORK_OPEN: ' + ', '.join(open_work) if open_work else '')


def reviews_settled(snapshot, run_id):
    """Every candidate has been reviewed or has a recorded review gap."""
    if _active_assignments(snapshot, run_id):
        return Guard(False, 'ASSIGNMENTS_IN_FLIGHT')
    open_reviews = sorted(t.id for t in _tasks(snapshot, run_id)
                          if REVIEW_TASK_KINDS.get(t.kind) in FINDING_REVIEW_KINDS
                          and t.status in OPEN_TASKS)
    return Guard(not open_reviews, 'REVIEW_WORK_OPEN: ' + ', '.join(open_reviews) if open_reviews else '')


def decomposed(snapshot, run_id):
    """A validated task graph exists. The graph's shape is a snapshot invariant already."""
    tasks = _tasks(snapshot, run_id)
    if not tasks:
        return Guard(False, 'NO_TASKS')
    return Guard(True)


def configured(snapshot, run_id):
    """The run's own configuration is usable; an unusable one is FAILED, never EXHAUSTED."""
    run = snapshot[run_id]
    if not run.acceptance_criteria:
        return Guard(False, 'NO_ACCEPTANCE_CRITERIA')
    if len({c.id for c in run.acceptance_criteria}) != len(run.acceptance_criteria):
        return Guard(False, 'DUPLICATE_CRITERION_IDS')
    if not any(c.required for c in run.acceptance_criteria):
        return Guard(False, 'NO_REQUIRED_CRITERION')
    if run.provider_request_limit < 1 or run.cycle_limit < 1:
        return Guard(False, 'INVALID_LIMITS')
    return Guard(True)


def synthesis_dispatchable(snapshot, run_id, gate):
    if gate.status != GateStatus.READY:
        return Guard(False, f'GATE_{gate.status}')
    run = snapshot[run_id]
    if run.synthesis_attempts >= run.synthesis_attempt_limit:
        return Guard(False, 'SYNTHESIS_ATTEMPT_LIMIT')
    return Guard(True)


def candidate_ready(snapshot, run_id):
    """A candidate result exists and nothing is still executing against it."""
    if _active_assignments(snapshot, run_id):
        return Guard(False, 'ASSIGNMENTS_IN_FLIGHT')
    candidates = [r for r in snapshot.values() if isinstance(r, Result) and r.run_id == run_id
                  and r.status == ResultStatus.CANDIDATE]
    return Guard(bool(candidates), '' if candidates else 'NO_CANDIDATE_RESULT')


GUARDS = {
    (RunState.RECEIVED, RunState.DECOMPOSING): configured,
    (RunState.DECOMPOSING, RunState.EXPLORING): decomposed,
    (RunState.EXPLORING, RunState.EVALUATING): wave_settled,
    (RunState.EVALUATING, RunState.CONSOLIDATING): reviews_settled,
    (RunState.SYNTHESIZING, RunState.FINAL_REVIEW): candidate_ready,
}
"""Guards that depend only on the snapshot. The transitions out of CONSOLIDATING and
FINAL_REVIEW depend on the gate decision and the review verdict, so the controller supplies
those explicitly through ``advance``."""


def legal(current, target):
    return target in RUN_TRANSITIONS.get(current, ())


def check(snapshot, run_id, target, *, guard=None):
    """Whether one run transition may be taken now, and why not when it may not."""
    run = snapshot[run_id]
    if not legal(run.state, target):
        return Guard(False, f'ILLEGAL_TRANSITION: {run.state} -> {target}')
    if target in TERMINAL_RUN_STATES:
        return Guard(True)
    if stopped(run) or remaining_seconds(run) <= 0:
        return Guard(False, 'RUN_NOT_LIVE')
    if guard is not None:
        return guard
    predicate = GUARDS.get((run.state, target))
    return predicate(snapshot, run_id) if predicate else Guard(True)


def advance(snapshot, run_id, target, *, guard=None, reason='', **fields):
    """Return the run successor and its event, or ``(None, refusal)``.

    Nothing is committed here: the controller commits the successor together with whatever
    else the transition implies, so a run can never be COMPLETED without its accepted
    result in the same transaction.
    """
    decision = check(snapshot, run_id, target, guard=guard)
    if not decision.allowed:
        return None, decision
    run = snapshot[run_id]
    changed = transition(run, target)
    if fields:
        changed = replace(changed, **fields)
    event = EventDraft(type=EventType.RUN_STATE_CHANGED, record_id=changed.id,
                       record_revision=changed.revision, correlation_id=run_id,
                       detail_json=json.dumps({'from': str(run.state), 'to': str(target),
                                               'reason': reason, 'cycle': changed.cycle,
                                               'repair_rounds': changed.repair_rounds,
                                               'presentation_revisions': changed.presentation_revisions}))
    return changed, event


# --- terminal outcomes -----------------------------------------------------------

def branch_stops(snapshot, run_id):
    """Every closed branch and why it closed. Run terminal decisions aggregate these; they
    never change what a branch stop meant locally."""
    return tuple(f'{g.id}: {g.stop_reason}' for g in sorted(
        (r for r in snapshot.values() if isinstance(r, AgentGroup) and r.run_id == run_id
         and r.status == GroupStatus.CLOSED and r.stop_reason), key=lambda g: g.id))


def final_review_issues(snapshot, run_id):
    issues = []
    for review in sorted((r for r in snapshot.values() if isinstance(r, ReviewRecord)
                          and r.run_id == run_id and r.kind == ReviewKind.FINAL), key=lambda r: r.id):
        for issue in review.blocking_issues + review.unsupported_claims:
            issues.append(f'{review.id} ({review.decision}): {issue}')
        for criterion in review.criterion_ids:
            issues.append(f'{review.id} ({review.decision}): criterion {criterion}')
    return tuple(issues)


def terminal_report(snapshot, run_id, identity, state, stop_reason, *, gaps=(), result_id=None):
    """Everything a run learned, and everything it did not, at the moment it ended.

    A non-success report keeps the validated partial knowledge and the unresolved gaps side
    by side, so nothing here can be read as a completed answer.
    """
    validated = tuple(sorted(f.id for f in snapshot.values() if isinstance(f, Finding)
                             and f.run_id == run_id and f.status == FindingStatus.VALIDATED))
    return TerminalReport(id=identity('outcome'), run_id=run_id, state=state,
                          stop_reason=stop_reason, result_id=result_id,
                          validated_finding_ids=validated, gaps=tuple(gaps),
                          branch_stops=branch_stops(snapshot, run_id),
                          final_review_issues=final_review_issues(snapshot, run_id),
                          unconsumed_knowledge=unconsumed_knowledge(snapshot, run_id),
                          created_at=now())


def terminal_event(report, run, **detail):
    return EventDraft(type=TERMINAL_EVENTS[report.state], record_id=report.id,
                      record_revision=report.revision, correlation_id=run.id,
                      detail_json=json.dumps({'state': str(report.state),
                                              'stop_reason': report.stop_reason,
                                              'result_id': report.result_id,
                                              'validated_findings': list(report.validated_finding_ids),
                                              'gaps': [g.key for g in report.gaps],
                                              'branch_stops': list(report.branch_stops),
                                              'final_review_issues': list(report.final_review_issues),
                                              'unconsumed_knowledge': list(report.unconsumed_knowledge),
                                              'cycle': run.cycle, 'repair_rounds': run.repair_rounds,
                                              **detail}))
