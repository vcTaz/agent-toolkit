"""Controller-authored synthesis work and the admission of one proposed answer.

A synthesizer is an ordinary assignment on the ordinary execution seam. What makes it safe
is what it is *given* and what is done with what it returns: the controller selects the
validated support, pins every revision of it, and re-checks that support against current
state before a ``Result`` version exists. The model proposes an answer; it never marks the
run complete, never cites knowledge it was not given, and never introduces a claim no
supplied finding carries.
"""
import json
from dataclasses import replace
from .completion import current_result, limitations, support_findings
from .domain import (Finding, FindingStatus, Result, ResultClaim, ResultCoverage, ResultStatus,
                     Task, TaskStatus, now)
from .events import EventDraft, EventType
from .policies import SYNTHESIS_KIND
from .propagation import bounded

MAX_ANSWER = 8000
MAX_CLAIMS = 24
UNAVAILABLE = (FindingStatus.REJECTED, FindingStatus.INVALIDATED, FindingStatus.SUPERSEDED)


def synthesis_task(identity, run_id, snapshot, gate, *, priority=8, source_review_id=None,
                   source_result_id=None, feedback=()):
    """The only writer of a synthesis task. Support is chosen here, not by the synthesizer.

    ``required_finding_ids`` is the deliberate selection: the ContextBuilder pins exactly
    that closure with its evidence, admits no candidates, and refuses outright if any
    member has become unavailable — so an invalidated claim cannot reach the answer.
    """
    run = snapshot[run_id]
    criteria = tuple(c.id for c in run.acceptance_criteria)
    caveats = limitations(snapshot, run_id, gate.readiness) + tuple(feedback)
    description = ('Compose the final answer for this run from the supplied validated findings. '
                   'Cite finding ids for every criterion and every material claim.')
    if source_review_id:
        description += f' Revising result {source_result_id} after final review {source_review_id}.'
    return Task(id=identity('task'), run_id=run_id, objective=f'synthesize the result for {run_id}',
                description=bounded(description, 2000), kind=SYNTHESIS_KIND, priority=priority,
                group_id=None, acceptance_criterion_ids=criteria,
                required_finding_ids=gate.support, candidate_finding_ids=(),
                limitations=tuple(bounded(note, 1000) for note in caveats)[:12],
                source_result_id=source_result_id, source_review_id=source_review_id,
                required=True, required_tools=())


def started_event(task, gate, attempt):
    return EventDraft(type=EventType.SYNTHESIS_STARTED, task_id=task.id, correlation_id=task.id,
                      detail_json=json.dumps({'phase': 'AUTHORIZED', 'task_id': task.id,
                                              'attempt': attempt,
                                              'support': list(gate.support),
                                              'criterion_ids': list(task.acceptance_criterion_ids),
                                              'limitations': list(task.limitations),
                                              'source_result_id': task.source_result_id,
                                              'source_review_id': task.source_review_id}))


# --- admission -------------------------------------------------------------------

def stale_support(assignment, snapshot):
    """Support that moved while the synthesis executed, using Stage-4 dependency staleness.

    There is no global run-revision rule here: only the exact records this assignment
    pinned can make its output stale.
    """
    reasons = []
    for identity, revision in zip(assignment.input_finding_ids, assignment.input_finding_revisions):
        finding = snapshot.get(identity)
        if not isinstance(finding, Finding):
            reasons.append(f'SUPPORT_MISSING: {identity}')
        elif finding.revision != revision:
            reasons.append(f'SUPPORT_REVISION_CHANGED: {identity}@{revision}->{finding.revision}')
        elif finding.status in UNAVAILABLE:
            reasons.append(f'SUPPORT_{finding.status}: {identity}')
    return tuple(reasons)


def _coverage(run, draft, cited, snapshot):
    """Recompute criterion coverage from the *cited* findings, never from the model's word."""
    entries = []
    for criterion in run.acceptance_criteria:
        supporting = tuple(sorted(i for i in cited if criterion.id in snapshot[i].criterion_ids))
        if supporting or criterion.id in draft.criterion_ids:
            entries.append(ResultCoverage(criterion_id=criterion.id, finding_ids=supporting,
                                          required=criterion.required))
    return tuple(entries)


def _check_citations(draft, run, snapshot, pinned):
    """Every citation must be knowledge this assignment was actually given, still valid.

    Returns the deduplicated citation tuple; raises ``ValueError(reason)`` otherwise. A
    result may cite nothing the controller did not select, and nothing that has since
    stopped being validated knowledge.
    """
    cited = tuple(dict.fromkeys(draft.finding_ids))
    if len(cited) != len(draft.finding_ids):
        raise ValueError('RESULT_DUPLICATE_SUPPORT')
    for candidate in cited:
        finding = snapshot.get(candidate)
        if not isinstance(finding, Finding) or finding.run_id != run.id:
            raise ValueError(f'RESULT_SUPPORT_MISSING: {candidate}')
        if candidate not in pinned:
            raise ValueError(f'RESULT_SUPPORT_NOT_IN_CONTEXT: {candidate}')
        if finding.status != FindingStatus.VALIDATED:
            raise ValueError(f'RESULT_SUPPORT_NOT_VALIDATED: {candidate}')
    if not set(draft.criterion_ids) <= {c.id for c in run.acceptance_criteria}:
        raise ValueError('RESULT_UNKNOWN_CRITERION')
    for claim in draft.claims:
        if not claim.finding_ids:
            raise ValueError('RESULT_CLAIM_UNSUPPORTED')
        if not set(claim.finding_ids) <= set(cited):
            raise ValueError('RESULT_CLAIM_REFERENCE_NOT_CITED')
    return cited


