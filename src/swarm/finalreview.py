"""Independent final review of one exact result version, and what its verdict authorizes.

The reviewer proposes a verdict. It cannot mutate a Finding, a Run or a Result: the record
it produces is written by the host, its independence is decided before a provider request is
spent, and its PASS is re-checked against current state before anything completes.

The controller — not the reviewer — decides whether a REVISE means "say it better" or "go
and get evidence", because only the controller can tell the difference from the record.
"""
import json
from dataclasses import dataclass, replace
from .completion import gap_records, repair_admissible, repair_key
from .domain import (Conflict, ConflictStatus, Evidence, Finding, FindingStatus, GateStatus, Result,
                     ResultStatus, RevisionKind, ReviewDecision, ReviewKind, ReviewRecord,
                     REVIEW_DECISIONS, Task, transition)
from .events import EventDraft, EventType
from .policies import FINAL_REVIEW_KIND, REPAIR_KIND, review_kind
from .propagation import bounded

UNAVAILABLE = (FindingStatus.REJECTED, FindingStatus.INVALIDATED, FindingStatus.SUPERSEDED)


def final_review_task(result, identity, run_id, snapshot, *, priority=9):
    """The only writer of ``Task.target_result_id``. No model-reachable path reaches it."""
    run = snapshot[run_id]
    return Task(id=identity('task'), run_id=run_id,
                objective=f'final review of result version {result.version}',
                description=bounded(f'Review result {result.id} at revision {result.revision} '
                                    f'against the acceptance criteria and the findings it cites.',
                                    2000),
                kind=FINAL_REVIEW_KIND, priority=priority, group_id=None,
                acceptance_criterion_ids=tuple(c.id for c in run.acceptance_criteria),
                required_finding_ids=result.finding_ids, candidate_finding_ids=(),
                target_result_id=result.id, source_result_id=result.id, required=True,
                required_tools=())


def started_event(task, result, assignment=None):
    return EventDraft(type=EventType.FINAL_REVIEW_STARTED, task_id=task.id,
                      assignment_id=getattr(assignment, 'id', None),
                      agent_id=getattr(assignment, 'agent_id', None), correlation_id=result.id,
                      detail_json=json.dumps({'phase': 'DISPATCHED' if assignment else 'AUTHORIZED',
                                              'result_id': result.id, 'version': result.version,
                                              'result_revision': result.revision,
                                              'finding_ids': list(result.finding_ids)}))


# --- staleness -------------------------------------------------------------------

def stale_reasons(assignment, snapshot):
    """Why a returned final review may not authorize completion.

    Everything the assignment pinned is re-checked: the exact result version, every
    supporting finding revision, and any conflict that opened over that support while the
    review ran. A stale review is recorded, never merged.
    """
    reasons = []
    result = snapshot.get(assignment.result_id) if assignment.result_id else None
    if not isinstance(result, Result):
        reasons.append('RESULT_MISSING')
    else:
        if result.revision != assignment.result_revision:
            reasons.append(f'RESULT_VERSION_CHANGED: {assignment.result_revision}->{result.revision}')
        if result.status != ResultStatus.CANDIDATE:
            reasons.append(f'RESULT_{result.status}')
        for identity, revision in zip(result.finding_ids, result.finding_revisions):
            finding = snapshot.get(identity)
            if not isinstance(finding, Finding):
                reasons.append(f'SUPPORT_MISSING: {identity}')
            elif finding.status in UNAVAILABLE:
                reasons.append(f'SUPPORT_{finding.status}: {identity}')
            elif finding.revision != revision:
                reasons.append(f'SUPPORT_REVISION_CHANGED: {identity}@{revision}->{finding.revision}')
        cited = set(result.finding_ids)
        for conflict in sorted((c for c in snapshot.values() if isinstance(c, Conflict)
                                and c.run_id == assignment.run_id
                                and c.status == ConflictStatus.OPEN), key=lambda c: c.id):
            if set(conflict.finding_ids) & cited:
                reasons.append(f'CONFLICT_OPENED: {conflict.id}')
    run = snapshot[assignment.run_id]
    criteria = {c.id for c in run.acceptance_criteria}
    if not set(assignment.criterion_ids) <= criteria:
        reasons.append('CRITERION_CHANGED')
    return tuple(reasons)


# --- admission -------------------------------------------------------------------

def _evidence(result):
    return tuple(Evidence(kind='tool_result', value=r.value_json, reference=r.id, verified=False,
                          tool_name=r.tool_name, arguments_json=r.arguments_json)
                 for r in sorted(result.tool_results, key=lambda r: r.id) if r.success)


