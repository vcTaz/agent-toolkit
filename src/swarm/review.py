"""Controller-owned review work: what review is due, and what a returned review may become.

A FindingDraft never requests its own promotion. Review tasks are created by the
controller, executed through the ordinary scheduler, and admitted here, where a model's
decision is combined with — and can only be weakened by — the host verification policy.
"""
import json
from dataclasses import dataclass, replace
from .domain import (Evidence, Finding, FindingStatus, ReviewDecision, ReviewKind, ReviewRecord,
                     REVIEW_DECISIONS, Role, Task, TaskRequest, blocking_keys, transition)
from .events import EventDraft, EventType
from .knowledge import invalidate_closure
from .policies import REVIEW_ROLE_FOR, REVIEW_TASK_KINDS, review_kind
from .verification import VerificationDecision

TASK_KIND = {ReviewKind.CRITICISM: 'criticism', ReviewKind.VALIDATION: 'validation'}
UNAVAILABLE = (FindingStatus.REJECTED, FindingStatus.INVALIDATED, FindingStatus.SUPERSEDED)


@dataclass(frozen=True)
class ReviewPolicy:
    """Deterministic scheduling policy. Attempts are bounded so a finding that cannot be
    reviewed leaves a recorded gap instead of an endless queue."""
    attempts_per_kind: int = 1
    priority: int = 5
    group_id: str | None = None
    """Review work belongs to no exploration branch; its evidence is host-assigned."""


@dataclass(frozen=True)
class ReviewPlan:
    finding_id: str
    kind: ReviewKind
    task_kind: str
    objective: str
    criterion_ids: tuple[str, ...]
    required_finding_ids: tuple[str, ...]


def dependency_closure(snapshot, finding):
    """Transitive finding dependencies, deterministic and iterative."""
    order, pending, seen = [], sorted(finding.dependency_finding_ids), set()
    while pending:
        identity = pending.pop(0)
        if identity in seen:
            continue
        seen.add(identity)
        order.append(identity)
        dependency = snapshot.get(identity)
        if isinstance(dependency, Finding):
            pending += sorted(dependency.dependency_finding_ids)
    return tuple(order)


def due_kind(finding: Finding):
    if finding.status in (FindingStatus.PROPOSED, FindingStatus.INVALIDATED):
        return ReviewKind.CRITICISM
    return ReviewKind.VALIDATION if finding.status == FindingStatus.CRITIQUED else None


def plan_reviews(snapshot, run_id, policy=ReviewPolicy()):
    """Which review work the controller owes, in deterministic finding order."""
    run = snapshot[run_id]
    # A review kind whose role is not registered is not configured for this run; that is a
    # host configuration decision, distinct from having no *independent* agent available.
    enabled = {kind for kind, name in REVIEW_ROLE_FOR.items()
               if any(isinstance(r, Role) and r.name == name for r in snapshot.values())}
    tasks = [t for t in snapshot.values() if isinstance(t, Task) and t.run_id == run_id]
    scheduled = {}
    for task in tasks:
        if task.target_finding_id and task.kind in REVIEW_TASK_KINDS:
            scheduled[(task.target_finding_id, task.kind)] = scheduled.get((task.target_finding_id, task.kind), 0) + 1
    budget = run.task_limit - sum(isinstance(r, (Task, TaskRequest)) for r in snapshot.values())
    plans = []
    for finding in sorted((r for r in snapshot.values() if isinstance(r, Finding) and r.run_id == run_id),
                          key=lambda f: f.id):
        kind = due_kind(finding)
        if kind not in enabled or len(plans) >= max(0, budget):
            continue
        if scheduled.get((finding.id, TASK_KIND[kind]), 0) >= policy.attempts_per_kind:
            continue
        closure = dependency_closure(snapshot, finding)
        dependencies = [snapshot.get(i) for i in closure]
        if any(not isinstance(d, Finding) or d.status in UNAVAILABLE for d in dependencies):
            continue  # its support is gone; review waits rather than blessing a broken chain
        if kind == ReviewKind.VALIDATION and any(d.status != FindingStatus.VALIDATED for d in dependencies):
            continue  # a validated claim may not rest on an unvalidated one
        plans.append(ReviewPlan(finding.id, kind, TASK_KIND[kind],
                                f'{TASK_KIND[kind]} of {finding.id}',
                                finding.criterion_ids, (finding.id,) + closure))
    return tuple(plans)