def _check_coverage(run, draft, cited, snapshot):
    """Coverage recomputed from the citations; a required criterion must really be covered."""
    coverage = _coverage(run, draft, cited, snapshot)
    declared = {entry.criterion_id for entry in coverage}
    uncovered = sorted(c.criterion_id for c in coverage if c.required and not c.finding_ids)
    missing = sorted(c.id for c in run.acceptance_criteria if c.required and c.id not in declared)
    if uncovered or missing:
        raise ValueError('RESULT_REQUIRED_CRITERION_UNSUPPORTED: ' + ', '.join(uncovered + missing))
    return coverage


def _result_events(record, assignment, task, coverage):
    return [EventDraft(type=EventType.RESULT_CREATED, record_id=record.id,
                       record_revision=record.revision, assignment_id=assignment.id,
                       task_id=task.id, agent_id=assignment.agent_id, correlation_id=record.id,
                       causation_id=assignment.id,
                       detail_json=json.dumps({'version': record.version,
                                               'finding_ids': list(record.finding_ids),
                                               'criterion_ids': list(record.criterion_ids),
                                               'coverage': [{'criterion_id': e.criterion_id,
                                                             'finding_ids': list(e.finding_ids),
                                                             'required': e.required}
                                                            for e in coverage],
                                               'claims': [{'claim': c.claim,
                                                           'finding_ids': list(c.finding_ids)}
                                                          for c in record.claims],
                                               'limitations': list(record.limitations),
                                               'supersedes_id': record.supersedes_id}))]


def admit_result(assignment, result, snapshot, identity):
    """Turn one result envelope into an immutable candidate ``Result`` version.

    Raises ``ValueError(reason)`` when the envelope is not an admissible candidate; the
    caller records the reason and fails the assignment without committing anything.
    """
    task, run, draft = snapshot[assignment.task_id], snapshot[assignment.run_id], result.result
    if task.kind != SYNTHESIS_KIND or draft is None:
        raise ValueError('RESULT_MISSING')
    stale = stale_support(assignment, snapshot)
    if stale:
        raise ValueError('RESULT_STALE: ' + '; '.join(stale))
    if len(draft.answer) > MAX_ANSWER or len(draft.claims) > MAX_CLAIMS:
        raise ValueError('RESULT_SIZE')
    pinned = dict(zip(assignment.input_finding_ids, assignment.input_finding_revisions))
    cited = _check_citations(draft, run, snapshot, pinned)
    coverage = _check_coverage(run, draft, cited, snapshot)
    # A revision names the version it replaces even after that version was judged: the
    # lineage is what makes "never edit a reviewed result" inspectable. Only a version that
    # is still a live candidate is *marked* superseded; a judged one keeps its verdict.
    revised = snapshot.get(task.source_result_id) if task.source_result_id else None
    outgoing = current_result(snapshot, run.id)
    lineage = outgoing or (revised if isinstance(revised, Result) else None)
    record = Result(id=identity('result'), run_id=run.id,
                    version=1 + sum(isinstance(r, Result) and r.run_id == run.id
                                    for r in snapshot.values()),
                    answer=draft.answer, created_by_assignment=assignment.id,
                    criterion_ids=tuple(sorted({e.criterion_id for e in coverage})),
                    coverage=coverage, finding_ids=cited,
                    finding_revisions=tuple(pinned[i] for i in cited),
                    claims=tuple(ResultClaim(claim=c.claim, finding_ids=c.finding_ids)
                                 for c in draft.claims),
                    limitations=tuple(draft.limitations) or task.limitations,
                    unresolved_issues=task.limitations,
                    supersedes_id=lineage.id if lineage else None, created_at=now())
    records, events = [record], _result_events(record, assignment, task, coverage)
    if outgoing is not None:
        replaced = transition_result(outgoing, ResultStatus.SUPERSEDED)
        records.append(replaced)
        events.append(EventDraft(type=EventType.RECORD_CHANGED, record_id=replaced.id,
                                 record_revision=replaced.revision, correlation_id=record.id,
                                 detail_json=json.dumps({'superseded_by': record.id})))
    return records, events, record


def transition_result(result, status, **fields):
    from .domain import transition
    return replace(transition(result, status), **fields)


def repeated_attempt(snapshot, run_id, support, source_review_id):
    """The failed synthesis task this attempt would exactly repeat, or None.

    Identity is the support the controller would supply plus the feedback it would carry:
    an attempt over the same knowledge, after the same review, has nothing new to try.
    """
    for task in sorted((t for t in snapshot.values() if isinstance(t, Task)
                        and t.run_id == run_id and t.kind == SYNTHESIS_KIND), key=lambda t: t.id):
        if (task.status == TaskStatus.FAILED and tuple(task.required_finding_ids) == tuple(support)
                and task.source_review_id == source_review_id):
            return f'{task.id}: {task.outcome}'
    return None


def refresh_support(snapshot, run_id, gate=None):
    """Support currently available for a new synthesis attempt."""
    return gate.support if gate is not None else support_findings(snapshot, run_id)
