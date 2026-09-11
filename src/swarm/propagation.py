"""Deterministic cross-pollination: eligibility, relevance, targeted delivery and retraction.

No model participates in routing. Nothing here creates knowledge: a propagation *consumes*
the Stage-5 validated projection and carries a bounded insight to a finite, named set of
tasks. There is no broadcast recipient, and an unvalidated claim is never propagated as
knowledge.

Together with ``review.review_task`` this module is the only cross-scope authority in the
system: ``propagation_records`` is the sole writer of ``Propagation``, and
``reconsideration_task``/``follow_up_task`` are the sole writers of
``Task.source_propagation_id``. A worker envelope reaches none of them.
"""
import json
from dataclasses import dataclass, replace
from .context import digest
from .domain import (AgentGroup, Conflict, ConflictStatus, Cycle, CycleStatus, Finding,
                     FindingStatus, GroupStatus, Propagation, PropagationKind, PropagationStatus,
                     ReconsiderationOutcome, Run, SwarmState, Task, TaskRequest, TaskStatus,
                     transition)
from .events import EventDraft, EventType
from .knowledge import duplicate_groups
from .policies import FINAL_REVIEW_KIND, SYNTHESIS_KIND, remaining_seconds, review_kind, stopped
from .review import dependency_closure

MAX_INSIGHT = 800
"""Compact discoveries, never transcripts."""

DEPENDENCY_SCORE, CRITERION_SCORE, TAG_SCORE, TAG_CAP = 4, 2, 1, 2
MIN_SCORE, MAX_TARGETS = 2, 3
LIVE_TARGET_STATUSES = (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING,
                        TaskStatus.COMPLETED)
CARRIED = (PropagationStatus.SELECTED, PropagationStatus.DELIVERED, PropagationStatus.CONSUMED)
RECEIVED = (PropagationStatus.DELIVERED, PropagationStatus.CONSUMED)
RECONSIDERATION_KIND, FOLLOW_UP_KIND = 'reconsideration', 'follow_up'
FOLLOW_UP_KINDS = (RECONSIDERATION_KIND, FOLLOW_UP_KIND)


@dataclass(frozen=True)
class PropagationPolicy:
    """Replaceable relevance policy. A semantic router replaces this without touching the
    propagation record, its delivery key or any consumer."""
    min_score: int = MIN_SCORE
    max_targets: int = MAX_TARGETS
    max_insight: int = MAX_INSIGHT
    priority: int = 1
    """Above exploration, below review: integrity work outranks propagation-driven work."""


def bounded(text, limit=MAX_INSIGHT):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def delivery_key(kind, knowledge_key, knowledge_revision, target_task_id):
    """Canonical idempotency key. Stored uniqueness, not best-effort querying."""
    return digest({'kind': str(kind), 'knowledge': knowledge_key,
                   'revision': knowledge_revision, 'target': target_task_id})


# --- eligibility ----------------------------------------------------------------

@dataclass(frozen=True)
class KnowledgeUnit:
    """One propagatable fact, identified independently of which duplicate is canonical."""
    kind: PropagationKind
    knowledge_key: str
    knowledge_revision: int
    canonical_id: str
    member_ids: tuple[str, ...]
    source_task_ids: tuple[str, ...]
    source_group_ids: tuple[str | None, ...]
    criterion_ids: tuple[str, ...]
    tags: tuple[str, ...]
    insight: str
    conflict_id: str | None = None


def _dependencies_valid(snapshot, finding):
    closure = dependency_closure(snapshot, finding)
    return all(isinstance(snapshot.get(i), Finding)
               and snapshot[i].status == FindingStatus.VALIDATED for i in closure)


def _sources(snapshot, member_ids):
    tasks = [snapshot[snapshot[i].task_id] for i in member_ids if isinstance(snapshot.get(i), Finding)
             and isinstance(snapshot.get(snapshot[i].task_id), Task)]
    return (tuple(sorted({t.id for t in tasks})), tuple(sorted({t.group_id for t in tasks}, key=str)))