def admit_final_review(assignment, result, snapshot, identity):
    """Turn one final-review envelope into an immutable ``ReviewRecord`` on the result.

    The record is written whatever the verdict, including for a stale review: the run must
    be able to say that a review happened and why it could not authorize completion.
    """
    task = snapshot[assignment.task_id]
    draft = result.review
    if review_kind(task) != ReviewKind.FINAL or draft is None:
        raise ValueError('FINAL_REVIEW_MISSING')
    version = snapshot.get(task.target_result_id)
    if not isinstance(version, Result) or version.run_id != assignment.run_id:
        raise ValueError('FINAL_REVIEW_TARGET_MISSING')
    if draft.target_id != version.id or draft.target_revision != assignment.result_revision:
        raise ValueError('FINAL_REVIEW_TARGET_MISMATCH')
    decision = ReviewDecision(draft.decision)
    if decision not in REVIEW_DECISIONS[ReviewKind.FINAL]:
        raise ValueError('FINAL_REVIEW_DECISION_NOT_ADMISSIBLE')
    criteria = {c.id for c in snapshot[assignment.run_id].acceptance_criteria}
    if not set(draft.criterion_ids) <= criteria:
        raise ValueError('FINAL_REVIEW_UNKNOWN_CRITERION')
    stale = stale_reasons(assignment, snapshot)
    record = ReviewRecord(id=identity('review'), run_id=assignment.run_id,
                          assignment_id=assignment.id, target_id=version.id,
                          target_revision=assignment.result_revision, kind=ReviewKind.FINAL,
                          decision=decision, evidence=_evidence(result), checks=draft.checks,
                          blocking_issues=draft.blocking_issues,
                          nonblocking_issues=draft.nonblocking_issues,
                          criterion_ids=draft.criterion_ids,
                          unsupported_claims=draft.unsupported_claims, summary=draft.summary,
                          verification='STALE: ' + '; '.join(stale) if stale else 'CURRENT')
    events = [EventDraft(type=EventType.FINAL_REVIEW_COMPLETED, record_id=record.id,
                         record_revision=record.revision, assignment_id=assignment.id,
                         task_id=task.id, agent_id=assignment.agent_id, correlation_id=version.id,
                         causation_id=assignment.id,
                         detail_json=json.dumps({'result_id': version.id, 'version': version.version,
                                                 'decision': str(decision),
                                                 'criterion_ids': list(draft.criterion_ids),
                                                 'unsupported_claims': list(draft.unsupported_claims),
                                                 'blocking_issues': list(draft.blocking_issues),
                                                 'nonblocking_issues': list(draft.nonblocking_issues),
                                                 'stale': list(stale)}))]
    if stale:
        events.append(EventDraft(type=EventType.FINAL_REVIEW_STALE, correlation_id=version.id,
                                 causation_id=assignment.id, task_id=task.id,
                                 detail_json=json.dumps({'result_id': version.id,
                                                         'review_id': record.id,
                                                         'reasons': list(stale)})))
    return [record], events, record


# --- verdict semantics -----------------------------------------------------------

def _located(gaps, named_criteria):
    """The gaps repair work can address: the gate's own, plus the criteria the review named.

    A reviewer that says "this claim is unsupported" without naming a criterion has located
    nothing the controller can author work against; one that names a criterion has.
    """
    from .domain import Gap
    keys = {gap.key for gap in gaps}
    located = list(gaps)
    for criterion in named_criteria:
        gap = Gap(criterion_id=criterion, reason='UNSUPPORTED')
        if gap.key not in keys:
            keys.add(gap.key)
            located.append(gap)
    return tuple(located)


@dataclass(frozen=True)
class Verdict:
    """What the controller concluded from one final review plus current state."""
    decision: ReviewDecision
    revision_kind: RevisionKind
    reasons: tuple[str, ...]
    stale: tuple[str, ...]
    gaps: tuple = ()

    def detail(self):
        return {'decision': str(self.decision), 'revision_kind': str(self.revision_kind),
                'reasons': list(self.reasons), 'stale': list(self.stale),
                'gaps': [g.key for g in self.gaps]}


def classify(review, result, snapshot, run_id, gate):
    """Decide what a non-PASS verdict — or a stale PASS — actually requires.

    The reviewer's issues locate the defect; the classification comes from the record. A
    revision is presentation-only exactly when current knowledge already supports every
    required criterion and every citation is still valid, so nothing new has to be learned.
    Anything else is an evidence defect, and synthesis prose cannot repair it.
    """
    named_criteria, unsupported_claims = review.criterion_ids, review.unsupported_claims
    stale = () if review.verification == 'CURRENT' else tuple(
        review.verification.removeprefix('STALE: ').split('; '))
    reasons = []
    required = gap_records(snapshot, run_id, gate.readiness)
    blocking = tuple(g for g in required if g.required)
    if stale:
        reasons.append('STALE_REVIEW')
    if gate.status != GateStatus.READY:
        reasons.append(f'GATE_{gate.status}')
        return Verdict(review.decision, RevisionKind.EVIDENCE, tuple(reasons), stale, blocking)
    for identity, revision in zip(result.finding_ids, result.finding_revisions):
        finding = snapshot.get(identity)
        if not isinstance(finding, Finding) or finding.status != FindingStatus.VALIDATED \
                or finding.revision != revision:
            reasons.append(f'CITATION_INVALID: {identity}')
    if reasons:
        return Verdict(review.decision, RevisionKind.EVIDENCE, tuple(reasons), stale, blocking)
    covered = {entry.criterion_id for entry in result.coverage if entry.finding_ids}
    knowledge = {entry.criterion_id for entry in gate.readiness if entry.clean}
    for criterion in named_criteria:
        if criterion in knowledge and criterion not in covered:
            # The knowledge exists and the result simply failed to present it.
            reasons.append(f'OMITTED_SUPPORTED_CRITERION: {criterion}')
        elif criterion not in knowledge:
            reasons.append(f'UNCOVERED_CRITERION: {criterion}')
            return Verdict(review.decision, RevisionKind.EVIDENCE, tuple(reasons), stale,
                           _located(blocking, named_criteria))
    if unsupported_claims:
        reasons.append('UNSUPPORTED_CLAIMS: ' + '; '.join(unsupported_claims[:4]))
        return Verdict(review.decision, RevisionKind.EVIDENCE, tuple(reasons), stale,
                       _located(blocking, named_criteria))
    if not reasons:
        if not (review.blocking_issues or named_criteria or unsupported_claims):
            # The reviewer disagreed but pointed at nothing the record confirms. Prose
            # cannot repair that, and neither can more evidence.
            return Verdict(review.decision, RevisionKind.NONE, ('NO_CONFIRMED_DEFECT',),
                           stale, blocking)
        reasons.append('PRESENTATION_ONLY')
    return Verdict(review.decision, RevisionKind.PRESENTATION, tuple(reasons), stale, blocking)


