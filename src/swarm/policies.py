"""Small deterministic work policies; no provider calls or canonical mutations."""
from dataclasses import dataclass
from datetime import datetime, timezone
from .domain import (Agent, AgentStatus, Assignment, Finding, FindingStatus, Task, TaskStatus,
                     Result, ResultStatus, Role, RoleName, ReviewKind, ReviewRecord, RunState,
                     AgentGroup, GroupStatus, TERMINAL_RUN_STATES)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    permanent: bool = False


WORK_ROLES = (RoleName.EXPLORER, RoleName.SPECIALIST, RoleName.COLLABORATOR,
              RoleName.CRITIC, RoleName.VALIDATOR, RoleName.SYNTHESIZER, RoleName.FINAL_REVIEWER)
REVIEW_TASK_KINDS = {'criticism': ReviewKind.CRITICISM, 'validation': ReviewKind.VALIDATION,
                     'final_review': ReviewKind.FINAL}
REVIEW_ROLE_FOR = {ReviewKind.CRITICISM: RoleName.CRITIC, ReviewKind.VALIDATION: RoleName.VALIDATOR,
                   ReviewKind.FINAL: RoleName.FINAL_REVIEWER}
FINDING_REVIEW_KINDS = (ReviewKind.CRITICISM, ReviewKind.VALIDATION)
SYNTHESIS_KIND, FINAL_REVIEW_KIND, REPAIR_KIND = 'synthesis', 'final_review', 'repair'
TERMINAL_RUNS = TERMINAL_RUN_STATES
COMPLETION_REQUESTS = 2
"""One synthesis and one final review, held back from optional work at all times."""
DUE_REVIEW_STATUSES = (FindingStatus.PROPOSED, FindingStatus.CRITIQUED, FindingStatus.INVALIDATED)


def stopped(run):
    return bool(run.work_stop_reason or run.state in TERMINAL_RUNS)


def remaining_seconds(run):
    if run.deadline_at is None:
        return float('inf')
    return (datetime.fromisoformat(run.deadline_at) - datetime.now(timezone.utc)).total_seconds()


def role_for(task, snapshot):
    if task.role_id:
        role = snapshot.get(task.role_id)
        return role if isinstance(role, Role) and role.name in WORK_ROLES else None
    wanted = {'exploration': RoleName.EXPLORER, 'specialization': RoleName.SPECIALIST,
              'collaboration': RoleName.COLLABORATOR, 'criticism': RoleName.CRITIC,
              'validation': RoleName.VALIDATOR, 'reconsideration': RoleName.COLLABORATOR,
              'follow_up': RoleName.COLLABORATOR, REPAIR_KIND: RoleName.SPECIALIST,
              SYNTHESIS_KIND: RoleName.SYNTHESIZER,
              FINAL_REVIEW_KIND: RoleName.FINAL_REVIEWER}.get(task.kind)
    return next((r for r in sorted(snapshot.values(), key=lambda r: r.id)
                 if isinstance(r, Role) and r.name == wanted), None)


def compatible_agents(task, role, snapshot, tool_names=(), provider_keys=None, idle_only=True):
    run = snapshot[task.run_id]
    result = []
    for agent in sorted((r for r in snapshot.values() if isinstance(r, Agent)), key=lambda a: a.id):
        if agent.run_id != task.run_id or agent.status == AgentStatus.DISABLED:
            continue
        if idle_only and agent.status != AgentStatus.IDLE:
            continue
        if provider_keys is not None and agent.provider_key not in provider_keys:
            continue
        if task.group_id != agent.group_id:
            continue
        if task.group_id:
            group = snapshot.get(task.group_id)
            if not isinstance(group, AgentGroup) or group.status != GroupStatus.ACTIVE or agent.id not in group.agent_ids:
                continue
        effective = set(run.permissions) & set(agent.permissions) & set(role.allowed_tools) & set(tool_names)
        if set(task.required_tools) <= effective:
            result.append(agent)
    return tuple(result)


def review_kind(task):
    """The review kind a task performs, or None when it is ordinary work."""
    if not (task.target_finding_id or task.target_result_id):
        return None
    kind = REVIEW_TASK_KINDS.get(task.kind)
    if kind == ReviewKind.FINAL:
        return kind if task.target_result_id else None
    return kind if task.target_finding_id else None


