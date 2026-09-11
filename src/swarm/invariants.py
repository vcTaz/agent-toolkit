"""Snapshot invariants: reference integrity, classification consistency and acyclicity.

Split from ``domain`` at Stage 6 for size, not for a change of responsibility. These checks
run inside the repository transaction against a *complete* canonical snapshot, never against
a partial model response, and they are the last line of defence behind the controller's own
admission policies.
"""
from .domain import (Agent, AgentGroup, Assignment, AssignmentStatus, Conflict, ConflictStatus,
                     Cycle, CycleStatus, DomainError, Finding, FindingStatus, GroupStatus, Message,
                     Propagation, PropagationKind, PropagationStatus, ReconsiderationOutcome,
                     Result, ResultStatus, ReviewDecision, ReviewKind, ReviewRecord, Role, Run,
                     RunRecord, RunState, SwarmState, Task, TaskRequest, TerminalReport,
                     REVIEW_DECISIONS, blocking_keys)


class _Graph:
    """One complete canonical snapshot: identity index and reference resolution."""

    def __init__(self, records):
        from .serialization import dumps, loads
        self.records, self.index, self.reviews = records, {}, {}
        for record in records:
            loads(dumps(record))  # runtime type/shape checks also apply to direct constructors
            if record.id in self.index:
                raise DomainError(f'duplicate identity: {record.id}')
            self.index[record.id] = record
            if isinstance(record, ReviewRecord):
                self.reviews.setdefault(record.target_id, []).append(record)

    def ref(self, owner, identity, expected):
        target = self.index.get(identity)
        if not isinstance(target, expected):
            raise DomainError(f'unknown or wrong-type reference: {identity}')
        if isinstance(target, Run) and target.id != owner.run_id:
            raise DomainError('cross-run reference')
        if isinstance(target, RunRecord) and target.run_id != owner.run_id:
            raise DomainError('cross-run reference')
        return target

    def each(self, kind):
        return (record for record in self.records if isinstance(record, kind))

    def blocking(self, target_id):
        """Every blocking issue key recorded against one target, whoever raised it."""
        return {key for review in self.reviews.get(target_id, ()) for key in blocking_keys(review)}


def _check_task(record, graph):
    if record.role_id:
        graph.ref(record, record.role_id, Role)
    for identity in record.required_finding_ids + record.candidate_finding_ids:
        graph.ref(record, identity, Finding)
    if record.target_finding_id:
        graph.ref(record, record.target_finding_id, Finding)
    if record.target_finding_id and record.target_result_id:
        raise DomainError('a review task targets a finding or a result, never both')
    for identity, kind in ((record.target_result_id, Result), (record.source_result_id, Result),
                           (record.source_review_id, ReviewRecord)):
        if identity:
            graph.ref(record, identity, kind)
    if record.source_propagation_id:
        graph.ref(record, record.source_propagation_id, Propagation)
    if not set(record.acceptance_criterion_ids) <= {c.id for c in graph.index[record.run_id].acceptance_criteria}:
        raise DomainError('unknown criterion')
    for identity in record.dependency_ids:
        graph.ref(record, identity, Task)
    if record.parent_task_id:
        graph.ref(record, record.parent_task_id, Task)
    if record.assignment_id and graph.ref(record, record.assignment_id, Assignment).task_id != record.id:
        raise DomainError('task assignment mismatch')
    if record.group_id:
        graph.ref(record, record.group_id, AgentGroup)