def knowledge_units(snapshot, run_id, policy=PropagationPolicy()):
    """Facts eligible to propagate, in deterministic order.

    Eligibility is: currently VALIDATED, transitively valid dependencies, and present in the
    shared-state projection — so exactly one member of a duplicate group is offered. A
    finding contested by an open conflict is never offered as uncontested knowledge; the
    conflict itself propagates instead.
    """
    state = next((r for r in snapshot.values() if isinstance(r, SwarmState) and r.run_id == run_id), None)
    if state is None:
        return ()
    projected = set(state.validated_findings)
    conflicts = sorted((c for c in snapshot.values() if isinstance(c, Conflict)
                        and c.run_id == run_id and c.status == ConflictStatus.OPEN), key=lambda c: c.id)
    contested = {i for c in conflicts for i in c.finding_ids}
    units = []
    for conflict in conflicts:
        participants = [snapshot[i] for i in conflict.finding_ids if isinstance(snapshot.get(i), Finding)]
        validated = [f for f in participants if f.status == FindingStatus.VALIDATED
                     and _dependencies_valid(snapshot, f)]
        if not validated:
            continue
        sources = _sources(snapshot, tuple(f.id for f in participants))
        units.append(KnowledgeUnit(
            PropagationKind.CONFLICT, conflict.signature, conflict.revision, min(f.id for f in validated),
            tuple(sorted(f.id for f in participants)), sources[0], sources[1],
            tuple(sorted({c for f in participants for c in f.criterion_ids})),
            tuple(sorted({t for f in participants for t in f.tags})),
            bounded(f'OPEN CONFLICT {conflict.id} ({conflict.kind}): {conflict.reason}. Contested claims: '
                    + '; '.join(f'{f.id}@{f.revision} {f.claim}' for f in participants), policy.max_insight),
            conflict.id))
    for group in duplicate_groups(snapshot, run_id):
        canonical = snapshot.get(group.canonical_id)
        if (not isinstance(canonical, Finding) or canonical.id not in projected
                or canonical.status != FindingStatus.VALIDATED or canonical.id in contested
                or not _dependencies_valid(snapshot, canonical)):
            continue
        members = tuple(i for i in group.member_ids if isinstance(snapshot.get(i), Finding)
                        and snapshot[i].status == FindingStatus.VALIDATED)
        sources = _sources(snapshot, members)
        units.append(KnowledgeUnit(
            PropagationKind.INSIGHT, digest([group.claim, group.signature]), canonical.revision,
            canonical.id, members, sources[0], sources[1],
            tuple(sorted({c for i in members for c in snapshot[i].criterion_ids})),
            tuple(sorted({t for i in members for t in snapshot[i].tags})),
            bounded(f'VALIDATED {canonical.id}@{canonical.revision}: {canonical.claim}', policy.max_insight)))
    return tuple(units)


# --- relevance ------------------------------------------------------------------

def relevance(unit, task):
    """Deterministic score plus the exact features that produced it."""
    score, features = 0, []
    dependencies = sorted(set(unit.source_task_ids) & set(task.dependency_ids))
    pinned = sorted(set(unit.member_ids) & set(task.required_finding_ids + task.candidate_finding_ids))
    if dependencies or pinned:
        score += DEPENDENCY_SCORE
        features.append('DEPENDENCY:' + ','.join(dependencies + pinned))
    criteria = sorted(set(unit.criterion_ids) & set(task.acceptance_criterion_ids))
    if criteria:
        score += CRITERION_SCORE
        features.append('CRITERION:' + ','.join(criteria))
    tags = sorted(set(unit.tags) & set(task.tags))
    if tags:
        score += min(len(tags), TAG_CAP) * TAG_SCORE
        features.append('TAG:' + ','.join(tags[:TAG_CAP]))
    return score, tuple(features)


