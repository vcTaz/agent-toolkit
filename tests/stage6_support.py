"""Shared Stage-6 fixtures: a reconsidering provider and branch/propagation helpers."""
import json
from stage5_support import call, done, seed  # noqa: F401  (re-exported for Stage-6 tests)
from stage5_support import CRITERIA
from swarm.domain import (Agent, AgentGroup, Assignment, Cycle, Evidence, Finding, FindingStatus,
                          Propagation, PropagationKind, PropagationStatus, Run, SwarmState, Task,
                          TaskStatus)
from swarm.knowledge import project
from swarm.roles import default_roles


class ReconsideringProvider:
    """Deterministic role dispatch that also answers delivered propagations.

    The explorer/critic/validator behaviour matches the Stage-5 fixture; a COLLABORATOR
    working a reconsideration or follow-up task reports a structured outcome for every
    delivery it was asked to consume.
    """

    def __init__(self, *, wrong=(), outcome='NO_CHANGE', reason='the branch rechecked its own sum',
                 collaborator=None, explorer=None, critic=None, validator=None, before=None,
                 silent=False):
        self.wrong, self.calls, self.contexts = dict(wrong), [], []
        self.outcome, self.reason, self.silent = outcome, reason, silent
        self.collaborator, self.explorer = collaborator, explorer
        self.critic, self.validator, self.before = critic, validator, before

    @staticmethod
    def _role(instructions):
        if instructions.startswith('Investigate'):
            return 'explorer'
        if instructions.startswith('Independently'):
            return 'validator'
        if instructions.startswith('Combine'):
            return 'collaborator'
        return 'critic'

    async def generate(self, request):
        tool = json.loads(request.messages[-1].content) if request.messages[-1].role == 'tool' else None
        context = json.loads(json.loads(request.messages[1].content)['context'])
        role = self._role(request.messages[0].content)
        self.calls.append((role, context['task']['id']))
        self.contexts.append((role, context))
        if self.before is not None:
            self.before(role, context)
        if role == 'collaborator':
            return self._reconsider(context, tool)
        if role == 'explorer':
            return self._explore(context, tool)
        return self._review(context, tool, role)

    def _answers(self, context):
        """Any work role may receive a delivery, so any of them can answer one."""
        if self.silent:
            return {}
        answers = [{'propagation_id': entry['id'], 'outcome': self.outcome, 'reason': self.reason}
                   for entry in context['propagations'] if entry['consumable']]
        return {'reconsiderations': answers} if answers else {}

    def _reconsider(self, context, tool):
        if self.collaborator is not None:
            return self.collaborator(context, tool)
        return done(summary='reconsidered', **self._answers(context))

    def _explore(self, context, tool):
        if self.explorer is not None:
            return self.explorer(context, tool)
        numbers = json.loads(context['task']['description'])
        total = self.wrong.get(context['task']['id'], sum(numbers))
        if tool is None:
            return call('arithmetic', {'numbers': numbers, 'expected': total})
        return done(findings=[{'claim': f'sum({numbers}) = {total}', 'evidence_ids': [tool['id']]}],
                    **self._answers(context))

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


def propagations(snapshot, kind=None):
    return sorted((p for p in snapshot.values() if isinstance(p, Propagation)
                   and (kind is None or p.kind == kind)), key=lambda p: p.id)


def insights(snapshot):
    return propagations(snapshot, PropagationKind.INSIGHT)


def retractions_of(snapshot):
    return propagations(snapshot, PropagationKind.RETRACTION)


def delivered(snapshot):
    return [p for p in propagations(snapshot)
            if p.status in (PropagationStatus.DELIVERED, PropagationStatus.CONSUMED)]


def cycles(snapshot):
    return sorted((c for c in snapshot.values() if isinstance(c, Cycle)), key=lambda c: c.number)


def tasks_of(snapshot, kind=None):
    return sorted((t for t in snapshot.values() if isinstance(t, Task)
                   and (kind is None or t.kind == kind)), key=lambda t: t.id)


def groups_of(snapshot):
    return sorted((g for g in snapshot.values() if isinstance(g, AgentGroup)), key=lambda g: g.id)


def events_of(repo, run_id, *types):
    wanted = {str(t) for t in types}
    return [e for e in repo.inspect(run_id).events if str(e.type) in wanted or not wanted]


def detail(event):
    return json.loads(event.detail_json)


def evidence(numbers, expected, reference='seed-1'):
    actual = sum(numbers)
    return Evidence(kind='tool_result', tool_name='arithmetic', reference=reference,
                    arguments_json='{"expected": %d, "numbers": %s}' % (expected, list(numbers)),
                    value='{"actual": %d, "matches": %s}'
                          % (actual, 'true' if actual == expected else 'false'))


class Fixture:
    """A committed-shape snapshot built by hand, so routing is tested without a controller."""

    def __init__(self, **run_fields):
        self.records = {}
        self.serial = 0
        self.workers = {}
        run_fields.setdefault('acceptance_criteria', CRITERIA)
        self.add(Run(id='r', objective='sums', permissions=('arithmetic',), **run_fields))
        for role in default_roles(allowed_tools=('arithmetic',)):
            self.add(role)

    def add(self, record):
        self.records[record.id] = record
        return record

    def group(self, identity, agent_id):
        self.add(Agent(id=agent_id, run_id='r', group_id=identity, permissions=('arithmetic',)))
        self.workers[identity] = agent_id
        return self.add(AgentGroup(id=identity, run_id='r', agent_ids=(agent_id,)))

    def task(self, identity, **fields):
        fields.setdefault('acceptance_criterion_ids', ('c1',))
        return self.add(Task(id=identity, run_id='r', objective=f'work {identity}', **fields))

    def finding(self, identity, task_id, claim, *, numbers=(1, 2), total=3,
                status=FindingStatus.VALIDATED, **fields):
        self.serial += 1
        agent_id = self.workers[self.records[task_id].group_id]
        assignment = self.add(Assignment(id=f'as-{self.serial}', run_id='r', task_id=task_id,
                                         agent_id=agent_id, role_id='role:EXPLORER'))
        fields.setdefault('criterion_ids', ('c1',))
        return self.add(Finding(id=identity, run_id='r', task_id=task_id,
                                assignment_id=assignment.id, claim=claim, status=status,
                                evidence=(evidence(numbers, total, f'ref-{self.serial}'),), **fields))

    def project(self):
        state = next((r for r in self.records.values() if isinstance(r, SwarmState)), None)
        if state is None:
            state = self.add(SwarmState(id='state', run_id='r'))
        updated = project(self.records, state)
        if updated is not None:
            self.records[updated.id] = updated
        return self.records


def standard(**run_fields):
    """One validated fact in branch A, one unrelated open task in branch B."""
    f = Fixture(**run_fields)
    f.group('ga', 'a')
    f.group('gb', 'b')
    f.task('ta', group_id='ga', status=TaskStatus.COMPLETED, tags=('sums',))
    f.task('tb', group_id='gb', tags=('sums',))
    f.finding('fa', 'ta', 'sum([1, 2]) = 3', tags=('sums',))
    return f