def _check_finding(record, graph):
    graph.ref(record, record.task_id, Task)
    if graph.ref(record, record.assignment_id, Assignment).task_id != record.task_id:
        raise DomainError('finding assignment/task mismatch')
    for identity in record.dependency_finding_ids + record.related_finding_ids:
        graph.ref(record, identity, Finding)
    if record.supersedes_id:
        graph.ref(record, record.supersedes_id, Finding)
    for identity in record.review_ids:
        if graph.ref(record, identity, ReviewRecord).target_id != record.id:
            raise DomainError('review target mismatch')
    if record.status != FindingStatus.VALIDATED:
        return
    if any(graph.ref(record, d, Finding).status != FindingStatus.VALIDATED
           for d in record.dependency_finding_ids):
        raise DomainError('validated finding has nonvalidated dependency')
    # Validated knowledge answers its critics: every blocking issue raised against this
    # finding must be named by a passing validation review, not merely outvoted.
    reviews = [graph.index[i] for i in record.review_ids]
    raised = {key for r in reviews if r.kind == ReviewKind.CRITICISM for key in blocking_keys(r)}
    addressed = {key for r in reviews if r.kind == ReviewKind.VALIDATION
                 and r.decision == ReviewDecision.PASS for key in r.resolved_issues}
    if raised - addressed:
        raise DomainError('unresolved blocking critique blocks validated knowledge')


def _check_assignment(record, graph):
    graph.ref(record, record.task_id, Task)
    graph.ref(record, record.agent_id, Agent)
    if graph.ref(record, record.role_id, Role).version != record.role_version:
        raise DomainError('role version mismatch')
    for ids, pins in ((record.input_finding_ids, record.input_finding_revisions),
                      (record.dependency_task_ids, record.dependency_task_revisions),
                      (record.message_ids, record.message_revisions),
                      (record.propagation_ids, record.propagation_revisions),
                      (record.criterion_ids, record.criterion_hashes),
                      (record.tool_names, record.tool_hashes)):
        if len(ids) != len(pins):
            raise DomainError('snapshot pin length mismatch')
    for identity in record.input_finding_ids:
        graph.ref(record, identity, Finding)
    for identity in record.dependency_task_ids:
        graph.ref(record, identity, Task)
    for identity in record.message_ids:
        graph.ref(record, identity, Message)
    for identity in record.propagation_ids:
        graph.ref(record, identity, Propagation)
    if (record.result_id is not None) != (record.result_revision > 0):
        raise DomainError('a pinned result needs its revision, and only a pinned result has one')
    if record.result_id:
        graph.ref(record, record.result_id, Result)
    if record.group_id:
        graph.ref(record, record.group_id, AgentGroup)
    if record.state_id:
        graph.ref(record, record.state_id, SwarmState)


def _check_review(record, graph):
    reviewer = graph.ref(record, record.assignment_id, Assignment)
    target = graph.ref(record, record.target_id, (Finding, Run, Result))
    if record.decision not in REVIEW_DECISIONS[record.kind]:
        raise DomainError('decision is not admissible for this review kind')
    if not set(record.resolved_issues) <= graph.blocking(record.target_id):
        raise DomainError('resolved issue does not name a recorded blocking issue')
    if record.criterion_ids and not set(record.criterion_ids) <= {
            c.id for c in graph.index[record.run_id].acceptance_criteria}:
        raise DomainError('unknown criterion')
    if (record.criterion_ids or record.unsupported_claims) and record.kind != ReviewKind.FINAL:
        raise DomainError('only a final review names criteria and unsupported claims')
    if isinstance(target, Result):
        # The one structural independence rule the MVP requires: whoever wrote the answer
        # may not be the identity that judges it.
        if record.kind != ReviewKind.FINAL:
            raise DomainError('only a final review targets a result version')
        if reviewer.agent_id == graph.ref(target, target.created_by_assignment, Assignment).agent_id:
            raise DomainError('the final reviewer must differ from the synthesizer')
        return
    if record.kind == ReviewKind.FINAL:
        raise DomainError('a final review targets a result version')
    if not isinstance(target, Finding):
        return
    if reviewer.agent_id == graph.ref(target, target.assignment_id, Assignment).agent_id:
        raise DomainError('reviewer must be a different agent')
    # Generation, criticism and validation are three identities, not two roles.
    if record.kind == ReviewKind.VALIDATION and any(
            reviewer.agent_id == graph.index[r.assignment_id].agent_id
            for r in graph.reviews.get(record.target_id, ())
            if r.kind == ReviewKind.CRITICISM and r.assignment_id in graph.index):
        raise DomainError('validator must differ from the critic of the same finding')