def _target_open(task, snapshot):
    group = snapshot.get(task.group_id) if task.group_id else None
    if task.group_id and (not isinstance(group, AgentGroup) or group.status != GroupStatus.ACTIVE):
        return False
    # A completed task can only reconsider inside a branch that is still open for work.
    return task.status != TaskStatus.COMPLETED or isinstance(group, AgentGroup)


def _already_carries(unit, task, snapshot):
    """Work authored to consume this very fact is not a target for it again.

    Without this a reconsideration task, which inherits its target's criteria, would score
    against the knowledge that created it and fan out one discovery indefinitely.
    """
    origin = snapshot.get(task.source_propagation_id) if task.source_propagation_id else None
    return isinstance(origin, Propagation) and origin.knowledge_key == unit.knowledge_key


def candidate_targets(unit, snapshot, run_id):
    """Active, in-run, non-review tasks this unit may legitimately reach.

    Completion work is excluded: a synthesis or final-review assignment reads exactly the
    knowledge the controller selected for it, so routing a discovery into one would be a
    second, unaudited path into the answer.
    """
    return [task for task in sorted((r for r in snapshot.values() if isinstance(r, Task)), key=lambda t: t.id)
            if task.run_id == run_id and task.status in LIVE_TARGET_STATUSES
            and review_kind(task) is None and task.kind not in (SYNTHESIS_KIND, FINAL_REVIEW_KIND)
            and _target_open(task, snapshot) and not _already_carries(unit, task, snapshot)]


@dataclass(frozen=True)
class PropagationDecision:
    unit: KnowledgeUnit
    target_task_id: str
    target_group_id: str | None
    score: int
    matched_features: tuple[str, ...]
    reason: str
    delivery_key: str


def select_targets(unit, snapshot, run_id, policy=PropagationPolicy()):
    """The replaceable routing interface: one fact in, a bounded set of targets out.

    Cross-pollination goes outside the source branch; a same-branch task qualifies only
    through an explicit declared dependency, which is local routing rather than fan-out.
    """
    scored = []
    for task in candidate_targets(unit, snapshot, run_id):
        score, features = relevance(unit, task)
        same_branch = task.group_id in unit.source_group_ids
        if same_branch and not any(f.startswith('DEPENDENCY:') for f in features):
            continue
        if score < policy.min_score:
            continue
        scored.append((-score, -task.priority, task.id, task, score, features))
    decisions = []
    for _, _, _, task, score, features in sorted(scored)[:policy.max_targets]:
        decisions.append(PropagationDecision(
            unit, task.id, task.group_id, score, features,
            f'score {score} from ' + '; '.join(features),
            delivery_key(unit.kind, unit.knowledge_key, unit.knowledge_revision, task.id)))
    return tuple(decisions)


def plan_propagations(snapshot, run_id, policy=PropagationPolicy()):
    """Undelivered decisions only. The delivery key makes repeated planning idempotent."""
    run = snapshot.get(run_id)
    if not isinstance(run, Run) or stopped(run) or remaining_seconds(run) <= 0:
        return ()
    existing = {p.delivery_key for p in snapshot.values() if isinstance(p, Propagation)}
    plans = []
    for unit in knowledge_units(snapshot, run_id, policy):
        for decision in select_targets(unit, snapshot, run_id, policy):
            if decision.delivery_key not in existing:
                existing.add(decision.delivery_key)
                plans.append(decision)
    return tuple(plans)


# --- records --------------------------------------------------------------------

def _event(kind, propagation, **detail):
    return EventDraft(type=kind, record_id=propagation.id, record_revision=propagation.revision,
                      task_id=propagation.target_task_id, group_id=propagation.target_group_id,
                      correlation_id=propagation.delivery_key,
                      detail_json=json.dumps({'kind': str(propagation.kind),
                                              'knowledge_key': propagation.knowledge_key,
                                              'knowledge_revision': propagation.knowledge_revision,
                                              'canonical_finding_id': propagation.canonical_finding_id,
                                              'source_finding_ids': list(propagation.source_finding_ids),
                                              'target_task_id': propagation.target_task_id,
                                              'score': propagation.score,
                                              'matched_features': list(propagation.matched_features),
                                              'state_revision': propagation.state_revision,
                                              'cycle': propagation.cycle, **detail}))


