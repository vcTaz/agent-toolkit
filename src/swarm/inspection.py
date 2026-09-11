"""Structured inspection of one persisted run.

Everything here is a *projection of stored records*, never a generated explanation. When
this module says a finding was validated, it says so by naming the review that validated
it, the host verification trail that review recorded, and the tool arguments and result the
verifier read. When it says a propagation reached a branch, it names the score and the
matched features the decision itself stored.

Two things are deliberately withheld. Provider transcripts never leave the execution seam,
so there is nothing here to print; and a context snapshot is summarised by its hash and its
selected/omitted identities rather than reproduced, because a run's inspection surface is
not a dump of its inputs.
"""
import json
from . import completion, metrics as metrics_module, timeline
from .domain import (Agent, AgentGroup, Assignment, Conflict, Cycle, Finding, FindingStatus,
                     Message, Propagation, Result, ResultStatus, ReviewKind, ReviewRecord, Run,
                     SwarmState, Task, TaskRequest, TerminalReport)
from .events import EventType

SECTIONS = ('run', 'criteria', 'result', 'results', 'outcome', 'metrics', 'tasks', 'agents',
            'assignments', 'groups', 'findings', 'reviews', 'evidence', 'conflicts',
            'propagations', 'cycles', 'messages', 'task_requests', 'state', 'provenance',
            'timeline', 'events')
DEFAULT_SECTIONS = ('run', 'criteria', 'result', 'outcome', 'metrics', 'provenance')


class UnknownRun(LookupError):
    """No such run in this database."""


def _evidence(item):
    return {'kind': item.kind, 'tool_name': item.tool_name, 'reference': item.reference,
            'verified': item.verified, 'arguments': item.arguments_json, 'value': item.value}


def _of(records, kind, key=lambda r: r.id):
    return sorted((r for r in records if isinstance(r, kind)), key=key)


# --- record views ------------------------------------------------------------------

def _run_view(run):
    return {'id': run.id, 'objective': run.objective, 'state': str(run.state),
            'stop_reason': run.stop_reason, 'result_id': run.result_id,
            'candidate_result_id': run.candidate_result_id, 'outcome_id': run.outcome_id,
            'work_stop_reason': run.work_stop_reason, 'cycle': run.cycle,
            'provider_requests': run.provider_requests, 'tool_calls': run.tool_calls,
            'repair_rounds': run.repair_rounds,
            'presentation_revisions': run.presentation_revisions,
            'synthesis_attempts': run.synthesis_attempts, 'permissions': list(run.permissions),
            'created_at': run.created_at, 'updated_at': run.updated_at,
            'limits': {'provider_request_limit': run.provider_request_limit,
                       'tool_call_limit': run.tool_call_limit,
                       'concurrency_limit': run.concurrency_limit, 'task_limit': run.task_limit,
                       'assignment_attempt_limit': run.assignment_attempt_limit,
                       'cycle_limit': run.cycle_limit, 'no_progress_limit': run.no_progress_limit,
                       'repair_round_limit': run.repair_round_limit,
                       'presentation_revision_limit': run.presentation_revision_limit,
                       'synthesis_attempt_limit': run.synthesis_attempt_limit,
                       'execution_timeout': run.execution_timeout,
                       'deadline_at': run.deadline_at}}


def _criteria_view(snapshot, run_id):
    """Each acceptance criterion with the gate's own current reading of it."""
    readiness = {entry.criterion_id: entry
                 for entry in completion.criterion_readiness(snapshot, run_id)}
    views = []
    for criterion in snapshot[run_id].acceptance_criteria:
        entry = readiness.get(criterion.id)
        views.append({'id': criterion.id, 'description': criterion.description,
                      'verifier_kind': criterion.verifier_kind, 'required': criterion.required,
                      **(entry.detail() if entry else {})})
    return tuple(views)