def _check_conflict(record, graph):
    if len(record.finding_ids) < 2 or len(set(record.finding_ids)) != len(record.finding_ids):
        raise DomainError('a conflict needs at least two distinct findings')
    if (tuple(sorted(record.finding_ids)) != record.finding_ids
            or len(record.finding_ids) != len(record.finding_revisions)):
        raise DomainError('conflict participants must be sorted and revision-pinned')
    for identity in record.finding_ids:
        graph.ref(record, identity, Finding)
    if (record.status == ConflictStatus.RESOLVED) != bool(record.resolution and record.resolved_at):
        raise DomainError('conflict resolution must accompany the RESOLVED status')


def _check_propagation(record, graph):
    """A delivery decision must name real, current-run knowledge and exactly one target."""
    graph.ref(record, record.canonical_finding_id, Finding)
    for identity in record.source_finding_ids:
        graph.ref(record, identity, Finding)
    graph.ref(record, record.target_task_id, Task)
    if record.target_group_id:
        graph.ref(record, record.target_group_id, AgentGroup)
    if record.conflict_id:
        graph.ref(record, record.conflict_id, Conflict)
    for identity in (record.reconsideration_task_id, record.follow_up_task_id):
        if identity:
            graph.ref(record, identity, Task)
    if record.outcome_assignment_id:
        graph.ref(record, record.outcome_assignment_id, Assignment)
    if not record.knowledge_key or not record.delivery_key:
        raise DomainError('a propagation needs a knowledge identity and a delivery key')
    if (record.kind == PropagationKind.RETRACTION) != bool(record.retracts_id):
        raise DomainError('a retraction names the delivery it retracts, and only a retraction does')
    if record.retracts_id:
        retracted = graph.ref(record, record.retracts_id, Propagation)
        if retracted.target_task_id != record.target_task_id:
            raise DomainError('a retraction must reach the target that received the knowledge')
    if (record.kind == PropagationKind.CONFLICT) != bool(record.conflict_id):
        raise DomainError('a conflict propagation names its conflict, and only it does')
    # An outcome is the record of a consumed delivery. It survives a later retraction — the
    # branch really did answer — but it cannot exist without a delivery having been consumed.
    if record.status == PropagationStatus.CONSUMED and record.outcome is None:
        raise DomainError('a consumed propagation records exactly one reconsideration outcome')
    if record.outcome is not None and record.status not in (PropagationStatus.CONSUMED,
                                                            PropagationStatus.RETRACTED):
        raise DomainError('only a consumed delivery carries a reconsideration outcome')
    if record.follow_up_task_id and record.outcome != ReconsiderationOutcome.FOLLOW_UP_REQUESTED:
        raise DomainError('follow-up work requires a FOLLOW_UP_REQUESTED outcome')


def _check_cycle(record, graph):
    if record.number < 1 or not record.trigger:
        raise DomainError('a cycle needs a positive number and a recorded trigger')
    for identity in record.task_ids:
        graph.ref(record, identity, Task)
    if (record.status == CycleStatus.CLOSED) != bool(record.ended_at):
        raise DomainError('a closed cycle records when it ended')


def _check_result(record, graph):
    """A result version names real, pinned support and cites nothing it did not reference."""
    graph.ref(record, record.created_by_assignment, Assignment)
    if len(record.finding_ids) != len(record.finding_revisions):
        raise DomainError('result support must be revision-pinned')
    if len(set(record.finding_ids)) != len(record.finding_ids):
        raise DomainError('result support is cited once')
    for identity in record.finding_ids:
        graph.ref(record, identity, Finding)
    if record.supersedes_id:
        graph.ref(record, record.supersedes_id, Result)
    if record.review_id and graph.ref(record, record.review_id, ReviewRecord).target_id != record.id:
        raise DomainError('result review target mismatch')
    if (record.decision is not None) != bool(record.review_id):
        raise DomainError('a judged result names its review, and only a judged one has a decision')
    if record.status == ResultStatus.ACCEPTED and record.decision != ReviewDecision.PASS:
        raise DomainError('an accepted result carries a passing final review')
    criteria = {c.id for c in graph.index[record.run_id].acceptance_criteria}
    if not set(record.criterion_ids) <= criteria:
        raise DomainError('unknown criterion')
    cited = set(record.finding_ids)
    for entry in record.coverage:
        if entry.criterion_id not in criteria:
            raise DomainError('unknown criterion')
        if not set(entry.finding_ids) <= cited:
            raise DomainError('result coverage cites support the result did not reference')
    for claim in record.claims:
        if not set(claim.finding_ids) <= cited:
            raise DomainError('result claim cites support the result did not reference')