def pass_blockers(result, snapshot, run_id, gate, stale=()):
    """Why a reviewer PASS may still not complete the run. Empty means it may."""
    reasons = list(stale)
    if gate.status != GateStatus.READY:
        reasons.append(f'GATE_{gate.status}')
        reasons += list(gate.reasons)
    for identity, revision in zip(result.finding_ids, result.finding_revisions):
        finding = snapshot.get(identity)
        if not isinstance(finding, Finding):
            reasons.append(f'SUPPORT_MISSING: {identity}')
        elif finding.status != FindingStatus.VALIDATED:
            reasons.append(f'SUPPORT_{finding.status}: {identity}')
        elif finding.revision != revision:
            reasons.append(f'SUPPORT_REVISION_CHANGED: {identity}')
    for entry in result.coverage:
        if entry.required and not entry.finding_ids:
            reasons.append(f'REQUIRED_CRITERION_UNSUPPORTED: {entry.criterion_id}')
    declared = {entry.criterion_id for entry in result.coverage if entry.finding_ids}
    for entry in gate.readiness:
        if entry.required and entry.criterion_id not in declared:
            reasons.append(f'REQUIRED_CRITERION_NOT_IN_RESULT: {entry.criterion_id}')
    return tuple(dict.fromkeys(reasons))


# --- repair work -----------------------------------------------------------------

def repair_task(gap, review, identity, run_id, snapshot, *, priority=6, round_number=1):
    """The only writer of a repair task.

    A repair request is controller-authored and fully bounded: it names the exact review and
    result that triggered it, the criterion and gap it must close, its round number, and a
    duplicate-suppression key. It is not generic worker ``TaskRequest`` adoption, which
    stays closed.
    """
    key = repair_key(gap, getattr(review, 'id', None))
    target = snapshot.get(getattr(review, 'target_id', None))
    return Task(id=identity('task'), run_id=run_id,
                objective=bounded(f'repair the support for {gap.criterion_id} ({gap.reason})'),
                description=bounded(f'{key} | round {round_number}. Establish tool-backed evidence '
                                    f'for criterion {gap.criterion_id}. Gap: {gap.reason}. '
                                    f'Current support: {", ".join(gap.supporting_ids) or "none"}.',
                                    2000),
                kind=REPAIR_KIND, priority=priority, group_id=None,
                acceptance_criterion_ids=(gap.criterion_id,), required_finding_ids=(),
                candidate_finding_ids=(), required=True,
                required_tools=_verifier_tools(snapshot, run_id, gap.criterion_id),
                source_review_id=getattr(review, 'id', None),
                source_result_id=getattr(target, 'id', None), outcome=key)


def _verifier_tools(snapshot, run_id, criterion_id):
    """A repair task must be able to produce the evidence its criterion's verifier needs."""
    criterion = next((c for c in snapshot[run_id].acceptance_criteria if c.id == criterion_id), None)
    return (criterion.verifier_kind,) if criterion and criterion.verifier_kind != 'tool' else ()


def plan_repairs(verdict, review, snapshot, run_id, gate):
    """Which repair tasks are admissible for this verdict, with the refusal reason for the rest."""
    admitted, refused = [], []
    for gap in verdict.gaps or gate.repairable:
        decision = repair_admissible(snapshot, run_id, gap, getattr(review, 'id', None))
        (admitted if decision.admissible else refused).append((gap, decision))
    return tuple(admitted), tuple(refused)


def judged(result, status, review, revision_kind):
    """Record the verdict on the exact version that was reviewed; never edit it in place."""
    return replace(transition(result, status), review_id=review.id, decision=review.decision,
                   revision_kind=revision_kind)
