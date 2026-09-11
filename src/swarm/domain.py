"""Immutable canonical records and controller-facing invariant functions.

These are trusted host APIs, never capabilities exposed to model providers.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum


class DomainError(ValueError):
    """Invalid record, reference, or lifecycle operation."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_VERSION = 4
"""Record schema. Stage 7 adds the durable ``Result`` version, the ``TerminalReport`` and the
run-workflow fields the controller needs; a stage-6 payload is refused rather than silently
reread with defaults."""


class AgentStatus(StrEnum):
    IDLE = 'IDLE'
    RUNNING = 'RUNNING'
    DISABLED = 'DISABLED'


class TaskStatus(StrEnum):
    PENDING = 'PENDING'
    READY = 'READY'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


class FindingStatus(StrEnum):
    PROPOSED = 'PROPOSED'
    CRITIQUED = 'CRITIQUED'
    VALIDATED = 'VALIDATED'
    INVALIDATED = 'INVALIDATED'
    REJECTED = 'REJECTED'
    SUPERSEDED = 'SUPERSEDED'


class RunState(StrEnum):
    RECEIVED = 'RECEIVED'
    DECOMPOSING = 'DECOMPOSING'
    EXPLORING = 'EXPLORING'
    EVALUATING = 'EVALUATING'
    CONSOLIDATING = 'CONSOLIDATING'
    SYNTHESIZING = 'SYNTHESIZING'
    FINAL_REVIEW = 'FINAL_REVIEW'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    EXHAUSTED = 'EXHAUSTED'
    CANCELLED = 'CANCELLED'


class RoleName(StrEnum):
    EXPLORER = 'EXPLORER'
    SPECIALIST = 'SPECIALIST'
    CRITIC = 'CRITIC'
    VALIDATOR = 'VALIDATOR'
    COLLABORATOR = 'COLLABORATOR'
    CONSOLIDATOR = 'CONSOLIDATOR'
    CROSS_POLLINATOR = 'CROSS_POLLINATOR'
    SYNTHESIZER = 'SYNTHESIZER'
    FINAL_REVIEWER = 'FINAL_REVIEWER'


class MessageStatus(StrEnum):
    QUEUED = 'QUEUED'
    DELIVERED = 'DELIVERED'
    REJECTED = 'REJECTED'


class GroupStatus(StrEnum):
    ACTIVE = 'ACTIVE'
    CLOSED = 'CLOSED'


class ReviewKind(StrEnum):
    CRITICISM = 'criticism'
    VALIDATION = 'validation'
    FINAL = 'final'
    """Independent review of one exact candidate ``Result`` version, never of a Finding."""


class ReviewDecision(StrEnum):
    """One closed set; ``REVIEW_DECISIONS`` restricts it per review kind."""
    PASS = 'PASS'
    CHALLENGE = 'CHALLENGE'
    FAIL = 'FAIL'
    INCONCLUSIVE = 'INCONCLUSIVE'
    REVISE = 'REVISE'
    REJECT = 'REJECT'


REVIEW_DECISIONS = {
    ReviewKind.CRITICISM: (ReviewDecision.PASS, ReviewDecision.CHALLENGE, ReviewDecision.INCONCLUSIVE),
    ReviewKind.VALIDATION: (ReviewDecision.PASS, ReviewDecision.FAIL, ReviewDecision.INCONCLUSIVE),
    ReviewKind.FINAL: (ReviewDecision.PASS, ReviewDecision.REVISE, ReviewDecision.REJECT),
}


class ConflictStatus(StrEnum):
    OPEN = 'OPEN'
    RESOLVED = 'RESOLVED'


class ConflictKind(StrEnum):
    CONTRADICTORY_VALUE = 'CONTRADICTORY_VALUE'
    DECLARED_CONTRADICTION = 'DECLARED_CONTRADICTION'


class AssignmentStatus(StrEnum):
    CREATED = 'CREATED'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


class PropagationKind(StrEnum):
    """What a targeted delivery carries. Never a transcript, never unvalidated knowledge."""
    INSIGHT = 'INSIGHT'
    CONFLICT = 'CONFLICT'
    RETRACTION = 'RETRACTION'