def propagation_records(decisions, identity, run_id, state_revision, cycle):
    """The only writer of ``Propagation``. Returns records with their selection events."""
    records, events = [], []
    for decision in decisions:
        unit = decision.unit
        record = Propagation(id=identity('propagation'), run_id=run_id, kind=unit.kind,
            knowledge_key=unit.knowledge_key, knowledge_revision=unit.knowledge_revision,
            canonical_finding_id=unit.canonical_id, source_finding_ids=unit.member_ids,
            target_task_id=decision.target_task_id, target_group_id=decision.target_group_id,
            delivery_key=decision.delivery_key, score=decision.score,
            matched_features=decision.matched_features, insight=unit.insight,
            reason=decision.reason, state_revision=state_revision, cycle=cycle,
            conflict_id=unit.conflict_id)
        records.append(record)
        events.append(_event(EventType.PROPAGATION_SELECTED, record, reason=record.reason))
        events.append(_event(EventType.CROSS_POLLINATION, record, insight=record.insight))
    return records, events


def deliverable(propagation, snapshot):
    """A running assignment's snapshot is never mutated: delivery waits for it to finish."""
    task = snapshot.get(propagation.target_task_id)
    if not isinstance(task, Task) or not _target_open(task, snapshot):
        return False
    if propagation.reconsideration_task_id:
        carrier = snapshot.get(propagation.reconsideration_task_id)
        return isinstance(carrier, Task) and carrier.status in (TaskStatus.PENDING, TaskStatus.READY)
    return task.status in (TaskStatus.PENDING, TaskStatus.READY)


def terminal_target(propagation, snapshot):
    """The target can never consume this delivery again."""
    task = snapshot.get(propagation.target_task_id)
    if not isinstance(task, Task):
        return 'TARGET_MISSING'
    if not _target_open(task, snapshot):
        return 'TARGET_BRANCH_CLOSED'
    if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        return 'TARGET_' + str(task.status)
    return None


def deliver(propagation):
    delivered = transition(propagation, PropagationStatus.DELIVERED)
    kind = (EventType.RETRACTION_DELIVERED if propagation.kind == PropagationKind.RETRACTION
            else EventType.PROPAGATION_DELIVERED)
    return delivered, _event(kind, delivered, insight=delivered.insight)


def skip(propagation, reason):
    skipped = replace(transition(propagation, PropagationStatus.SKIPPED), status_reason=reason)
    return skipped, _event(EventType.PROPAGATION_SKIPPED, skipped, reason=reason)


# --- retraction -----------------------------------------------------------------

def _still_carried(propagation, snapshot):
    if propagation.kind == PropagationKind.CONFLICT:
        conflict = snapshot.get(propagation.conflict_id)
        return isinstance(conflict, Conflict) and conflict.status == ConflictStatus.OPEN
    finding = snapshot.get(propagation.canonical_finding_id)
    return (isinstance(finding, Finding) and finding.status == FindingStatus.VALIDATED
            and finding.revision == propagation.knowledge_revision)


