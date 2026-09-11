"""Shared Stage-5 fixtures: a deterministic role-dispatched provider and run seeding."""
import json
from swarm.contracts import ModelResponse, ToolCall
from swarm.domain import (Agent, AgentGroup, Assignment, Criterion, Evidence, Finding, FindingStatus,
                          ReviewDecision, ReviewKind, ReviewRecord, Role, RoleName, Run, SwarmState,
                          Task, now)
from swarm.events import EventDraft, EventType
from swarm.roles import default_roles, role_id
from swarm.tools.arithmetic import ArithmeticTool

CRITERIA = (Criterion(id='c1', description='integer sums are correct', verifier_kind='arithmetic'),)
TOOLS = {'arithmetic': ArithmeticTool()}


def seed(repo, run_id, *records):
    repo.commit(run_id, records, [EventDraft(type=EventType.RECORD_CHANGED, record_id=r.id,
                                             record_revision=r.revision) for r in records])


def run_record(**kwargs):
    return Run(id='r', objective='sum two integer lists', acceptance_criteria=CRITERIA,
               permissions=('arithmetic',), concurrency_limit=2, **kwargs)


def agent(identity, group_id=None):
    return Agent(id=identity, run_id='r', group_id=group_id, permissions=('arithmetic',))


def explore(identity, numbers, group_id=None, **kwargs):
    return Task(id=identity, run_id='r', objective=f'sum {numbers}', description=json.dumps(numbers),
                group_id=group_id, acceptance_criterion_ids=('c1',), required_tools=('arithmetic',),
                **kwargs)


def call(name, arguments):
    payload = json.dumps(arguments, sort_keys=True)
    return ModelResponse(tool_calls=(ToolCall(id=f'call-{abs(hash(payload)) % 10**6}', name=name,
                                              arguments_json=payload),))


def done(**extra):
    return ModelResponse(content=json.dumps({'status': 'SUCCEEDED', 'summary': 'ok', **extra}))


class Provider:
    """Dispatches on role instructions. Its confident answer is never verification."""

    def __init__(self, *, wrong=(), critic=None, validator=None, explorer=None, before=None):
        self.wrong, self.calls = dict(wrong), []
        self.critic, self.validator, self.explorer, self.before = critic, validator, explorer, before

    async def generate(self, request):
        instructions = request.messages[0].content
        tool = json.loads(request.messages[-1].content) if request.messages[-1].role == 'tool' else None
        context = json.loads(json.loads(request.messages[1].content)['context'])
        role = ('explorer' if instructions.startswith('Investigate')
                else 'validator' if instructions.startswith('Independently') else 'critic')
        self.calls.append((role, context['task']['id']))
        if self.before is not None:
            self.before(role, context)
        if role == 'explorer':
            return self._explore(context, tool)
        return self._review(context, tool, role)

    def _explore(self, context, tool):
        if self.explorer is not None:
            return self.explorer(context, tool)
        numbers = json.loads(context['task']['description'])
        total = self.wrong.get(context['task']['id'], sum(numbers))
        if tool is None:
            return call('arithmetic', {'numbers': numbers, 'expected': total})
        return done(findings=[{'claim': f'sum({numbers}) = {total}', 'evidence_ids': [tool['id']]}])

    def _review(self, context, tool, role):
        hook = self.critic if role == 'critic' else self.validator
        if hook is not None:
            return hook(context, tool)
        target = next(f for f in context['findings'] if f['id'] == context['target_id'])
        if role == 'validator' and tool is None:
            claim = target['claim']
            numbers = json.loads(claim[claim.index('['):claim.index(']') + 1])
            return call('arithmetic', {'numbers': numbers, 'expected': int(claim.split('=')[-1])})
        review = {'target_id': target['id'], 'target_revision': target['revision'],
                  'decision': 'PASS', 'summary': f'{role} finished'}
        if role == 'validator':
            review['evidence_ids'] = [tool['id']]
            review['checks'] = ['recomputed the sum with the trusted tool']
            review['resolved_issues'] = [issue['key'] for r in context['reviews']
                                         for issue in r['blocking_issues']]
        return done(review=review)


def target_of(context):
    return next(f for f in context['findings'] if f['id'] == context['target_id'])


def review_payload(context, decision, **extra):
    target = target_of(context)
    return done(review={'target_id': target['id'], 'target_revision': target['revision'],
                        'decision': decision, 'summary': 'scripted', **extra})


def setup_run(repo, tasks, agents, *, run=None, groups=(), extra=()):
    seed(repo, 'r', run or run_record(), *default_roles(allowed_tools=('arithmetic',)),
         *agents, *groups, *tasks, *extra)


def advance(repo, run_id, identity, *statuses):
    """Walk a seeded fixture record through legal transitions, one commit each."""
    from swarm.domain import transition
    for status in statuses:
        seed(repo, run_id, transition(repo.get(run_id, identity), status))


def complete_task(repo, run_id, task_id, assignment_id=None):
    from swarm.domain import AssignmentStatus, TaskStatus
    advance(repo, run_id, task_id, TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.COMPLETED)
    if assignment_id:
        advance(repo, run_id, assignment_id, AssignmentStatus.RUNNING, AssignmentStatus.COMPLETED)


def reject_finding(repo, run_id, finding_id):
    """Reject a candidate the way the controller would: atomically with the projection."""
    from swarm.knowledge import project
    from swarm.domain import FindingStatus, transition
    snapshot = repo.snapshot(run_id)
    rejected = transition(snapshot[finding_id], FindingStatus.REJECTED)
    merged = dict(snapshot, **{finding_id: rejected})
    updated = project(merged, state_of(merged))
    records = [rejected] + ([updated] if updated else [])
    repo.commit(run_id, records, [EventDraft(type=EventType.FINDING_REJECTED, record_id=r.id,
                                             record_revision=r.revision) for r in records])


def findings(snapshot):
    return sorted((f for f in snapshot.values() if isinstance(f, Finding)), key=lambda f: f.id)


def reviews(snapshot):
    return sorted((r for r in snapshot.values() if isinstance(r, ReviewRecord)), key=lambda r: r.id)


def state_of(snapshot):
    return next(r for r in snapshot.values() if isinstance(r, SwarmState))
