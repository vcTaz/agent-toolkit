"""Pure admission checks for pinned assignments and nonexecuting task proposals."""
from dataclasses import fields
from .domain import (Agent, AgentStatus, AssignmentStatus, Task, TaskStatus, Finding, FindingStatus,
                     Message, MessageStatus, Propagation, PropagationStatus, Result, ResultStatus,
                     ReviewKind, Role, RoleName, AgentGroup, GroupStatus, TaskRequest)
from .context import digest
from .policies import (Decision, REVIEW_ROLE_FOR, SYNTHESIS_KIND, review_kind, stopped,
                       remaining_seconds)
from .serialization import encode


def check_assignment_admissibility(assignment, execution_result, snapshot, tools=()):
    current = snapshot.get(assignment.id)
    run = snapshot.get(assignment.run_id)
    if current is None or current.status != AssignmentStatus.RUNNING:
        return Decision(False, 'ASSIGNMENT_NOT_RUNNING')
    # Every pin below must match the stored record, so a caller-supplied copy can never
    # widen its own admissibility; only lifecycle fields may have advanced.
    lifecycle = {'revision', 'status', 'started_at', 'ended_at'}
    if any(getattr(assignment, f.name) != getattr(current, f.name)
           for f in fields(current) if f.name not in lifecycle):
        return Decision(False, 'ASSIGNMENT_PROVENANCE_MISMATCH')
    if run is None or stopped(run) or remaining_seconds(run) <= 0:
        return Decision(False, 'RUN_STOPPED')
    if execution_result.assignment_id != assignment.id:
        return Decision(False, 'ASSIGNMENT_ID_MISMATCH')
    task = snapshot.get(assignment.task_id)
    if not isinstance(task, Task) or task.run_id != run.id or task.status != TaskStatus.RUNNING or task.assignment_id != assignment.id:
        return Decision(False, 'TASK_NOT_ASSIGNED')
    if task.revision != assignment.task_revision:
        return Decision(False, 'TASK_REVISION_CHANGED')
    agent = snapshot.get(assignment.agent_id)
    if not isinstance(agent, Agent) or agent.run_id != run.id or agent.status != AgentStatus.RUNNING or agent.assignment_id != assignment.id:
        return Decision(False, 'AGENT_NOT_ASSIGNED')
    role = snapshot.get(assignment.role_id)
    if not isinstance(role, Role) or role.version != assignment.role_version or agent.role_id != role.id:
        return Decision(False, 'ROLE_CHANGED')
    if agent.provider_key != assignment.provider_key:
        return Decision(False, 'PROVIDER_CHANGED')
    if agent.group_id != assignment.group_id or task.group_id != assignment.group_id:
        return Decision(False, 'GROUP_CHANGED')
    if assignment.group_id:
        group = snapshot.get(assignment.group_id)
        if not isinstance(group, AgentGroup) or group.status != GroupStatus.ACTIVE or agent.id not in group.agent_ids:
            return Decision(False, 'GROUP_UNAVAILABLE')
    for identity, revision in zip(assignment.dependency_task_ids, assignment.dependency_task_revisions):
        dep = snapshot.get(identity)
        if not isinstance(dep, Task) or dep.run_id != run.id or dep.status != TaskStatus.COMPLETED or dep.revision != revision:
            return Decision(False, 'DEPENDENCY_TASK_CHANGED')
    # A criticism task may legitimately target an INVALIDATED finding; nothing else may rely on one.
    revisable = task.target_finding_id if review_kind(task) == ReviewKind.CRITICISM else None
    unavailable = (FindingStatus.INVALIDATED, FindingStatus.REJECTED, FindingStatus.SUPERSEDED)
    for identity, revision in zip(assignment.input_finding_ids, assignment.input_finding_revisions):
        f = snapshot.get(identity)
        if (not isinstance(f, Finding) or f.run_id != run.id or f.revision != revision
                or (f.status in unavailable and not (identity == revisable
                                                     and f.status == FindingStatus.INVALIDATED))):
            return Decision(False, 'INPUT_FINDING_CHANGED')
    for identity, revision in zip(assignment.message_ids, assignment.message_revisions):
        m = snapshot.get(identity)
        if not isinstance(m, Message) or m.run_id != run.id or m.status != MessageStatus.DELIVERED or m.delivery_revision != revision or agent.id not in m.delivered_to:
            return Decision(False, 'MESSAGE_DELIVERY_CHANGED')
    # A retracted delivery moves the pinned revision, so an assignment that started while the
    # knowledge was valid is stale by the same rule Stage 4 established for findings.
    for identity, revision in zip(assignment.propagation_ids, assignment.propagation_revisions):
        p = snapshot.get(identity)
        if (not isinstance(p, Propagation) or p.run_id != run.id or p.revision != revision
                or p.status == PropagationStatus.RETRACTED):
            return Decision(False, 'PROPAGATION_CHANGED')
    # A final review is pinned to one exact result version; a version that moved underneath
    # it is stale by the same rule Stage 4 established for findings.
    if assignment.result_id is not None:
        version = snapshot.get(assignment.result_id)
        if (not isinstance(version, Result) or version.run_id != run.id
                or version.revision != assignment.result_revision
                or version.status != ResultStatus.CANDIDATE):
            return Decision(False, 'RESULT_VERSION_CHANGED')
    criteria = {c.id: c for c in run.acceptance_criteria}
    if any(i not in criteria or digest(encode(criteria[i])) != h for i, h in zip(assignment.criterion_ids, assignment.criterion_hashes)):
        return Decision(False, 'CRITERION_CHANGED')
    effective = set(run.permissions) & set(agent.permissions) & set(role.allowed_tools)
    if not set(assignment.tool_names) <= effective:
        return Decision(False, 'PERMISSIONS_CHANGED')
    tool_map = {t.name: t for t in tools}
    if any(name not in tool_map or digest(encode(tool_map[name])) != expected
           for name, expected in zip(assignment.tool_names, assignment.tool_hashes)):
        return Decision(False, 'TOOL_DEFINITION_CHANGED')
    return _check_proposal_kind(assignment, execution_result, task, role, run, snapshot)