def review_task(plan: ReviewPlan, identity, run_id, snapshot, policy=ReviewPolicy()):
    """Materialize one review Task. This is the only writer of ``target_finding_id``, which
    deliberately crosses group scope; no model-reachable path reaches it."""
    finding = snapshot[plan.finding_id]
    source = snapshot.get(finding.task_id)
    return Task(id=identity('task'), run_id=run_id, objective=plan.objective,
                description=f'Review {finding.id} at revision {finding.revision} on its exact claim.',
                kind=plan.task_kind, priority=policy.priority, group_id=policy.group_id,
                acceptance_criterion_ids=plan.criterion_ids,
                required_finding_ids=plan.required_finding_ids,
                # Host authorization for the supporting evidence, which may still be a
                # candidate: the controller states exactly what this review must read.
                candidate_finding_ids=plan.required_finding_ids[1:],
                target_finding_id=plan.finding_id, required=True,
                required_tools=getattr(source, 'required_tools', ()),
                tags=finding.tags)


# --- admission ------------------------------------------------------------------

def _model_evidence(result):
    return tuple(Evidence(kind='tool_result', value=r.value_json, reference=r.id, verified=False,
                          tool_name=r.tool_name, arguments_json=r.arguments_json)
                 for r in sorted(result.tool_results, key=lambda r: r.id) if r.success)


def _raised_blocking(snapshot, finding):
    return {key: review.id for review in sorted(
        (r for r in snapshot.values() if isinstance(r, ReviewRecord) and r.target_id == finding.id
         and r.kind == ReviewKind.CRITICISM), key=lambda r: r.id) for key in blocking_keys(review)}


def _settle(kind, model, host, finding, draft, snapshot):
    """Combine the reviewer's decision with the host verdict.

    A model PASS is necessary and never sufficient: the host can only lower the outcome.
    The returned reason is the recorded verification trail, including why a PASS was refused.
    """
    if kind == ReviewKind.CRITICISM:
        return model, ''
    trail = f'{host.decision}: {host.reason}'.strip(': ')
    if host.decision == 'FAIL' or model == ReviewDecision.FAIL:
        return ReviewDecision.FAIL, trail
    if model != ReviewDecision.PASS or host.decision != 'PASS':
        return ReviewDecision.INCONCLUSIVE, f'{trail}; MODEL_{model}'
    unresolved = sorted(set(_raised_blocking(snapshot, finding)) - set(draft.resolved_issues))
    if unresolved:
        return ReviewDecision.INCONCLUSIVE, f'{trail}; UNRESOLVED_BLOCKING_CRITIQUE: ' + ', '.join(unresolved)
    if any(snapshot[i].status != FindingStatus.VALIDATED for i in finding.dependency_finding_ids):
        return ReviewDecision.INCONCLUSIVE, f'{trail}; DEPENDENCY_NOT_VALIDATED'
    return ReviewDecision.PASS, trail