class PropagationStatus(StrEnum):
    SELECTED = 'SELECTED'
    DELIVERED = 'DELIVERED'
    CONSUMED = 'CONSUMED'
    SKIPPED = 'SKIPPED'
    RETRACTED = 'RETRACTED'


class ReconsiderationOutcome(StrEnum):
    """``UNREPORTED`` is host-recorded: silence is an outcome of its own, never NO_CHANGE."""
    APPLIED = 'APPLIED'
    NO_CHANGE = 'NO_CHANGE'
    FOLLOW_UP_REQUESTED = 'FOLLOW_UP_REQUESTED'
    UNREPORTED = 'UNREPORTED'


REPORTABLE_OUTCOMES = (ReconsiderationOutcome.APPLIED, ReconsiderationOutcome.NO_CHANGE,
                       ReconsiderationOutcome.FOLLOW_UP_REQUESTED)
"""The closed set a worker may return; the host alone records ``UNREPORTED``."""


class CycleStatus(StrEnum):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'


class ResultStatus(StrEnum):
    """A result version is written once and only ever judged; it is never edited."""
    CANDIDATE = 'CANDIDATE'
    ACCEPTED = 'ACCEPTED'
    REVISED = 'REVISED'
    REJECTED = 'REJECTED'
    SUPERSEDED = 'SUPERSEDED'


class RevisionKind(StrEnum):
    """What a REVISE/REJECT actually requires. The controller decides this from state; a
    reviewer's issues locate the defect but never classify it."""
    PRESENTATION = 'PRESENTATION'
    EVIDENCE = 'EVIDENCE'
    NONE = 'NONE'


class GateStatus(StrEnum):
    READY = 'READY'
    NOT_READY = 'NOT_READY'
    EXHAUSTED = 'EXHAUSTED'


class BranchStop(StrEnum):
    DEPENDENCY_FAILED = 'DEPENDENCY_FAILED'
    SUPERSEDED = 'SUPERSEDED'
    CRITERION_COVERED = 'CRITERION_COVERED'
    ATTEMPT_LIMIT = 'ATTEMPT_LIMIT'
    NO_PROGRESS = 'NO_PROGRESS'
    CYCLE_LIMIT = 'CYCLE_LIMIT'
    BUDGET_LIMIT = 'BUDGET_LIMIT'
    CANCELLED = 'CANCELLED'


@dataclass(frozen=True, kw_only=True)
class Record:
    id: str
    schema_version: int = SCHEMA_VERSION
    revision: int = 1

    def __post_init__(self):
        from .validation import check_record
        check_record(self)
        if not self.id or self.schema_version != SCHEMA_VERSION or self.revision < 1:
            raise DomainError('invalid identity, schema version, or revision')


@dataclass(frozen=True, kw_only=True)
class RunRecord(Record):
    run_id: str


@dataclass(frozen=True, kw_only=True)
class Role(Record):
    name: RoleName
    version: int = 1
    instructions: str = ''
    allowed_tools: tuple[str, ...] = ()
    output_fields: tuple[str, ...] = ('findings', 'messages', 'task_requests')
    communication_scope: str = 'group'
    input_kind: str = 'task'
    output_kind: str = 'execution_result'


@dataclass(frozen=True, kw_only=True)
class Agent(RunRecord):
    provider_key: str = 'fake'
    status: AgentStatus = AgentStatus.IDLE
    permissions: tuple[str, ...] = ()
    role_id: str | None = None
    assignment_id: str | None = None
    group_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class Task(RunRecord):
    objective: str
    description: str = ''
    kind: str = 'exploration'
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    dependency_ids: tuple[str, ...] = ()
    acceptance_criterion_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    parent_task_id: str | None = None
    group_id: str | None = None
    assignment_id: str | None = None
    outcome: str | None = None
    role_id: str | None = None
    required_tools: tuple[str, ...] = ()
    required: bool = True
    required_finding_ids: tuple[str, ...] = ()
    candidate_finding_ids: tuple[str, ...] = ()
    allow_dependency_candidates: bool = False
    target_finding_id: str | None = None
    target_result_id: str | None = None
    """Set only by the controller-owned final-review factory."""
    source_result_id: str | None = None
    source_review_id: str | None = None
    """Provenance for controller-authored synthesis, resynthesis and repair work."""
    limitations: tuple[str, ...] = ()
    """Bounded, controller-selected caveats a synthesis assignment must acknowledge."""
    source_propagation_id: str | None = None
    """Set only by the controller-owned reconsideration factory; no model-reachable path."""
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class Evidence:
    """``tool_name``/``arguments_json`` are host-recorded: a verifier must be able to see
    what was actually computed, not only that some tool call succeeded."""
    kind: str
    value: str = ''
    reference: str | None = None
    verified: bool = False
    tool_name: str = ''
    arguments_json: str = ''