def _check_proposal_kind(assignment, execution_result, task, role, run, snapshot):
    """A review envelope is authoritative only in a review role on a review task targeting
    the finding revision this assignment pinned. Everything else is refused before commit."""
    from .review import due_kind
    kind = review_kind(task)
    if task.kind == SYNTHESIS_KIND:
        return _check_result_proposal(assignment, execution_result, task, role, run)
    if execution_result.result is not None:
        return Decision(False, 'RESULT_PROPOSAL_FORBIDDEN')
    if kind is None:
        if execution_result.review is not None:
            return Decision(False, 'REVIEW_PROPOSAL_FORBIDDEN')
        return _check_reconsiderations(assignment, execution_result, snapshot)
    if role.name != REVIEW_ROLE_FOR[kind]:
        return Decision(False, 'REVIEW_ROLE_MISMATCH')
    if execution_result.reconsiderations:
        return Decision(False, 'RECONSIDERATION_FORBIDDEN')
    if execution_result.status != 'SUCCEEDED':
        return Decision(True)
    if execution_result.review is None:
        return Decision(False, 'REVIEW_MISSING')
    if execution_result.findings or execution_result.task_requests:
        return Decision(False, 'REVIEW_SCOPE_VIOLATION')
    if kind == ReviewKind.FINAL:
        return _check_final_review(assignment, execution_result, task, snapshot)
    target = snapshot.get(task.target_finding_id)
    if not isinstance(target, Finding) or target.run_id != run.id:
        return Decision(False, 'REVIEW_TARGET_MISSING')
    pinned = dict(zip(assignment.input_finding_ids, assignment.input_finding_revisions)).get(target.id)
    if pinned is None or target.revision != pinned:
        return Decision(False, 'REVIEW_TARGET_REVISION_CHANGED')
    review = execution_result.review
    if review.target_id != target.id or review.target_revision != pinned:
        return Decision(False, 'REVIEW_TARGET_MISMATCH')
    if due_kind(target) != kind:
        return Decision(False, 'REVIEW_TARGET_INELIGIBLE')
    return Decision(True)


def _check_result_proposal(assignment, execution_result, task, role, run):
    """Only a SYNTHESIZER on a synthesis task may propose a result, and only a result."""
    if role.name != RoleName.SYNTHESIZER:
        return Decision(False, 'SYNTHESIS_ROLE_MISMATCH')
    if execution_result.review is not None or execution_result.reconsiderations:
        return Decision(False, 'SYNTHESIS_SCOPE_VIOLATION')
    if execution_result.status != 'SUCCEEDED':
        return Decision(True)
    if execution_result.result is None:
        return Decision(False, 'RESULT_MISSING')
    if execution_result.findings or execution_result.task_requests:
        return Decision(False, 'SYNTHESIS_SCOPE_VIOLATION')
    if not set(execution_result.result.criterion_ids) <= {c.id for c in run.acceptance_criteria}:
        return Decision(False, 'RESULT_UNKNOWN_CRITERION')
    return Decision(True)


