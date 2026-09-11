"""Admission of permitted worker proposals into a transaction's record batch.

Findings enter as PROPOSED candidates only. Their evidence carries the host's record of
what each tool actually computed, and their dependencies are the evidence the controller
required them to build on — so invalidating that support later reaches this claim.
"""
import json
from .domain import Finding, Evidence, Message, ReconsiderationOutcome, TaskRequest
from .events import EventDraft, EventType
from .admission import check_task_request, request_fingerprint
from .messaging import route_message
from .propagation import for_task, record_outcome


def admit_proposals(assignment, result, snapshot, identity):
    """Return new records/events. No mutation, scheduling, or knowledge promotion."""
    records, events = [], []
    task = snapshot[assignment.task_id]
    working = dict(snapshot)
    def event(kind, **detail):
        events.append(EventDraft(type=kind, assignment_id=assignment.id, task_id=task.id,
                                 agent_id=assignment.agent_id, correlation_id=assignment.id,
                                 detail_json=json.dumps(detail)))
    tools = {r.id: r for r in result.tool_results if r.success and r.assignment_id == assignment.id}
    dependencies = tuple(sorted(set(task.required_finding_ids) & set(assignment.input_finding_ids)))
    for draft in result.findings:
        if not set(draft.evidence_ids) <= tools.keys():
            raise ValueError('UNTRUSTED_TOOL_EVIDENCE')
        finding = Finding(id=identity('finding'), run_id=assignment.run_id, task_id=task.id,
            assignment_id=assignment.id, claim=draft.claim, reasoning_summary=draft.reasoning_summary,
            evidence=tuple(Evidence(kind='tool_result', reference=i, value=tools[i].value_json,
                                    verified=False, tool_name=tools[i].tool_name,
                                    arguments_json=tools[i].arguments_json)
                           for i in draft.evidence_ids), confidence=draft.confidence,
            dependency_finding_ids=dependencies,
            criterion_ids=task.acceptance_criterion_ids, tags=task.tags)
        records.append(finding)
        working[finding.id] = finding
        events.append(EventDraft(type=EventType.FINDING_CREATED, record_id=finding.id,
            record_revision=finding.revision, assignment_id=assignment.id, task_id=task.id,
            agent_id=assignment.agent_id, correlation_id=assignment.id,
            detail_json=json.dumps({'claim': finding.claim, 'status': str(finding.status),
                                    'criterion_ids': list(finding.criterion_ids),
                                    'dependency_finding_ids': list(dependencies),
                                    'evidence': len(finding.evidence)})))
    permitted_references = set(assignment.input_finding_ids + assignment.message_ids + assignment.dependency_task_ids + (task.id,))
    for draft in result.messages:
        if not set(draft.reference_ids) <= permitted_references:
            event(EventType.MESSAGE_REJECTED, reason='REFERENCE_NOT_IN_CONTEXT', recipient=draft.recipient)
            continue
        message = Message(id=identity('message'), run_id=assignment.run_id,
            sender=f'agent:{assignment.agent_id}', recipient=draft.recipient, summary=draft.summary,
            kind=draft.kind, reference_ids=draft.reference_ids, causation_id=assignment.id,
            correlation_id=assignment.id)
        _, reason = route_message(message, working)
        if reason:
            event(EventType.MESSAGE_REJECTED, reason=reason, recipient=draft.recipient)
            continue
        records.append(message)  # queued until the controller's next delivery pass
        working[message.id] = message
        events.append(EventDraft(type=EventType.MESSAGE_SENT, record_id=message.id,
            record_revision=message.revision, assignment_id=assignment.id, task_id=task.id,
            agent_id=assignment.agent_id, correlation_id=assignment.id))
    for draft in result.task_requests:
        new_id = identity('request')
        decision = check_task_request(draft, assignment, working, candidate_id=new_id)
        if not decision.allowed:
            event(EventType.TASK_REQUEST_REJECTED, reason=decision.reason, objective=draft.objective)
            continue
        request = TaskRequest(id=new_id, run_id=assignment.run_id, assignment_id=assignment.id,
            parent_task_id=task.id, objective=draft.objective, description=draft.description,
            dependency_ids=draft.dependency_ids, criterion_ids=draft.criterion_ids,
            fingerprint=request_fingerprint(draft, task.id))
        records.append(request)
        working[request.id] = request
        events.append(EventDraft(type=EventType.TASK_REQUEST_ADMITTED, record_id=request.id,
            record_revision=request.revision, assignment_id=assignment.id, task_id=task.id,
            detail_json=json.dumps({'executable': False})))
    records, events = _consume(assignment, result, snapshot, task, records, events)
    return records, events


def _consume(assignment, result, snapshot, task, records, events):
    """Settle every delivery this assignment owed an answer for.

    Silence is recorded as UNREPORTED rather than read as agreement, so an unanswered
    discovery stays visible in the audit instead of quietly counting as NO_CHANGE.
    """
    reported = {draft.propagation_id: draft for draft in result.reconsiderations}
    pinned = set(assignment.propagation_ids)
    for propagation, consumable in for_task(snapshot, task):
        if not consumable or propagation.id not in pinned:
            continue
        draft = reported.get(propagation.id)
        outcome = draft.outcome if draft else ReconsiderationOutcome.UNREPORTED
        reason = draft.reason if draft else 'the assignment returned no answer for this delivery'
        consumed, event = record_outcome(propagation, outcome, reason, assignment.id)
        records.append(consumed)
        events.append(event)
    return records, events
