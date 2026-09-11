"""A human-readable causal trace over the durable event log.

The audit already records what happened and in what order; a per-run monotonic sequence is
the causal order. This module only renders it, and it renders from an explicit allowlist of
detail keys rather than dumping event payloads — so a trace can never leak an execution
transcript, a context snapshot or a whole before/after record into the terminal.
"""
import json
from .events import EventType

CORE_EVENTS = (
    EventType.RUN_CREATED, EventType.RUN_STATE_CHANGED,
    EventType.CYCLE_STARTED, EventType.CYCLE_COMPLETED,
    EventType.TASK_CREATED, EventType.TASK_READY, EventType.TASK_ASSIGNED,
    EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED,
    EventType.TASK_BLOCKED, EventType.RETRY_SCHEDULED, EventType.OUTPUT_REJECTED,
    EventType.TASK_REQUEST_ADMITTED, EventType.TASK_REQUEST_REJECTED,
    EventType.FINDING_CREATED, EventType.REVIEW_STARTED, EventType.REVIEW_COMPLETED,
    EventType.REVIEW_REJECTED, EventType.FINDING_CRITIQUED, EventType.FINDING_VALIDATED,
    EventType.FINDING_REJECTED, EventType.FINDING_INVALIDATED, EventType.FINDING_SUPERSEDED,
    EventType.KNOWLEDGE_PROMOTED, EventType.KNOWLEDGE_REMOVED,
    EventType.CONSOLIDATION_COMPLETED, EventType.CONFLICT_OPENED, EventType.CONFLICT_RESOLVED,
    EventType.MESSAGE_SENT, EventType.MESSAGE_DELIVERED, EventType.MESSAGE_REJECTED,
    EventType.PROPAGATION_SELECTED, EventType.CROSS_POLLINATION,
    EventType.PROPAGATION_DELIVERED, EventType.PROPAGATION_SKIPPED,
    EventType.PROPAGATION_RETRACTED, EventType.RETRACTION_DELIVERED,
    EventType.RECONSIDERATION_STARTED, EventType.RECONSIDERATION_COMPLETED,
    EventType.BRANCH_TERMINATED, EventType.GROUP_CLOSED, EventType.COVERAGE_GAP,
    EventType.SYNTHESIS_GATE_EVALUATED, EventType.SYNTHESIS_STARTED, EventType.SYNTHESIS_STALE,
    EventType.RESULT_CREATED, EventType.RESULT_REJECTED,
    EventType.FINAL_REVIEW_STARTED, EventType.FINAL_REVIEW_COMPLETED,
    EventType.FINAL_REVIEW_STALE, EventType.RESULT_REVISION_REQUESTED,
    EventType.REPAIR_WORK_CREATED, EventType.WORK_STOPPED,
    EventType.RUN_COMPLETED, EventType.RUN_EXHAUSTED, EventType.RUN_FAILED,
    EventType.RUN_CANCELLED)
"""The narrative: what a reader needs to reconstruct the agent/task/finding/review/
propagation flow without reading storage."""

DETAIL_EVENTS = (
    EventType.CONTEXT_SELECTED, EventType.AGENT_STARTED, EventType.AGENT_COMPLETED,
    EventType.AGENT_FAILED, EventType.ROLE_ASSIGNED, EventType.BRANCH_PROGRESS,
    EventType.PROVIDER_REQUESTED, EventType.PROVIDER_COMPLETED, EventType.PROVIDER_FAILED,
    EventType.TOOL_STARTED, EventType.TOOL_COMPLETED, EventType.TOOL_FAILED,
    EventType.EXECUTION_STARTED, EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED,
    EventType.EXECUTION_CANCELLED)
"""Execution-seam bookkeeping. Available on request; never part of the default narrative."""

SAFE_KEYS = ('reason', 'status', 'decision', 'model_decision', 'verification', 'kind',
             'task_kind', 'review_kind', 'phase', 'number', 'trigger', 'admitted', 'cycle',
             'criterion_id', 'target_finding_id', 'target_revision', 'target_result_id',
             'result_id', 'review_id', 'propagation_id', 'recipient', 'delivered_to',
             'code', 'name', 'call_id', 'round', 'version', 'attempt', 'progress',
             'idle_cycles', 'revision_kind', 'stop_reason', 'role_id', 'agent_id',
             'outcome', 'outcome_reason', 'score', 'target_task_id', 'canonical_finding_id',
             'source_propagation_id', 'gap', 'from', 'to', 'insight', 'repair_key')
"""Every other detail key is summarised by shape, never printed verbatim: an event payload
may contain a proposal, a context snapshot or a record image, and none of those belong in
a trace."""

COUNTED_KEYS = ('gaps', 'reasons', 'blocking_issues', 'nonblocking_issues', 'resolved_issues',
               'criterion_ids', 'unsupported_claims', 'task_ids', 'support', 'finding_ids',
               'selected_ids', 'omitted_ids', 'repairable', 'stale', 'validated_findings',
               'branch_stops', 'final_review_issues', 'unconsumed_knowledge', 'canonical_ids',
               'duplicate_ids', 'open_conflict_ids', 'propagation_ids', 'coverage_gaps',
               'unresolved', 'trigger_ids', 'blockers', 'checks', 'feedback', 'matched_features')


def _short(value, limit=90):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def summarise(detail):
    """A bounded, allowlisted one-line rendering of one event's detail."""
    parts = []
    for key in SAFE_KEYS:
        if key in detail and detail[key] not in (None, '', [], {}):
            parts.append(f'{key}={_short(detail[key])}')
    for key in COUNTED_KEYS:
        value = detail.get(key)
        if isinstance(value, list) and value:
            parts.append(f'{key}[{len(value)}]={_short(value, 70)}')
    return ' '.join(parts)


def entry(event):
    detail = json.loads(event.detail_json)
    return {'sequence': event.sequence, 'type': str(event.type), 'timestamp': event.timestamp,
            'record_id': event.record_id, 'task_id': event.task_id, 'agent_id': event.agent_id,
            'assignment_id': event.assignment_id, 'group_id': event.group_id,
            'correlation_id': event.correlation_id, 'causation_id': event.causation_id,
            'summary': summarise(detail)}


def build(events, *, full=False):
    """The trace, in causal order. ``full`` adds the execution-seam bookkeeping."""
    wanted = set(CORE_EVENTS) | (set(DETAIL_EVENTS) if full else set())
    return tuple(entry(event) for event in events if event.type in wanted)


def identifiers(item):
    """The ids a trace line carries, deduplicated and in a stable order for rendering."""
    seen, order = set(), []
    for key in ('task_id', 'agent_id', 'assignment_id', 'group_id', 'record_id'):
        value = item.get(key)
        if value and value not in seen:
            seen.add(value)
            order.append(value)
    return tuple(order)