def retractions(snapshot, run_id, identity, cycle, reason='KNOWLEDGE_INVALIDATED'):
    """Targeted retraction for exactly the deliveries whose knowledge became ineligible.

    A propagation that was never delivered is closed silently — nothing received it. Only a
    recipient of *this* knowledge revision is told, so a newer valid revision delivered to
    the same target is untouched.
    """
    records, events = [], []
    for propagation in sorted((p for p in snapshot.values() if isinstance(p, Propagation)
                               and p.run_id == run_id and p.kind != PropagationKind.RETRACTION
                               and p.status in CARRIED), key=lambda p: p.id):
        if _still_carried(propagation, snapshot):
            continue
        retracted = replace(transition(propagation, PropagationStatus.RETRACTED), status_reason=reason)
        records.append(retracted)
        events.append(_event(EventType.PROPAGATION_RETRACTED, retracted, reason=reason))
        if propagation.status not in RECEIVED:
            continue
        finding = snapshot.get(propagation.canonical_finding_id)
        status = finding.status if isinstance(finding, Finding) else 'MISSING'
        key = delivery_key(PropagationKind.RETRACTION, propagation.delivery_key,
                           propagation.knowledge_revision, propagation.target_task_id)
        notice = Propagation(id=identity('propagation'), run_id=run_id,
            kind=PropagationKind.RETRACTION, knowledge_key=propagation.knowledge_key,
            knowledge_revision=propagation.knowledge_revision,
            canonical_finding_id=propagation.canonical_finding_id,
            source_finding_ids=propagation.source_finding_ids,
            target_task_id=propagation.target_task_id, target_group_id=propagation.target_group_id,
            delivery_key=key, score=propagation.score, matched_features=propagation.matched_features,
            insight=bounded(f'RETRACTED {propagation.canonical_finding_id}'
                            f'@{propagation.knowledge_revision} is now {status}: {reason}. '
                            f'It was delivered to {propagation.target_task_id} as {propagation.id}. '
                            f'Do not rely on it.'),
            reason=f'retracts {propagation.id}: {reason}', state_revision=propagation.state_revision,
            cycle=cycle, retracts_id=propagation.id)
        records.append(notice)
        events.append(_event(EventType.PROPAGATION_SELECTED, notice, reason=notice.reason))
    return records, events


# --- controller-authored reconsideration work -----------------------------------

def _equivalent_task(propagation, kind, snapshot):
    """Equivalent work already exists when the same knowledge already reached the same
    target as the same kind of task, whichever propagation carried it."""
    for task in snapshot.values():
        if not isinstance(task, Task) or task.kind != kind or not task.source_propagation_id:
            continue
        origin = snapshot.get(task.source_propagation_id)
        if (isinstance(origin, Propagation) and origin.knowledge_key == propagation.knowledge_key
                and origin.target_task_id == propagation.target_task_id):
            return True
    return False


def admissible_follow_up(propagation, kind, snapshot, run_id):
    """Bounded controller authority: current knowledge, live target, room in the graph."""
    run = snapshot.get(run_id)
    if not isinstance(run, Run) or stopped(run) or remaining_seconds(run) <= 0:
        return 'RUN_STOPPED'
    if propagation.kind != PropagationKind.RETRACTION and not _still_carried(propagation, snapshot):
        return 'KNOWLEDGE_NOT_CURRENT'
    target = snapshot.get(propagation.target_task_id)
    if not isinstance(target, Task) or not _target_open(target, snapshot):
        return 'TARGET_UNAVAILABLE'
    if sum(isinstance(r, (Task, TaskRequest)) for r in snapshot.values()) >= run.task_limit:
        return 'TASK_LIMIT'
    if run.provider_requests >= run.provider_request_limit:
        return 'BUDGET_EXHAUSTED'
    if _equivalent_task(propagation, kind, snapshot):
        return 'DUPLICATE_FOLLOW_UP'
    return None