def _check_final_review(assignment, execution_result, task, snapshot):
    """The reviewed version must be the exact one this assignment was dispatched against."""
    version = snapshot.get(task.target_result_id)
    if not isinstance(version, Result) or version.run_id != assignment.run_id:
        return Decision(False, 'REVIEW_TARGET_MISSING')
    if assignment.result_id != version.id or version.revision != assignment.result_revision:
        return Decision(False, 'REVIEW_TARGET_REVISION_CHANGED')
    review = execution_result.review
    if review.target_id != version.id or review.target_revision != assignment.result_revision:
        return Decision(False, 'REVIEW_TARGET_MISMATCH')
    if version.status != ResultStatus.CANDIDATE:
        return Decision(False, 'REVIEW_TARGET_INELIGIBLE')
    return Decision(True)


def _check_reconsiderations(assignment, execution_result, snapshot):
    """A branch may answer only the deliveries this assignment actually received.

    The propagation must have been pinned into this context, must still be the delivery it
    was, and must be one this task owes an outcome for; a reported outcome cannot invent a
    delivery, reach another branch's delivery, or answer one already consumed.
    """
    from .propagation import for_task
    if not execution_result.reconsiderations:
        return Decision(True)
    task = snapshot.get(assignment.task_id)
    owed = {p.id for p, consumable in for_task(snapshot, task) if consumable}
    pinned = set(assignment.propagation_ids)
    for draft in execution_result.reconsiderations:
        if draft.propagation_id not in pinned:
            return Decision(False, 'RECONSIDERATION_NOT_IN_CONTEXT')
        if draft.propagation_id not in owed:
            return Decision(False, 'RECONSIDERATION_TARGET_INELIGIBLE')
    return Decision(True)


def request_fingerprint(draft, parent_id):
    return digest({'parent': parent_id, 'objective': ' '.join(draft.objective.lower().split()),
                   'description': ' '.join(draft.description.split()),
                   'dependencies': sorted(draft.dependency_ids), 'criteria': sorted(draft.criterion_ids)})


def check_task_request(draft, assignment, snapshot, *, candidate_id='__new_request__'):
    run = snapshot[assignment.run_id]
    parent_id = draft.parent_task_id or assignment.task_id
    parent = snapshot.get(parent_id)
    if parent_id != assignment.task_id or not isinstance(parent, Task) or parent.run_id != run.id:
        return Decision(False, 'INVALID_REQUEST_PARENT')
    if not draft.objective.strip() or len(draft.objective) > 4000 or len(draft.description) > 4000:
        return Decision(False, 'REQUEST_SIZE')
    if stopped(run) or remaining_seconds(run) <= 0 or run.provider_requests >= run.provider_request_limit:
        return Decision(False, 'REQUEST_BUDGET_EXHAUSTED')
    if sum(isinstance(r, (Task, TaskRequest)) for r in snapshot.values()) >= run.task_limit:
        return Decision(False, 'TASK_LIMIT')
    if len(draft.dependency_ids) > 16 or len(set(draft.dependency_ids)) != len(draft.dependency_ids):
        return Decision(False, 'INVALID_REQUEST_DEPENDENCIES')
    if candidate_id in draft.dependency_ids:
        return Decision(False, 'REQUEST_CYCLE')
    for identity in draft.dependency_ids:
        dep = snapshot.get(identity)
        if not isinstance(dep, Task) or dep.run_id != run.id:
            return Decision(False, 'INVALID_REQUEST_DEPENDENCY')
    if not set(draft.criterion_ids) <= set(parent.acceptance_criterion_ids):
        return Decision(False, 'INVALID_REQUEST_CRITERIA')
    # Validate the proposed graph even when a caller supplies an inconsistent fixture snapshot.
    edges = {r.id: r.dependency_ids for r in snapshot.values() if isinstance(r, Task)}
    edges[candidate_id] = draft.dependency_ids
    active, done = set(), set()
    def visit(identity):
        if identity in active:
            return False
        if identity in done:
            return True
        active.add(identity)
        if any(not visit(dep) for dep in edges.get(identity, ())):
            return False
        active.remove(identity)
        done.add(identity)
        return True
    if any(not visit(i) for i in edges):
        return Decision(False, 'REQUEST_CYCLE')
    fingerprint = request_fingerprint(draft, parent_id)
    if any(isinstance(r, TaskRequest) and r.fingerprint == fingerprint for r in snapshot.values()):
        return Decision(False, 'DUPLICATE_REQUEST')
    return Decision(True)