def agent_of(snapshot, identity):
    assignment = snapshot.get(identity)
    return assignment.agent_id if isinstance(assignment, Assignment) else None


def excluded_final_reviewers(snapshot, run_id):
    """Every identity that has authored a result version for this run.

    Independence for the final review is about authorship of the answer, not about the
    branches whose findings it rests on: excluding those would make the reviewer pool
    collapse as soon as the run produced knowledge, and would buy no independence the
    Stage-5 finding reviews have not already provided.
    """
    return frozenset(identity for identity in
                     {agent_of(snapshot, r.created_by_assignment) for r in snapshot.values()
                      if isinstance(r, Result) and r.run_id == run_id} if identity)


def excluded_review_agents(task, snapshot):
    """Agent identities that may not perform this review.

    Criticism excludes the generating agent. Validation additionally excludes every agent
    that already reviewed this finding, so generator, critic and validator are three
    distinct identities. A final review excludes every synthesizer identity in the run.
    Independence is decided here, before a provider request is spent.
    """
    kind = review_kind(task)
    if kind == ReviewKind.FINAL:
        return excluded_final_reviewers(snapshot, task.run_id)
    finding = snapshot.get(task.target_finding_id) if kind else None
    if not isinstance(finding, Finding):
        return frozenset()
    excluded = {agent_of(snapshot, finding.assignment_id)}
    if kind == ReviewKind.VALIDATION:
        excluded |= {agent_of(snapshot, r.assignment_id) for r in snapshot.values()
                     if isinstance(r, ReviewRecord) and r.target_id == finding.id}
    return frozenset(identity for identity in excluded if identity)


def compatible_review_agents(task, role, snapshot, tool_names=(), provider_keys=None, idle_only=True):
    """Role/permission/group-compatible agents minus the ones this review may not use."""
    excluded = excluded_review_agents(task, snapshot)
    return tuple(agent for agent in compatible_agents(task, role, snapshot, tool_names, provider_keys, idle_only)
                 if agent.id not in excluded)


def eligible_agents(task, role, snapshot, tool_names=(), provider_keys=None, idle_only=True):
    """One selection entry point; review tasks route through the independence policy."""
    selector = compatible_review_agents if review_kind(task) else compatible_agents
    return selector(task, role, snapshot, tool_names, provider_keys, idle_only)


def completion_imminent(snapshot, run):
    """Whether the run is at or near the point where it needs its final-review identity.

    The controller enters SYNTHESIZING only after the gate said READY, so these states are
    exactly "ready or near-ready" without recomputing the gate inside a selection policy.
    """
    if run.state in (RunState.SYNTHESIZING, RunState.FINAL_REVIEW):
        return True
    return any(isinstance(r, Result) and r.run_id == run.id and r.status == ResultStatus.CANDIDATE
               for r in snapshot.values()) or any(
        isinstance(t, Task) and t.run_id == run.id and t.kind in (SYNTHESIS_KIND, FINAL_REVIEW_KIND)
        and t.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)
        for t in snapshot.values())


def _reserve_one(review, snapshot, reserved, tool_names, provider_keys):
    if not ready_decision(review, snapshot).allowed:
        return
    role = role_for(review, snapshot)
    if role is None:
        return
    free = [a.id for a in eligible_agents(review, role, snapshot, tool_names, provider_keys)
            if a.id not in reserved]
    if free:
        reserved.add(free[0])


def _final_review_holder(snapshot, run, reserved, tool_names, provider_keys):
    """Hold back one eligible independent final-review identity once completion is near.

    This is an explicit reservation rule, not a scheduler: it names the first eligible
    identity in deterministic order and takes nothing else.
    """
    excluded = excluded_final_reviewers(snapshot, run.id)
    role = next((r for r in sorted(snapshot.values(), key=lambda r: r.id)
                 if isinstance(r, Role) and r.name == RoleName.FINAL_REVIEWER), None)
    if role is None:
        return
    probe = Task(id=f'{run.id}:final-review-reservation', run_id=run.id,
                 objective='final review reservation', kind=FINAL_REVIEW_KIND, group_id=None)
    for agent in compatible_agents(probe, role, snapshot, tool_names, provider_keys):
        if agent.id not in excluded and agent.id not in reserved:
            reserved.add(agent.id)
            return