def _task_view(task):
    return {'id': task.id, 'kind': task.kind, 'status': str(task.status),
            'objective': task.objective, 'group_id': task.group_id, 'priority': task.priority,
            'required': task.required, 'outcome': task.outcome,
            'dependency_ids': list(task.dependency_ids), 'tags': list(task.tags),
            'acceptance_criterion_ids': list(task.acceptance_criterion_ids),
            'required_tools': list(task.required_tools),
            'target_finding_id': task.target_finding_id,
            'target_result_id': task.target_result_id,
            'source_review_id': task.source_review_id,
            'source_result_id': task.source_result_id,
            'source_propagation_id': task.source_propagation_id,
            'required_finding_ids': list(task.required_finding_ids),
            'revision': task.revision, 'created_at': task.created_at}


def _agent_view(agent):
    return {'id': agent.id, 'status': str(agent.status), 'group_id': agent.group_id,
            'role_id': agent.role_id, 'assignment_id': agent.assignment_id,
            'provider_key': agent.provider_key, 'permissions': list(agent.permissions)}


def _assignment_view(assignment):
    """Provenance without the payload: what was pinned, not what was said."""
    return {'id': assignment.id, 'task_id': assignment.task_id, 'agent_id': assignment.agent_id,
            'role_id': assignment.role_id, 'role_version': assignment.role_version,
            'status': str(assignment.status), 'attempt': assignment.attempt,
            'group_id': assignment.group_id, 'context_hash': assignment.context_hash,
            'input_finding_ids': list(assignment.input_finding_ids),
            'input_finding_revisions': list(assignment.input_finding_revisions),
            'propagation_ids': list(assignment.propagation_ids),
            'criterion_ids': list(assignment.criterion_ids),
            'tool_names': list(assignment.tool_names), 'result_id': assignment.result_id,
            'result_revision': assignment.result_revision,
            'started_at': assignment.started_at, 'ended_at': assignment.ended_at}


def _group_view(group):
    return {'id': group.id, 'status': str(group.status), 'stop_reason': group.stop_reason,
            'agent_ids': list(group.agent_ids), 'task_ids': list(group.task_ids),
            'tags': list(group.tags), 'idle_cycles': group.idle_cycles,
            'progress_cycle': group.progress_cycle,
            'progress_signature': group.progress_signature[:16]}


def _finding_view(finding, snapshot):
    """A claim with the exact reason its lifecycle reached where it is."""
    reviews = [snapshot[i] for i in finding.review_ids if isinstance(snapshot.get(i), ReviewRecord)]
    verified = [_evidence(item) for review in reviews for item in review.evidence if item.verified]
    return {'id': finding.id, 'status': str(finding.status), 'claim': finding.claim,
            'task_id': finding.task_id, 'assignment_id': finding.assignment_id,
            'agent_id': getattr(snapshot.get(finding.assignment_id), 'agent_id', None),
            'criterion_ids': list(finding.criterion_ids), 'tags': list(finding.tags),
            'dependency_finding_ids': list(finding.dependency_finding_ids),
            'supersedes_id': finding.supersedes_id, 'revision': finding.revision,
            'review_ids': list(finding.review_ids),
            'evidence': [_evidence(item) for item in finding.evidence],
            'verified_evidence': verified,
            'lifecycle': [{'review_id': r.id, 'kind': str(r.kind), 'decision': str(r.decision),
                           'verification': r.verification,
                           'reviewer': getattr(snapshot.get(r.assignment_id), 'agent_id', None)}
                          for r in reviews],
            'why': _finding_reason(finding, reviews)}


def _finding_reason(finding, reviews):
    """Why this claim stands where it does, in the record's own terms."""
    validating = [r for r in reviews if r.kind == ReviewKind.VALIDATION]
    if finding.status == FindingStatus.VALIDATED:
        last = validating[-1] if validating else None
        return (f'validated by {last.id} ({last.verification})' if last
                else 'validated without a recorded validation review')
    if finding.status == FindingStatus.REJECTED:
        last = validating[-1] if validating else (reviews[-1] if reviews else None)
        return f'rejected by {last.id} ({last.verification or last.summary})' if last else 'rejected'
    if finding.status == FindingStatus.INVALIDATED:
        return 'invalidated: its support stopped standing'
    if finding.status == FindingStatus.SUPERSEDED:
        return 'superseded by a validated replacement'
    return f'{finding.status.lower()}: review is not finished'


