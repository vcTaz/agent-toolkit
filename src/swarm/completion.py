"""The synthesis gate: whether trustworthy knowledge is sufficient to produce a result.

Nothing here asks a model whether it is ready to answer. Readiness is *computed* from the
same records Stage 5 and Stage 6 already maintain — ``knowledge.criterion_coverage`` for
per-criterion support, ``cycles.coverage_gaps`` for why a criterion is unclean — and the
gate's only new work is the decision Stage 6 deliberately refused to make: whether an
unresolved gap still admits bounded repair, or means the run is exhausted.

The gate returns a structured decision with explicit reasons. It never commits anything.
"""
from dataclasses import dataclass
from .domain import (Agent, AgentStatus, Conflict, ConflictStatus, Finding, FindingStatus, Gap,
                     GateStatus, Propagation, PropagationStatus, ReconsiderationOutcome, Result,
                     ResultStatus, ReviewKind, ReviewRecord, Role, RoleName, Task, TaskRequest,
                     TaskStatus)
from .knowledge import criterion_coverage, findings_of
from .cycles import coverage_gaps
from .policies import (COMPLETION_REQUESTS, DUE_REVIEW_STATUSES, FINDING_REVIEW_KINDS,
                       REVIEW_TASK_KINDS, outstanding_reviews, remaining_seconds, review_kind,
                       stopped)
from .review import dependency_closure

OPEN_TASKS = (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)
REPAIRABLE = ('UNSUPPORTED', 'COVERAGE_LOST', 'CONFLICTED', 'REVIEW_OUTSTANDING',
              'SUPPORT_DEPENDENCY_INVALID', 'BLOCKING_ISSUE_OUTSTANDING')
"""Gap reasons that name work a repair task could plausibly do. A reason outside this set
is a defect of the run's configuration, not something more exploration can fix."""


# --- criterion readiness ---------------------------------------------------------

@dataclass(frozen=True)
class CriterionReadiness:
    """Everything the gate can say about one acceptance criterion."""
    criterion_id: str
    required: bool
    supporting_ids: tuple[str, ...]
    verified_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    covered: bool
    clean: bool
    blocking_gap: str | None

    def detail(self):
        return {'criterion_id': self.criterion_id, 'required': self.required,
                'supporting_ids': list(self.supporting_ids), 'verified_ids': list(self.verified_ids),
                'conflict_ids': list(self.conflict_ids), 'covered': self.covered,
                'clean': self.clean, 'blocking_gap': self.blocking_gap}


def _verified_support(snapshot, finding_id):
    """Whether a host verifier — not a reviewer's confidence — attested this exact claim."""
    return any(isinstance(r, ReviewRecord) and r.target_id == finding_id
               and any(e.verified and e.reference for e in r.evidence) for r in snapshot.values())


def _support_dependencies_valid(snapshot, finding):
    closure = dependency_closure(snapshot, finding)
    return all(isinstance(snapshot.get(i), Finding)
               and snapshot[i].status == FindingStatus.VALIDATED for i in closure)


def _unresolved_blocking(snapshot, finding_id):
    """Blocking critique issues raised against a finding that no passing validation named."""
    reviews = [r for r in snapshot.values() if isinstance(r, ReviewRecord) and r.target_id == finding_id]
    from .domain import ReviewDecision, blocking_keys
    raised = {key for r in reviews if r.kind == ReviewKind.CRITICISM for key in blocking_keys(r)}
    addressed = {key for r in reviews if r.kind == ReviewKind.VALIDATION
                 and r.decision == ReviewDecision.PASS for key in r.resolved_issues}
    return sorted(raised - addressed)


def _open_review_tasks(snapshot, run_id):
    return tuple(sorted((t for t in snapshot.values() if isinstance(t, Task) and t.run_id == run_id
                         and REVIEW_TASK_KINDS.get(t.kind) in FINDING_REVIEW_KINDS
                         and t.status in OPEN_TASKS), key=lambda t: t.id))


def _review_outstanding(snapshot, run_id):
    """Required finding review work that is scheduled or still owed, run-wide."""
    return (tuple(t.id for t in _open_review_tasks(snapshot, run_id)),
            outstanding_reviews(snapshot, snapshot[run_id]))


def _review_outstanding_for(snapshot, run_id, criterion_id):
    """The same question asked of one criterion, so a gap names the work that concerns it.

    A finding awaiting review elsewhere delays the whole run — the wave is not settled —
    but it is not a *gap in this criterion*, and the gate says which is which.
    """
    scheduled = {t.target_finding_id for t in _open_review_tasks(snapshot, run_id)}
    return any(criterion_id in f.criterion_ids
               and (f.id in scheduled or f.status in DUE_REVIEW_STATUSES)
               for f in findings_of(snapshot, run_id))