def admit_review(assignment, result, snapshot, identity, verification):
    """Turn one review envelope into a ReviewRecord plus the lifecycle it authorizes.

    Raises ``ValueError(reason)`` when the envelope is not an admissible review; the caller
    records the reason and fails the assignment without committing anything.
    """
    task = snapshot[assignment.task_id]
    kind = review_kind(task)
    draft = result.review
    if kind is None or draft is None:
        raise ValueError('REVIEW_MISSING')
    finding = snapshot.get(task.target_finding_id)
    if not isinstance(finding, Finding) or due_kind(finding) != kind:
        raise ValueError('REVIEW_TARGET_INELIGIBLE')
    if draft.target_id != finding.id or draft.target_revision != finding.revision:
        raise ValueError('REVIEW_TARGET_REVISION_MISMATCH')
    model = ReviewDecision(draft.decision)
    if model not in REVIEW_DECISIONS[kind]:
        raise ValueError('REVIEW_DECISION_NOT_ADMISSIBLE')
    review = _record(assignment, result, finding, kind, model, identity, verification, snapshot)
    decision = review.decision
    records, events = [review], [EventDraft(type=EventType.REVIEW_COMPLETED, record_id=review.id,
        record_revision=review.revision, assignment_id=assignment.id, task_id=task.id,
        agent_id=assignment.agent_id, correlation_id=assignment.id,
        detail_json=json.dumps({'target_id': finding.id, 'target_revision': finding.revision,
                                'kind': str(kind), 'model_decision': str(model),
                                'decision': str(decision), 'verification': review.verification,
                                'blocking_issues': list(draft.blocking_issues),
                                'resolved_issues': list(review.resolved_issues)}))]
    changed, event_types, outcome, detail = _apply(finding, review, decision, kind)
    records.append(changed)
    events += [EventDraft(type=event_type, record_id=changed.id, record_revision=changed.revision,
                          assignment_id=assignment.id, task_id=task.id, correlation_id=assignment.id,
                          detail_json=json.dumps(detail)) for event_type in event_types]
    if outcome == FindingStatus.REJECTED:
        cascade, cascade_events = invalidate_closure(snapshot, assignment.run_id, finding.id,
                                                     'SUPPORTING_CLAIM_REJECTED')
        records += cascade
        events += cascade_events
    return records, events, review


def _record(assignment, result, finding, kind, model, identity, verification, snapshot):
    """Build the immutable review. Verified evidence comes only from the host verifier."""
    draft, evidence = result.review, _model_evidence(result)
    host = (verification.verify(finding, snapshot, evidence) if kind == ReviewKind.VALIDATION
            else VerificationDecision('INCONCLUSIVE', 'NOT_A_VERIFICATION'))
    decision, reason = _settle(kind, model, host, finding, draft, snapshot)
    raised = _raised_blocking(snapshot, finding)
    return ReviewRecord(id=identity('review'), run_id=assignment.run_id,
        assignment_id=assignment.id, target_id=finding.id, target_revision=finding.revision,
        kind=kind, decision=decision,
        evidence=(host.evidence if decision == ReviewDecision.PASS else ()) + evidence,
        checks=draft.checks, blocking_issues=draft.blocking_issues,
        nonblocking_issues=draft.nonblocking_issues,
        resolved_issues=tuple(i for i in draft.resolved_issues if i in raised),
        summary=draft.summary, verification=reason)


def _apply(finding, review, decision, kind):
    """Exact-revision lifecycle for the reviewed finding. Review history is append-only.

    Promotion is one record change committed with the review that authorized it, so the
    finding and the shared-state projection can never disagree.
    """
    detail = {'review_id': review.id, 'decision': str(decision), 'revision': finding.revision + 1,
              'target_revision': finding.revision, 'verification': review.verification}
    if kind == ReviewKind.CRITICISM:
        if decision == ReviewDecision.INCONCLUSIVE:
            return _append(finding, review), (EventType.REVIEW_REJECTED,), None, detail
        return (replace(transition(finding, FindingStatus.CRITIQUED),
                        review_ids=finding.review_ids + (review.id,)),
                (EventType.FINDING_CRITIQUED,), FindingStatus.CRITIQUED, detail)
    if decision == ReviewDecision.PASS:
        return (transition(finding, FindingStatus.VALIDATED, review=review),
                (EventType.FINDING_VALIDATED, EventType.KNOWLEDGE_PROMOTED),
                FindingStatus.VALIDATED, detail)
    if decision == ReviewDecision.FAIL:
        return (replace(transition(finding, FindingStatus.REJECTED),
                        review_ids=finding.review_ids + (review.id,)),
                (EventType.FINDING_REJECTED,), FindingStatus.REJECTED, detail)
    return _append(finding, review), (EventType.REVIEW_REJECTED,), None, detail


def _append(finding, review):
    """Record an inconclusive review without changing status; the revision still moves, so
    any assignment pinned to the older revision is now stale."""
    return replace(finding, review_ids=finding.review_ids + (review.id,), revision=finding.revision + 1)