def _review_view(review, snapshot):
    return {'id': review.id, 'kind': str(review.kind), 'decision': str(review.decision),
            'target_id': review.target_id, 'target_revision': review.target_revision,
            'assignment_id': review.assignment_id,
            'reviewer': getattr(snapshot.get(review.assignment_id), 'agent_id', None),
            'summary': review.summary, 'verification': review.verification,
            'checks': list(review.checks), 'blocking_issues': list(review.blocking_issues),
            'nonblocking_issues': list(review.nonblocking_issues),
            'resolved_issues': list(review.resolved_issues),
            'criterion_ids': list(review.criterion_ids),
            'unsupported_claims': list(review.unsupported_claims),
            'evidence': [_evidence(item) for item in review.evidence],
            'created_at': review.created_at}


def _evidence_view(records, snapshot):
    """Every piece of host-verified evidence, and the exact claim it was accepted for."""
    entries = []
    for review in _of(records, ReviewRecord):
        for item in review.evidence:
            if not item.verified:
                continue
            target = snapshot.get(review.target_id)
            entries.append({'review_id': review.id, 'target_id': review.target_id,
                            'claim': getattr(target, 'claim', None),
                            'verification': review.verification,
                            'reviewer': getattr(snapshot.get(review.assignment_id),
                                                'agent_id', None), **_evidence(item)})
    return tuple(entries)


def _propagation_view(propagation):
    return {'id': propagation.id, 'kind': str(propagation.kind),
            'status': str(propagation.status), 'status_reason': propagation.status_reason,
            'knowledge_key': propagation.knowledge_key,
            'knowledge_revision': propagation.knowledge_revision,
            'canonical_finding_id': propagation.canonical_finding_id,
            'source_finding_ids': list(propagation.source_finding_ids),
            'target_task_id': propagation.target_task_id,
            'target_group_id': propagation.target_group_id,
            'delivery_key': propagation.delivery_key, 'score': propagation.score,
            'matched_features': list(propagation.matched_features),
            'insight': propagation.insight, 'cycle': propagation.cycle,
            'conflict_id': propagation.conflict_id, 'retracts_id': propagation.retracts_id,
            'outcome': str(propagation.outcome) if propagation.outcome else None,
            'outcome_reason': propagation.outcome_reason,
            'outcome_assignment_id': propagation.outcome_assignment_id,
            'reconsideration_task_id': propagation.reconsideration_task_id,
            'follow_up_task_id': propagation.follow_up_task_id,
            'why': propagation.reason}


def _conflict_view(conflict):
    return {'id': conflict.id, 'kind': str(conflict.kind), 'status': str(conflict.status),
            'finding_ids': list(conflict.finding_ids), 'signature': conflict.signature,
            'reason': conflict.reason, 'criterion_ids': list(conflict.criterion_ids),
            'resolution': conflict.resolution}


def _cycle_view(cycle):
    return {'id': cycle.id, 'number': cycle.number, 'status': str(cycle.status),
            'trigger': cycle.trigger, 'reason': cycle.reason, 'task_ids': list(cycle.task_ids),
            'unresolved': list(cycle.unresolved), 'ended_at': cycle.ended_at}


def _result_view(result, snapshot):
    return {'id': result.id, 'version': result.version, 'status': str(result.status),
            'answer': result.answer, 'criterion_ids': list(result.criterion_ids),
            'coverage': [{'criterion_id': e.criterion_id, 'finding_ids': list(e.finding_ids),
                          'required': e.required} for e in result.coverage],
            'claims': [{'claim': c.claim, 'finding_ids': list(c.finding_ids)}
                       for c in result.claims],
            'finding_ids': list(result.finding_ids),
            'finding_revisions': list(result.finding_revisions),
            'limitations': list(result.limitations),
            'unresolved_issues': list(result.unresolved_issues),
            'supersedes_id': result.supersedes_id, 'review_id': result.review_id,
            'decision': str(result.decision) if result.decision else None,
            'revision_kind': str(result.revision_kind) if result.revision_kind else None,
            'created_by_assignment': result.created_by_assignment,
            'author': getattr(snapshot.get(result.created_by_assignment), 'agent_id', None),
            'created_at': result.created_at}