def criterion_readiness(snapshot, run_id):
    """Per-criterion readiness, in criterion order, using the Stage-6 coverage model.

    Two contradictory validated findings do not make a criterion covered: an open conflict
    over any supporting finding leaves the coverage unclean, exactly as Stage 5 defined it.
    """
    run = snapshot[run_id]
    coverage = criterion_coverage(snapshot, run_id)
    reasons = {gap['criterion_id']: gap['reason'] for gap in coverage_gaps(snapshot, run_id)}
    open_reviews, owed = _review_outstanding(snapshot, run_id)
    entries = []
    for criterion in run.acceptance_criteria:
        entry = coverage[criterion.id]
        verified = tuple(i for i in entry.supporting_ids if _verified_support(snapshot, i))
        invalid = tuple(i for i in entry.supporting_ids
                        if not _support_dependencies_valid(snapshot, snapshot[i]))
        blocked = tuple(i for i in entry.supporting_ids if _unresolved_blocking(snapshot, i))
        gap = None
        if not entry.clean:
            gap = reasons.get(criterion.id, 'UNSUPPORTED')
        elif invalid:
            gap = 'SUPPORT_DEPENDENCY_INVALID'
        elif blocked:
            gap = 'BLOCKING_ISSUE_OUTSTANDING'
        elif not verified:
            gap = 'SUPPORT_UNVERIFIED'
        elif _review_outstanding_for(snapshot, run_id, criterion.id):
            gap = 'REVIEW_OUTSTANDING'
        entries.append(CriterionReadiness(criterion.id, criterion.required, entry.supporting_ids,
                                          verified, entry.conflict_ids, bool(entry.supporting_ids),
                                          entry.clean and not invalid and not blocked, gap))
    return tuple(entries)


def gap_records(snapshot, run_id, readiness=None):
    """Structured gaps for every criterion the gate refuses, required flag included."""
    run = snapshot[run_id]
    required = {c.id: c.required for c in run.acceptance_criteria}
    by_id = {gap['criterion_id']: gap for gap in coverage_gaps(snapshot, run_id)}
    gaps = []
    for entry in readiness if readiness is not None else criterion_readiness(snapshot, run_id):
        if entry.blocking_gap is None:
            continue
        raw = by_id.get(entry.criterion_id, {})
        gaps.append(Gap(criterion_id=entry.criterion_id, reason=entry.blocking_gap,
                        required=required.get(entry.criterion_id, True),
                        supporting_ids=entry.supporting_ids, conflict_ids=entry.conflict_ids,
                        invalidated_support=tuple(raw.get('invalidated_support', ()))))
    return tuple(gaps)


# --- the gate --------------------------------------------------------------------

@dataclass(frozen=True)
class GateDecision:
    status: GateStatus
    reasons: tuple[str, ...]
    readiness: tuple[CriterionReadiness, ...]
    gaps: tuple[Gap, ...]
    repairable: tuple[Gap, ...]
    support: tuple[str, ...]
    """The validated findings a synthesis would be built from, in deterministic order."""

    @property
    def ready(self):
        return self.status == GateStatus.READY

    def detail(self):
        return {'status': str(self.status), 'reasons': list(self.reasons),
                'criteria': [entry.detail() for entry in self.readiness],
                'gaps': [{'criterion_id': g.criterion_id, 'reason': g.reason,
                          'required': g.required, 'supporting_ids': list(g.supporting_ids),
                          'conflict_ids': list(g.conflict_ids),
                          'invalidated_support': list(g.invalidated_support)} for g in self.gaps],
                'repairable': [g.key for g in self.repairable], 'support': list(self.support)}


def _open_required_work(snapshot, run_id):
    return tuple(sorted(t.id for t in snapshot.values() if isinstance(t, Task)
                        and t.run_id == run_id and t.required and t.status in OPEN_TASKS
                        and review_kind(t) != ReviewKind.FINAL and t.kind != 'synthesis'))


def _unsettled_branch_work(snapshot, run_id):
    return tuple(sorted(t.id for t in snapshot.values() if isinstance(t, Task)
                        and t.run_id == run_id and t.status in OPEN_TASKS
                        and review_kind(t) is None and t.kind not in ('synthesis',)))