def _check_report(record, graph):
    if record.state not in (RunState.COMPLETED, RunState.EXHAUSTED, RunState.FAILED,
                            RunState.CANCELLED):
        raise DomainError('a terminal report records a terminal state')
    if (record.state == RunState.COMPLETED) != bool(record.result_id):
        raise DomainError('only a completed run reports an accepted result')
    if record.result_id and graph.ref(record, record.result_id, Result).status != ResultStatus.ACCEPTED:
        raise DomainError('a completed run reports the accepted result version')
    for identity in record.validated_finding_ids:
        if graph.ref(record, identity, Finding).status != FindingStatus.VALIDATED:
            raise DomainError('terminal report knowledge classification mismatch')
    criteria = {c.id for c in graph.index[record.run_id].acceptance_criteria}
    if any(gap.criterion_id not in criteria for gap in record.gaps):
        raise DomainError('unknown criterion')


def _check_run(record, graph):
    """COMPLETED and an accepted result are one fact, committed together."""
    for identity in (record.result_id, record.candidate_result_id):
        if identity is not None:
            result = graph.index.get(identity)
            if not isinstance(result, Result) or result.run_id != record.id:
                raise DomainError('unknown or wrong-type result reference')
    if record.result_id and graph.index[record.result_id].status != ResultStatus.ACCEPTED:
        raise DomainError('a run result must name the accepted result version')
    if (record.state == RunState.COMPLETED) != bool(record.result_id):
        raise DomainError('COMPLETED requires an accepted result, and only COMPLETED has one')
    if record.outcome_id is not None:
        report = graph.index.get(record.outcome_id)
        if not isinstance(report, TerminalReport) or report.run_id != record.id:
            raise DomainError('unknown or wrong-type terminal report reference')
        if report.state != record.state:
            raise DomainError('the terminal report must record the run terminal state')
    if record.repair_rounds > record.repair_round_limit:
        raise DomainError('repair rounds exceed the run limit')
    if record.presentation_revisions > record.presentation_revision_limit:
        raise DomainError('presentation revisions exceed the run limit')
    if record.synthesis_attempts > record.synthesis_attempt_limit:
        raise DomainError('synthesis attempts exceed the run limit')


def _check_state(record, graph):
    for identity in record.active_task_ids:
        graph.ref(record, identity, Task)
    for identity in record.active_group_ids:
        graph.ref(record, identity, AgentGroup)
    for identity in record.open_conflict_ids:
        if graph.ref(record, identity, Conflict).status != ConflictStatus.OPEN:
            raise DomainError('shared-state conflict classification mismatch')
    for attribute, allowed in (('validated_findings', (FindingStatus.VALIDATED,)),
                               ('candidate_findings', (FindingStatus.PROPOSED, FindingStatus.CRITIQUED)),
                               ('invalidated_findings', (FindingStatus.INVALIDATED,)),
                               ('rejected_findings', (FindingStatus.REJECTED,))):
        if any(graph.ref(record, identity, Finding).status not in allowed
               for identity in getattr(record, attribute)):
            raise DomainError('shared-state classification mismatch')


def _check_message(record, graph):
    for address, special in ((record.sender, ('system', 'orchestrator')),
                             (record.recipient, ('orchestrator',))):
        if address in special:
            continue
        prefix, separator, identity = address.partition(':')
        if not separator or prefix not in ('agent', 'group'):
            raise DomainError('invalid message address')
        graph.ref(record, identity, Agent if prefix == 'agent' else AgentGroup)
    for identity in record.reference_ids:
        graph.ref(record, identity, RunRecord)