def follow_up_task(propagation, kind, identity, run_id, snapshot, policy=PropagationPolicy()):
    """The only writer of ``Task.source_propagation_id``. Explicit parent, dependency and
    criteria; optional work, so required integrity work outranks it in budget and selection."""
    target = snapshot[propagation.target_task_id]
    finding = snapshot.get(propagation.canonical_finding_id)
    criteria = tuple(sorted(set(target.acceptance_criterion_ids)
                            & set(getattr(finding, 'criterion_ids', ()) or target.acceptance_criterion_ids)))
    verb = 'Reconsider' if kind == RECONSIDERATION_KIND else 'Investigate the follow-up for'
    detail = (propagation.outcome_reason if kind == FOLLOW_UP_KIND and propagation.outcome_reason
              else propagation.insight)
    return Task(id=identity('task'), run_id=run_id,
                objective=bounded(f'{verb} {target.id} in light of {propagation.id}'),
                description=bounded(f'{propagation.kind} {propagation.canonical_finding_id}'
                                    f'@{propagation.knowledge_revision}. {detail}', 2000),
                kind=kind, priority=policy.priority, group_id=target.group_id,
                parent_task_id=target.id, dependency_ids=(),
                acceptance_criterion_ids=criteria or target.acceptance_criterion_ids,
                required=False, required_tools=target.required_tools, tags=target.tags,
                source_propagation_id=propagation.id)


def link_task(propagation, task, kind):
    """Attach controller-authored work to the delivery that justified it."""
    field = 'reconsideration_task_id' if kind == RECONSIDERATION_KIND else 'follow_up_task_id'
    return replace(propagation, revision=propagation.revision + 1, **{field: task.id})


# --- reconsideration outcomes ---------------------------------------------------

def record_outcome(propagation, outcome, reason, assignment_id):
    """Consume one delivery. Silence is recorded as UNREPORTED, never as NO_CHANGE."""
    consumed = replace(transition(propagation, PropagationStatus.CONSUMED),
                       outcome=ReconsiderationOutcome(outcome),
                       outcome_reason=bounded(reason, 1000), outcome_assignment_id=assignment_id)
    return consumed, _event(EventType.RECONSIDERATION_COMPLETED, consumed,
                            outcome=str(consumed.outcome), outcome_reason=consumed.outcome_reason,
                            assignment_id=assignment_id)


def pending_follow_ups(snapshot, run_id):
    """Consumed deliveries whose FOLLOW_UP_REQUESTED has not yet been given a task."""
    return tuple(sorted((p for p in snapshot.values() if isinstance(p, Propagation)
                         and p.run_id == run_id and p.status == PropagationStatus.CONSUMED
                         and p.outcome == ReconsiderationOutcome.FOLLOW_UP_REQUESTED
                         and not p.follow_up_task_id), key=lambda p: p.id))


def undeliverable(snapshot, run_id):
    """Deliveries whose original target can no longer consume them, but whose branch is
    still open — the bounded post-completion reconsideration case."""
    return tuple(sorted((p for p in snapshot.values() if isinstance(p, Propagation)
                         and p.run_id == run_id and p.status == PropagationStatus.SELECTED
                         and not p.reconsideration_task_id
                         and not deliverable(p, snapshot) and terminal_target(p, snapshot) is None),
                        key=lambda p: p.id))


def for_task(snapshot, task):
    """Propagations this assignment must read, with whether it owes an outcome.

    A delivery is consumable by the task it was routed to, or by the reconsideration task
    the controller created to carry it. Work created *because* of a delivery still sees it,
    but its outcome is already recorded, so it is informational.
    """
    entries = []
    for propagation in sorted((p for p in snapshot.values() if isinstance(p, Propagation)
                               and p.run_id == task.run_id), key=lambda p: p.id):
        carrier = propagation.reconsideration_task_id or propagation.target_task_id
        if carrier == task.id and propagation.status == PropagationStatus.DELIVERED:
            entries.append((propagation, True))
        elif propagation.follow_up_task_id == task.id:
            entries.append((propagation, False))
    return tuple(sorted(entries, key=lambda e: (-e[0].score, e[0].id)))


def open_cycle(snapshot, run_id):
    return next((c for c in sorted((r for r in snapshot.values() if isinstance(r, Cycle)
                                    and r.run_id == run_id), key=lambda c: c.number, reverse=True)
                 if c.status == CycleStatus.OPEN), None)


def current_cycle(snapshot, run_id):
    cycle = open_cycle(snapshot, run_id)
    return cycle.number if cycle else getattr(snapshot.get(run_id), 'cycle', 0)