def _report_view(report):
    return {'id': report.id, 'state': str(report.state), 'stop_reason': report.stop_reason,
            'result_id': report.result_id,
            'validated_finding_ids': list(report.validated_finding_ids),
            'gaps': [{'criterion_id': g.criterion_id, 'reason': g.reason, 'required': g.required,
                      'supporting_ids': list(g.supporting_ids),
                      'conflict_ids': list(g.conflict_ids),
                      'invalidated_support': list(g.invalidated_support)} for g in report.gaps],
            'branch_stops': list(report.branch_stops),
            'final_review_issues': list(report.final_review_issues),
            'unconsumed_knowledge': list(report.unconsumed_knowledge),
            'created_at': report.created_at}


def _state_view(state):
    return {'id': state.id, 'revision': state.revision,
            'active_task_ids': list(state.active_task_ids),
            'validated_findings': list(state.validated_findings),
            'candidate_findings': list(state.candidate_findings),
            'invalidated_findings': list(state.invalidated_findings),
            'rejected_findings': list(state.rejected_findings),
            'failed_approaches': list(state.failed_approaches),
            'open_conflict_ids': list(state.open_conflict_ids),
            'active_group_ids': list(state.active_group_ids)}


# --- provenance ---------------------------------------------------------------------

def _details(events, kind):
    return [json.loads(event.detail_json) for event in events if event.type == kind]


def provenance(snapshot, run_id, events):
    """The recorded answers to "why did this run end where it did?"

    Every entry is a stored decision — a gate evaluation, a repair refusal, a review gap, a
    branch stop — rather than a narrative composed after the fact.
    """
    run = snapshot[run_id]
    report = next((r for r in snapshot.values() if isinstance(r, TerminalReport)
                   and r.run_id == run_id), None)
    gates = _details(events, EventType.SYNTHESIS_GATE_EVALUATED)
    repairs = _details(events, EventType.REPAIR_WORK_CREATED)
    accepted = snapshot.get(run.result_id) if run.result_id else None
    support = []
    if isinstance(accepted, Result):
        for entry in accepted.coverage:
            support.append({'criterion_id': entry.criterion_id, 'required': entry.required,
                            'finding_ids': list(entry.finding_ids),
                            'claims': [snapshot[i].claim for i in entry.finding_ids
                                       if isinstance(snapshot.get(i), Finding)]})
    return {
        'terminal_state': str(run.state),
        'stop_reason': run.stop_reason,
        'terminal_report': _report_view(report) if report is not None else None,
        'final_gate': gates[-1] if gates else None,
        'gate_evaluations': len(gates),
        'repair_decisions': [{'admitted': entry.get('admitted'),
                              'criterion_id': entry.get('criterion_id'),
                              'gap': entry.get('gap'), 'reason': entry.get('reason'),
                              'round': entry.get('round'), 'task_id': entry.get('task_id'),
                              'review_id': entry.get('review_id')} for entry in repairs],
        'review_gaps': [{'task_id': entry.get('task_id'), 'reason': entry.get('reason'),
                         'target_finding_id': entry.get('target_finding_id')}
                        for entry in _details(events, EventType.REVIEW_REJECTED)],
        'branch_stops': [{'group_id': entry.get('group_id'), 'reason': entry.get('reason')}
                         for entry in _details(events, EventType.BRANCH_TERMINATED)],
        'coverage_gaps': (_details(events, EventType.COVERAGE_GAP) or [{}])[-1].get('gaps', []),
        'result_support': support,
        'final_reviews': [{'id': r.id, 'decision': str(r.decision), 'verification': r.verification,
                           'target_id': r.target_id, 'criterion_ids': list(r.criterion_ids),
                           'blocking_issues': list(r.blocking_issues)}
                          for r in _of(snapshot.values(), ReviewRecord)
                          if r.kind == ReviewKind.FINAL],
    }