@dataclass(frozen=True, kw_only=True)
class Finding(RunRecord):
    task_id: str
    assignment_id: str
    claim: str
    reasoning_summary: str = ''
    evidence: tuple[Evidence, ...] = ()
    status: FindingStatus = FindingStatus.PROPOSED
    dependency_finding_ids: tuple[str, ...] = ()
    related_finding_ids: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    review_ids: tuple[str, ...] = ()
    confidence: float | None = None
    supersedes_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class Message(RunRecord):
    sender: str
    recipient: str
    kind: str = 'INSIGHT'
    summary: str = ''
    reference_ids: tuple[str, ...] = ()
    status: MessageStatus = MessageStatus.QUEUED
    created_at: str = field(default_factory=now)
    delivered_to: tuple[str, ...] = ()
    delivery_revision: int = 0
    read_by: tuple[str, ...] = ()
    causation_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class SwarmState(RunRecord):
    active_task_ids: tuple[str, ...] = ()
    validated_findings: tuple[str, ...] = ()
    candidate_findings: tuple[str, ...] = ()
    invalidated_findings: tuple[str, ...] = ()
    rejected_findings: tuple[str, ...] = ()
    failed_approaches: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    active_group_ids: tuple[str, ...] = ()
    open_conflict_ids: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AgentGroup(RunRecord):
    task_ids: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    status: GroupStatus = GroupStatus.ACTIVE
    stop_reason: str | None = None
    progress_signature: str = ''
    """Digest of this branch's measured knowledge at the last cycle boundary."""
    progress_cycle: int = 0
    idle_cycles: int = 0


@dataclass(frozen=True, kw_only=True)
class Criterion:
    id: str
    description: str
    verifier_kind: str = 'tool'
    required: bool = True
    """A required criterion must be cleanly covered before synthesis; an optional one may
    survive as a recorded limitation."""


@dataclass(frozen=True, kw_only=True)
class ResultClaim:
    """One material claim in the answer and the validated findings that carry it."""
    claim: str
    finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ResultCoverage:
    criterion_id: str
    finding_ids: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True, kw_only=True)
class Gap:
    """One criterion that current knowledge does not cleanly support, and why."""
    criterion_id: str
    reason: str
    required: bool = True
    supporting_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    invalidated_support: tuple[str, ...] = ()

    @property
    def key(self):
        return f'{self.criterion_id}:{self.reason}'