def _check_agent(record, graph):
    if record.role_id:
        graph.ref(record, record.role_id, Role)
    if record.assignment_id and graph.ref(record, record.assignment_id, Assignment).agent_id != record.id:
        raise DomainError('agent assignment mismatch')
    if record.group_id:
        graph.ref(record, record.group_id, AgentGroup)


def _check_group(record, graph):
    for identity in record.agent_ids:
        graph.ref(record, identity, Agent)
    for identity in record.task_ids:
        graph.ref(record, identity, Task)
    # A branch is never marked stopped while it is still open for work.
    if record.stop_reason and record.status != GroupStatus.CLOSED:
        raise DomainError('an active branch cannot carry a stop reason')


def _check_request(record, graph):
    graph.ref(record, record.assignment_id, Assignment)
    graph.ref(record, record.parent_task_id, Task)
    for identity in record.dependency_ids:
        graph.ref(record, identity, Task)


CHECKS = ((Task, _check_task), (Finding, _check_finding), (Assignment, _check_assignment),
          (TaskRequest, _check_request), (Agent, _check_agent), (AgentGroup, _check_group),
          (ReviewRecord, _check_review), (Conflict, _check_conflict), (Message, _check_message),
          (Propagation, _check_propagation), (Cycle, _check_cycle), (SwarmState, _check_state),
          (Result, _check_result), (TerminalReport, _check_report), (Run, _check_run))


def _check_singletons(graph):
    states = list(graph.each(SwarmState))
    if len({state.run_id for state in states}) != len(states):
        raise DomainError('a run has at most one shared-state projection')
    active = [a for a in graph.each(Assignment) if a.status == AssignmentStatus.RUNNING]
    if len({a.agent_id for a in active}) != len(active) or len({a.task_id for a in active}) != len(active):
        raise DomainError('only one active assignment per agent and task')
    # Idempotency is a stored constraint, not a best-effort query: the same knowledge cannot
    # be delivered twice to the same target at the same revision.
    keys = [p.delivery_key for p in graph.each(Propagation)]
    if len(set(keys)) != len(keys):
        raise DomainError('duplicate propagation delivery key')
    open_cycles = [c for c in graph.each(Cycle) if c.status == CycleStatus.OPEN]
    if len({c.run_id for c in open_cycles}) != len(open_cycles):
        raise DomainError('a run has at most one open cycle')
    numbers = [(c.run_id, c.number) for c in graph.each(Cycle)]
    if len(set(numbers)) != len(numbers):
        raise DomainError('cycle numbers are unique within a run')
    accepted = [r for r in graph.each(Result) if r.status == ResultStatus.ACCEPTED]
    if len({r.run_id for r in accepted}) != len(accepted):
        raise DomainError('a run accepts at most one result')
    versions = [(r.run_id, r.version) for r in graph.each(Result)]
    if len(set(versions)) != len(versions):
        raise DomainError('result versions are unique within a run')
    reports = list(graph.each(TerminalReport))
    if len({r.run_id for r in reports}) != len(reports):
        raise DomainError('a run ends once')


def _check_acyclic(graph):
    for cls, edge in ((Task, 'dependency_ids'), (Task, 'parent_task_id'),
                      (Finding, 'dependency_finding_ids'), (Finding, 'supersedes_id'),
                      (Result, 'supersedes_id')):
        active, done = set(), set()
        for start in graph.each(cls):
            stack = [(start.id, False)]
            while stack:
                identity, expanded = stack.pop()
                if expanded:
                    active.discard(identity)
                    done.add(identity)
                    continue
                if identity in done:
                    continue
                if identity in active:
                    raise DomainError('dependency cycle')
                active.add(identity)
                stack.append((identity, True))
                links = getattr(graph.index[identity], edge)
                stack += [(link, False) for link in ((links,) if isinstance(links, str) else links or ())]


def validate_records(records):
    """Validate a complete canonical snapshot, not a partial model response."""
    graph = _Graph(tuple(records))
    for record in graph.records:
        if isinstance(record, RunRecord):
            graph.ref(record, record.run_id, Run)
        for kind, check in CHECKS:
            if isinstance(record, kind):
                check(record, graph)
    _check_singletons(graph)
    _check_acyclic(graph)