# --- assembly -------------------------------------------------------------------------

def current_result(snapshot, run_id):
    """The accepted version if there is one, otherwise the latest version written."""
    run = snapshot[run_id]
    if run.result_id and isinstance(snapshot.get(run.result_id), Result):
        return snapshot[run.result_id]
    versions = _of(snapshot.values(), Result, key=lambda r: r.version)
    return versions[-1] if versions else None


def build(inspection, run_id, *, sections=None, full=False):
    """Assemble one run's inspection from a repository ``Inspection``."""
    records = inspection.records
    snapshot = {record.id: record for record in records}
    run = snapshot.get(run_id)
    if not isinstance(run, Run):
        raise UnknownRun(run_id)
    wanted = set(sections or SECTIONS)
    events = inspection.events
    latest = current_result(snapshot, run_id)
    report = next((r for r in records if isinstance(r, TerminalReport)), None)
    state = next((r for r in records if isinstance(r, SwarmState)), None)
    builders = {
        'run': lambda: _run_view(run),
        'criteria': lambda: list(_criteria_view(snapshot, run_id)),
        'result': lambda: _result_view(latest, snapshot) if latest is not None else None,
        'results': lambda: [_result_view(r, snapshot)
                            for r in _of(records, Result, key=lambda x: x.version)],
        'outcome': lambda: _report_view(report) if report is not None else None,
        'metrics': lambda: metrics_module.metrics(snapshot, run_id, events),
        'tasks': lambda: [_task_view(t) for t in _of(records, Task)],
        'agents': lambda: [_agent_view(a) for a in _of(records, Agent)],
        'assignments': lambda: [_assignment_view(a) for a in _of(records, Assignment)],
        'groups': lambda: [_group_view(g) for g in _of(records, AgentGroup)],
        'findings': lambda: [_finding_view(f, snapshot) for f in _of(records, Finding)],
        'reviews': lambda: [_review_view(r, snapshot) for r in _of(records, ReviewRecord)],
        'evidence': lambda: list(_evidence_view(records, snapshot)),
        'conflicts': lambda: [_conflict_view(c) for c in _of(records, Conflict)],
        'propagations': lambda: [_propagation_view(p) for p in _of(records, Propagation)],
        'cycles': lambda: [_cycle_view(c) for c in _of(records, Cycle, key=lambda x: x.number)],
        'messages': lambda: [{'id': m.id, 'sender': m.sender, 'recipient': m.recipient,
                              'kind': m.kind, 'status': str(m.status), 'summary': m.summary,
                              'reference_ids': list(m.reference_ids),
                              'delivered_to': list(m.delivered_to)}
                             for m in _of(records, Message)],
        'task_requests': lambda: [{'id': r.id, 'assignment_id': r.assignment_id,
                                   'parent_task_id': r.parent_task_id, 'objective': r.objective,
                                   'fingerprint': r.fingerprint,
                                   'note': 'an admitted proposal; never schedulable work'}
                                  for r in _of(records, TaskRequest)],
        'state': lambda: _state_view(state) if state is not None else None,
        'provenance': lambda: provenance(snapshot, run_id, events),
        'timeline': lambda: list(timeline.build(events, full=full)),
        'events': lambda: [{'sequence': e.sequence, 'type': str(e.type),
                            'timestamp': e.timestamp, 'record_id': e.record_id}
                           for e in events],
    }
    report_out = {'run_id': run_id, 'status': inspection.status, 'sections': sorted(wanted)}
    for name in SECTIONS:
        if name in wanted:
            report_out[name] = builders[name]()
    return report_out


def list_runs(repository):
    """Every run this database holds, newest first."""
    return repository.runs()