@dataclass(frozen=True, kw_only=True)
class Result(RunRecord):
    """One immutable candidate answer, pinned to the exact support it was built from.

    A revision never edits a reviewed result: it creates a new version that names the one it
    supersedes, so the review that judged version *n* keeps meaning what it meant.
    """
    version: int
    answer: str
    created_by_assignment: str
    status: ResultStatus = ResultStatus.CANDIDATE
    criterion_ids: tuple[str, ...] = ()
    coverage: tuple[ResultCoverage, ...] = ()
    finding_ids: tuple[str, ...] = ()
    finding_revisions: tuple[int, ...] = ()
    claims: tuple[ResultClaim, ...] = ()
    limitations: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    supersedes_id: str | None = None
    review_id: str | None = None
    decision: ReviewDecision | None = None
    revision_kind: RevisionKind | None = None
    created_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class TerminalReport(RunRecord):
    """What a run ended with. Written once, in the same transaction as the terminal state.

    A non-success terminal report keeps the validated partial knowledge, the unresolved
    gaps and the branch stop reasons; it never presents them as a completed answer.
    """
    state: RunState
    stop_reason: str
    result_id: str | None = None
    validated_finding_ids: tuple[str, ...] = ()
    gaps: tuple[Gap, ...] = ()
    branch_stops: tuple[str, ...] = ()
    final_review_issues: tuple[str, ...] = ()
    unconsumed_knowledge: tuple[str, ...] = ()
    created_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class Run(Record):
    objective: str
    state: RunState = RunState.RECEIVED
    acceptance_criteria: tuple[Criterion, ...] = ()
    provider_request_limit: int = 80
    tool_call_limit: int = 120
    provider_requests: int = 0
    tool_calls: int = 0
    cycle: int = 0
    permissions: tuple[str, ...] = ()
    concurrency_limit: int = 4
    task_limit: int = 32
    assignment_attempt_limit: int = 2
    cycle_limit: int = 3
    """Exploration waves including the initial one, per the architecture default."""
    no_progress_limit: int = 2
    repair_rounds: int = 0
    repair_round_limit: int = 2
    """Evidence-repair rounds after a final review, per the architecture default."""
    presentation_revisions: int = 0
    presentation_revision_limit: int = 2
    """Resyntheses that changed only how known knowledge was presented."""
    synthesis_attempts: int = 0
    synthesis_attempt_limit: int = 5
    execution_timeout: float = 60.0
    deadline_at: str | None = None
    work_stop_reason: str | None = None
    result_id: str | None = None
    """The one ACCEPTED result version; set only in the transaction that enters COMPLETED."""
    candidate_result_id: str | None = None
    outcome_id: str | None = None
    stop_reason: str | None = None
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class Assignment(RunRecord):
    task_id: str
    agent_id: str
    role_id: str
    role_version: int = 1
    attempt: int = 1
    input_finding_ids: tuple[str, ...] = ()
    input_finding_revisions: tuple[int, ...] = ()
    status: AssignmentStatus = AssignmentStatus.CREATED
    task_revision: int = 0
    group_id: str | None = None
    provider_key: str = ''
    dependency_task_ids: tuple[str, ...] = ()
    dependency_task_revisions: tuple[int, ...] = ()
    message_ids: tuple[str, ...] = ()
    message_revisions: tuple[int, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    criterion_hashes: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    tool_hashes: tuple[str, ...] = ()
    propagation_ids: tuple[str, ...] = ()
    propagation_revisions: tuple[int, ...] = ()
    result_id: str | None = None
    result_revision: int = 0
    """A final-review assignment pins the exact result version it was dispatched against."""
    state_id: str | None = None
    state_revision: int = 0
    context_json: str = ''
    context_hash: str = ''
    started_at: str | None = None
    ended_at: str | None = None


@dataclass(frozen=True, kw_only=True)
class ReviewRecord(RunRecord):
    """Immutable, targets one exact record revision. Only the host writes verified evidence."""
    assignment_id: str
    target_id: str
    target_revision: int
    decision: ReviewDecision
    kind: ReviewKind = ReviewKind.VALIDATION
    evidence: tuple[Evidence, ...] = ()
    checks: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    nonblocking_issues: tuple[str, ...] = ()
    resolved_issues: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    """Criteria a final review names as at fault. A locator, not a classification: the
    controller still decides from state what the defect requires."""
    unsupported_claims: tuple[str, ...] = ()
    summary: str = ''
    verification: str = ''
    created_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class Conflict(RunRecord):
    """Two individually reviewed findings that cannot both stand uncontested."""
    finding_ids: tuple[str, ...]
    finding_revisions: tuple[int, ...]
    kind: ConflictKind
    signature: str
    reason: str = ''
    status: ConflictStatus = ConflictStatus.OPEN
    criterion_ids: tuple[str, ...] = ()
    resolution: str | None = None
    resolved_at: str | None = None
    created_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class Propagation(RunRecord):
    """One targeted cross-pollination decision and its delivery lifecycle.

    There is no broadcast recipient: every propagation names exactly one target task. The
    decision itself — score, matched features, the knowledge identity it carries and the
    projection revision it was taken from — is durable, so the audit can answer what exact
    knowledge change caused this delivery. Only the lifecycle fields ever change.
    """
    kind: PropagationKind
    knowledge_key: str
    """Deterministic identity of the *fact*: the consolidation duplicate signature. Stable
    across which member of a duplicate group happens to be canonical."""
    knowledge_revision: int
    canonical_finding_id: str
    source_finding_ids: tuple[str, ...] = ()
    target_task_id: str
    target_group_id: str | None = None
    delivery_key: str
    """``(kind, knowledge_key, knowledge_revision, target_task_id)``; unique within a run."""
    score: int = 0
    matched_features: tuple[str, ...] = ()
    insight: str = ''
    reason: str = ''
    state_revision: int = 0
    cycle: int = 0
    conflict_id: str | None = None
    retracts_id: str | None = None
    status: PropagationStatus = PropagationStatus.SELECTED
    status_reason: str = ''
    outcome: ReconsiderationOutcome | None = None
    outcome_reason: str = ''
    outcome_assignment_id: str | None = None
    reconsideration_task_id: str | None = None
    follow_up_task_id: str | None = None
    created_at: str = field(default_factory=now)


@dataclass(frozen=True, kw_only=True)
class Cycle(RunRecord):
    """One bounded exploration or reconsideration wave and what justified it."""
    number: int
    trigger: str
    trigger_ids: tuple[str, ...] = ()
    reason: str = ''
    task_ids: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    status: CycleStatus = CycleStatus.OPEN
    created_at: str = field(default_factory=now)
    ended_at: str | None = None


@dataclass(frozen=True, kw_only=True)
class TaskRequest(RunRecord):
    """An admitted proposal, never an executable Task."""
    assignment_id: str
    parent_task_id: str
    objective: str
    description: str = ''
    dependency_ids: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    fingerprint: str = ''


ACTIVE_RUN_STATES = (RunState.RECEIVED, RunState.DECOMPOSING, RunState.EXPLORING,
                     RunState.EVALUATING, RunState.CONSOLIDATING, RunState.SYNTHESIZING,
                     RunState.FINAL_REVIEW)
TERMINAL_RUN_STATES = (RunState.COMPLETED, RunState.FAILED, RunState.EXHAUSTED, RunState.CANCELLED)
_ABANDON = (RunState.FAILED, RunState.EXHAUSTED, RunState.CANCELLED)
"""Every active state may end this way; COMPLETED is reachable only through final review."""

RUN_TRANSITIONS = {
    RunState.RECEIVED: (RunState.DECOMPOSING,) + _ABANDON,
    RunState.DECOMPOSING: (RunState.EXPLORING,) + _ABANDON,
    RunState.EXPLORING: (RunState.EVALUATING,) + _ABANDON,
    RunState.EVALUATING: (RunState.CONSOLIDATING,) + _ABANDON,
    RunState.CONSOLIDATING: (RunState.EXPLORING, RunState.SYNTHESIZING) + _ABANDON,
    RunState.SYNTHESIZING: (RunState.FINAL_REVIEW, RunState.CONSOLIDATING) + _ABANDON,
    RunState.FINAL_REVIEW: (RunState.COMPLETED, RunState.SYNTHESIZING, RunState.EXPLORING) + _ABANDON,
}
"""Terminal states are absent, so they are absorbing by construction."""


TRANSITIONS = {
    AgentStatus: {'IDLE': ('RUNNING', 'DISABLED'), 'RUNNING': ('IDLE', 'DISABLED')},
    TaskStatus: {'PENDING': ('READY', 'FAILED', 'CANCELLED'),
                 'READY': ('RUNNING', 'FAILED', 'CANCELLED'),
                 'RUNNING': ('READY', 'COMPLETED', 'FAILED', 'CANCELLED')},
    FindingStatus: {'PROPOSED': ('CRITIQUED', 'REJECTED'),
                    'CRITIQUED': ('VALIDATED', 'REJECTED'),
                    'VALIDATED': ('INVALIDATED', 'SUPERSEDED'),
                    'INVALIDATED': ('CRITIQUED', 'REJECTED')},
    MessageStatus: {'QUEUED': ('DELIVERED', 'REJECTED')},
    GroupStatus: {'ACTIVE': ('CLOSED',)},
    ConflictStatus: {'OPEN': ('RESOLVED',)},
    AssignmentStatus: {'CREATED': ('RUNNING', 'CANCELLED'),
                       'RUNNING': ('COMPLETED', 'FAILED', 'CANCELLED')},
    PropagationStatus: {'SELECTED': ('DELIVERED', 'SKIPPED', 'RETRACTED'),
                        'DELIVERED': ('CONSUMED', 'SKIPPED', 'RETRACTED'),
                        'CONSUMED': ('RETRACTED',)},
    CycleStatus: {'OPEN': ('CLOSED',)},
    ResultStatus: {'CANDIDATE': ('ACCEPTED', 'REVISED', 'REJECTED', 'SUPERSEDED')},
}


def blocking_keys(review: 'ReviewRecord') -> tuple[str, ...]:
    """Stable identifiers for a critique's blocking issues, so later verification can
    say which one it addressed instead of asserting that all of them are fine."""
    return tuple(f'{review.id}#{index}' for index, _ in enumerate(review.blocking_issues))


def transition(record, target, *, review: ReviewRecord | None = None):
    """Return a successor for one guarded lifecycle step.

    The Run's own workflow is here because it is a lifecycle like any other; what makes it
    controller-owned is that only the controller may *call* this, and that the readiness
    predicates guarding each step live in ``workflow``/``completion``, not in a model.
    """
    if isinstance(record, Run):
        if type(target) is not RunState or target not in RUN_TRANSITIONS.get(record.state, ()):
            raise DomainError(f'illegal run transition: {record.state} -> {target}')
        return replace(record, state=target, revision=record.revision + 1, updated_at=now())
    current = getattr(record, 'status', None)
    if type(target) is not type(current) or target not in TRANSITIONS.get(type(current), {}).get(current, ()):
        raise DomainError(f'illegal transition: {current} -> {target}')
    updates = {'status': target, 'revision': record.revision + 1}
    if isinstance(record, Finding) and target == FindingStatus.VALIDATED:
        if (review is None or review.run_id != record.run_id or review.target_id != record.id
                or review.target_revision != record.revision or review.kind != ReviewKind.VALIDATION
                or review.decision != ReviewDecision.PASS or review.blocking_issues
                or review.assignment_id == record.assignment_id
                or not any(e.verified and e.kind == 'tool_result' and e.reference for e in review.evidence)):
            raise DomainError('validation requires independent, versioned, tool-backed review')
        updates['review_ids'] = record.review_ids + (review.id,)
    if isinstance(record, Task):
        updates['updated_at'] = now()
    return replace(record, **updates)


def assign_role(agent: Agent, role: Role) -> Agent:
    if agent.status != AgentStatus.IDLE:
        raise DomainError('only idle agents can change role')
    return replace(agent, role_id=role.id, revision=agent.revision + 1)


def revise_finding(finding: Finding, *, new_id: str, claim: str,
                   evidence: tuple[Evidence, ...]) -> Finding:
    if new_id == finding.id:
        raise DomainError('substantive revision requires a new finding identity')
    return replace(finding, id=new_id, claim=claim, evidence=evidence, revision=1,
                   status=FindingStatus.PROPOSED, review_ids=(), supersedes_id=finding.id)


def invalidate(findings: tuple[Finding, ...], finding_id: str) -> tuple[Finding, ...]:
    """Invalidate validated dependents transitively; no shared-state promotion occurs here."""
    if finding_id not in {f.id for f in findings}:
        raise DomainError('unknown finding')
    affected = {finding_id}
    while True:
        expanded = affected | {f.id for f in findings if affected.intersection(f.dependency_finding_ids)}
        if expanded == affected:
            break
        affected = expanded
    return tuple(transition(f, FindingStatus.INVALIDATED)
                 if f.id in affected and f.status == FindingStatus.VALIDATED else f for f in findings)


def validate_records(records):
    """Snapshot invariants live in ``invariants``; this stays the public entry point.

    The deferred import keeps the dependency one-way: invariants know every record type,
    records know none of the checks.
    """
    from .invariants import validate_records as _validate
    _validate(records)