def reserved_for_review(task, snapshot, tool_names=(), provider_keys=None):
    """Idle identities that due review work needs and optional work must not consume.

    Stage 5 made generation, criticism and validation three distinct identities, so the
    independence pool is a real resource. This reserves *one already-schedulable reviewer
    per due review*, and nothing more: a review that is not itself dispatchable reserves
    nobody, so optional work can never deadlock behind a review that will never run.
    Stage 7 extends the same rule to the final reviewer once completion is near.
    """
    if task.required or review_kind(task):
        return frozenset()
    run = snapshot[task.run_id]
    reserved = set()
    for review in sorted((t for t in snapshot.values() if isinstance(t, Task)
                          and t.run_id == task.run_id and review_kind(t)
                          and t.status in (TaskStatus.PENDING, TaskStatus.READY)), key=lambda t: t.id):
        _reserve_one(review, snapshot, reserved, tool_names, provider_keys)
    if completion_imminent(snapshot, run):
        _final_review_holder(snapshot, run, reserved, tool_names, provider_keys)
    return frozenset(reserved)


def ready_decision(task, snapshot):
    run = snapshot[task.run_id]
    if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
        return Decision(False, 'NOT_PENDING')
    if stopped(run) or remaining_seconds(run) <= 0:
        return Decision(False, 'RUN_STOPPED', True)
    for identity in task.dependency_ids:
        dependency = snapshot.get(identity)
        if not isinstance(dependency, Task) or dependency.run_id != task.run_id:
            return Decision(False, 'DEPENDENCY_MISSING', True)
        if dependency.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            return Decision(False, 'DEPENDENCY_FAILED', True)
        if dependency.status != TaskStatus.COMPLETED:
            return Decision(False, 'DEPENDENCY_PENDING')
    if task.group_id:
        group = snapshot.get(task.group_id)
        if not isinstance(group, AgentGroup) or group.status != GroupStatus.ACTIVE:
            return Decision(False, 'GROUP_CLOSED', True)
    return Decision(True)


def select_tasks(tasks):
    return sorted(tasks, key=lambda t: (-t.priority, t.created_at, t.id))


def retry_allowed(attempt, run, reason):
    return attempt < run.assignment_attempt_limit and not stopped(run) and remaining_seconds(run) > 0 and reason != 'CANCELLED'


def outstanding_reviews(snapshot, run):
    """Required finding review/revalidation the controller still owes, not yet scheduled."""
    scheduled = {t.target_finding_id for t in snapshot.values()
                 if isinstance(t, Task) and t.run_id == run.id and t.target_finding_id
                 and REVIEW_TASK_KINDS.get(t.kind) in FINDING_REVIEW_KINDS
                 and t.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)}
    return sum(1 for f in snapshot.values() if isinstance(f, Finding) and f.run_id == run.id
               and f.status in DUE_REVIEW_STATUSES and f.id not in scheduled)


def completion_reserve(snapshot, run):
    """Provider requests held back for the work a run needs in order to finish at all.

    Deliberately simple and deterministic: one synthesis, one final review, and every
    required review or revalidation still owed. An authorized repair round adds required
    repair tasks, which are counted as pending required work rather than reserved twice.
    """
    if stopped(run):
        return 0
    return COMPLETION_REQUESTS + outstanding_reviews(snapshot, run)


@dataclass(frozen=True)
class BudgetPolicy:
    reserved_requests: int = 0
    reserved_tools: int = 0

    def admit(self, task, snapshot, reservations=0):
        run = snapshot[task.run_id]
        floor = self.reserved_requests + reservations
        if not task.required:
            floor += sum(isinstance(t, Task) and t.required and t.status in (TaskStatus.PENDING, TaskStatus.READY)
                         for t in snapshot.values())
            floor += completion_reserve(snapshot, run)
        if run.provider_request_limit - run.provider_requests <= floor:
            return Decision(False, 'BUDGET_RESERVED_OR_EXHAUSTED')
        if task.required_tools and run.tool_call_limit - run.tool_calls <= self.reserved_tools:
            return Decision(False, 'TOOL_BUDGET_EXHAUSTED')
        return Decision(True)