def support_findings(snapshot, run_id):
    """Validated knowledge a synthesis may build on, criterion-relevant first.

    Propagation is not a prerequisite: a validated finding no downstream task ever consumed
    is still current knowledge, and is offered here on the same terms as any other.
    """
    run = snapshot[run_id]
    criteria = {c.id for c in run.acceptance_criteria}
    validated = [f for f in findings_of(snapshot, run_id) if f.status == FindingStatus.VALIDATED]
    relevant = [f for f in validated if set(f.criterion_ids) & criteria]
    selected, order = set(), []
    for finding in sorted(relevant, key=lambda f: f.id):
        for identity in (finding.id,) + dependency_closure(snapshot, finding):
            if identity not in selected and isinstance(snapshot.get(identity), Finding):
                selected.add(identity)
                order.append(identity)
    return tuple(sorted(order))


def completion_cost(run):
    """Provider requests the run still needs in order to finish from where it stands.

    Held-back capacity is for work *ahead*: once the synthesis has been dispatched only the
    final review remains, and once the review has run the run owes nothing further. Charging
    the full reserve at every re-check would refuse a result the run has already paid for.
    """
    from .domain import RunState
    if run.state == RunState.FINAL_REVIEW:
        return 0
    return 1 if run.state == RunState.SYNTHESIZING else COMPLETION_REQUESTS


def budget_sufficient(snapshot, run_id):
    """Enough provider budget for the completion work this run has not yet paid for."""
    run = snapshot[run_id]
    return run.provider_request_limit - run.provider_requests >= completion_cost(run)


def evaluate_gate(snapshot, run_id):
    """Compute readiness. READY, NOT_READY or EXHAUSTED, always with reasons."""
    run = snapshot[run_id]
    readiness = criterion_readiness(snapshot, run_id)
    gaps = gap_records(snapshot, run_id, readiness)
    required_gaps = tuple(g for g in gaps if g.required)
    support = support_findings(snapshot, run_id)
    reasons = []
    if stopped(run) or remaining_seconds(run) <= 0:
        reasons.append('RUN_NOT_LIVE')
    for gap in required_gaps:
        reasons.append(f'CRITERION_{gap.reason}: {gap.criterion_id}')
    open_reviews, owed = _review_outstanding(snapshot, run_id)
    if open_reviews or owed:
        reasons.append('REQUIRED_REVIEW_OUTSTANDING')
    required_work = _open_required_work(snapshot, run_id)
    if required_work:
        reasons.append('REQUIRED_WORK_UNSETTLED: ' + ', '.join(required_work))
    branch_work = _unsettled_branch_work(snapshot, run_id)
    if branch_work:
        reasons.append('BRANCH_WORK_UNSETTLED: ' + ', '.join(branch_work))
    if not budget_sufficient(snapshot, run_id):
        reasons.append('COMPLETION_BUDGET_INSUFFICIENT')
    if not support and any(c.required for c in run.acceptance_criteria):
        reasons.append('NO_VALIDATED_SUPPORT')
    if not reasons:
        return GateDecision(GateStatus.READY, (), readiness, gaps, (), support)
    repairable = tuple(g for g in required_gaps
                       if g.reason in REPAIRABLE and repair_admissible(snapshot, run_id, g).admissible)
    blocked = 'RUN_NOT_LIVE' in reasons or 'COMPLETION_BUDGET_INSUFFICIENT' in reasons
    settling = bool(open_reviews or required_work or branch_work or owed)
    if not blocked and (settling or repairable):
        return GateDecision(GateStatus.NOT_READY, tuple(reasons), readiness, gaps, repairable, support)
    return GateDecision(GateStatus.EXHAUSTED, tuple(reasons), readiness, gaps, repairable, support)


# --- repair admissibility --------------------------------------------------------

@dataclass(frozen=True)
class RepairDecision:
    admissible: bool
    reason: str = ''

    def detail(self):
        return {'admissible': self.admissible, 'reason': self.reason}


def repair_key(gap, review_id):
    """Identity of one repair request: the gap it closes and the review that found it."""
    return f'{review_id or "GATE"}#{gap.criterion_id}#{gap.reason}'


def existing_repair(snapshot, run_id, key):
    return next((t for t in sorted((r for r in snapshot.values() if isinstance(r, Task)
                                    and r.run_id == run_id and r.kind == 'repair'), key=lambda t: t.id)
                 if t.outcome == key or t.description.startswith(key)), None)


def repair_admissible(snapshot, run_id, gap, review_id=None):
    """Bounded controller authority to open repair work for one gap.

    Every limit the run declares is checked here, so "try again" can never be bought by a
    model asking for it: cycle, repair round, task graph, provider budget and deadline.
    """
    run = snapshot[run_id]
    if stopped(run) or remaining_seconds(run) <= 0:
        return RepairDecision(False, 'RUN_STOPPED')
    if gap.reason not in REPAIRABLE:
        return RepairDecision(False, 'GAP_NOT_REPAIRABLE')
    if run.repair_rounds >= run.repair_round_limit:
        return RepairDecision(False, 'REPAIR_LIMIT')
    if run.cycle >= run.cycle_limit:
        return RepairDecision(False, 'CYCLE_LIMIT')
    if sum(isinstance(r, (Task, TaskRequest)) for r in snapshot.values()) >= run.task_limit:
        return RepairDecision(False, 'TASK_LIMIT')
    if run.provider_request_limit - run.provider_requests <= COMPLETION_REQUESTS:
        return RepairDecision(False, 'BUDGET_EXHAUSTED')
    if existing_repair(snapshot, run_id, repair_key(gap, review_id)) is not None:
        return RepairDecision(False, 'DUPLICATE_REPAIR')
    if not repair_capacity(snapshot, run_id):
        return RepairDecision(False, 'NO_REPAIR_CAPACITY')
    return RepairDecision(True)


def repair_capacity(snapshot, run_id):
    """Whether repair work could actually be executed if it were created.

    Admitting work nothing can run would spend an exploration wave to reach the same gap
    again, so capacity is part of admissibility rather than something discovered at
    dispatch: a role for repair work must be registered and one unbranched agent free.
    """
    if not any(isinstance(r, Role) and r.name == RoleName.SPECIALIST for r in snapshot.values()):
        return False
    return any(isinstance(a, Agent) and a.run_id == run_id and a.group_id is None
               and a.status != AgentStatus.DISABLED for a in snapshot.values())


# --- limitations and unconsumed knowledge ----------------------------------------

def limitations(snapshot, run_id, readiness=None):
    """Bounded caveats a synthesis must acknowledge rather than quietly present as settled.

    Contested information appears here whether or not the conflict touches a required
    criterion, so a result can never present one side of an open conflict as agreed.
    """
    readiness = readiness if readiness is not None else criterion_readiness(snapshot, run_id)
    notes = []
    for conflict in sorted((c for c in snapshot.values() if isinstance(c, Conflict)
                            and c.run_id == run_id and c.status == ConflictStatus.OPEN),
                           key=lambda c: c.id):
        notes.append(f'OPEN CONFLICT {conflict.id} ({conflict.kind}) over '
                     f'{", ".join(conflict.finding_ids)}: {conflict.reason}')
    for entry in readiness:
        if entry.blocking_gap and not entry.required:
            notes.append(f'OPTIONAL CRITERION {entry.criterion_id} is not cleanly '
                         f'supported ({entry.blocking_gap})')
    return tuple(notes)


def unconsumed_knowledge(snapshot, run_id):
    """Deliveries that reached a branch and were never answered, and follow-ups never opened.

    Stage 6 recorded these on the propagation; the terminal report is where a run finally
    says "we learned this and nothing used it".
    """
    notes = []
    for propagation in sorted((p for p in snapshot.values() if isinstance(p, Propagation)
                               and p.run_id == run_id), key=lambda p: p.id):
        if propagation.status in (PropagationStatus.SELECTED, PropagationStatus.DELIVERED):
            notes.append(f'{propagation.id}: {propagation.canonical_finding_id} reached '
                         f'{propagation.target_task_id} and was never answered')
        elif (propagation.outcome == ReconsiderationOutcome.FOLLOW_UP_REQUESTED
              and not propagation.follow_up_task_id):
            notes.append(f'{propagation.id}: follow-up requested for '
                         f'{propagation.target_task_id} and never opened')
        elif propagation.outcome == ReconsiderationOutcome.UNREPORTED:
            notes.append(f'{propagation.id}: delivered to {propagation.target_task_id} '
                         f'and returned no answer')
    return tuple(notes)


def current_result(snapshot, run_id):
    """The live candidate result version, or None."""
    return next((r for r in sorted((x for x in snapshot.values() if isinstance(x, Result)
                                    and x.run_id == run_id), key=lambda r: r.version, reverse=True)
                 if r.status == ResultStatus.CANDIDATE), None)


def result_versions(snapshot, run_id):
    return tuple(sorted((r for r in snapshot.values() if isinstance(r, Result) and r.run_id == run_id),
                        key=lambda r: r.version))
