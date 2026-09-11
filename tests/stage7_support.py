"""Shared Stage-7 fixtures: a completing provider and run/result helpers.

The provider adds the two roles Stage 7 schedules for the first time — SYNTHESIZER and
FINAL_REVIEWER — to the Stage-6 reconsidering provider. Its confident answers are still
never verification: every claim it makes is checked by the trusted arithmetic verifier, and
its final reviews are checked against the run's own gate.
"""
import json
from stage5_support import CRITERIA, agent, call, done, explore, run_record, seed  # noqa: F401
from stage6_support import ReconsideringProvider, propagations, tasks_of  # noqa: F401
from swarm.domain import (Agent, AgentGroup, Criterion, Result, ResultStatus, ReviewKind,
                          ReviewRecord, Run, RunState, Task, TerminalReport)
from swarm.roles import default_roles

TWO_CRITERIA = (Criterion(id='c1', description='the first sum is correct', verifier_kind='arithmetic'),
                Criterion(id='c2', description='the second sum is correct', verifier_kind='arithmetic'))
OPTIONAL_SECOND = (TWO_CRITERIA[0],
                   Criterion(id='c2', description='the second sum is correct',
                             verifier_kind='arithmetic', required=False))


def run_with(criteria=TWO_CRITERIA, **fields):
    return Run(id='r', objective='sum two integer lists', acceptance_criteria=criteria,
               permissions=('arithmetic',), concurrency_limit=2, **fields)


def setup_completing_run(repo, tasks, agents, *, run=None, groups=(), extra=()):
    seed(repo, 'r', run or run_with(), *default_roles(allowed_tools=('arithmetic',)),
         *agents, *groups, *tasks, *extra)


def two_branch_run(repo, *, run=None, first=(1, 2, 3), second=(10, 20), workers=('a', 'b'),
                   free=('critic', 'validator', 'writer', 'judge')):
    """Two independent branches, one criterion each, plus an unbranched identity pool.

    Review, synthesis and final review all run outside any branch, so the pool is what the
    independence and reservation rules actually draw on.
    """
    tasks = [explore('ta', list(first), group_id='ga'), explore('tb', list(second), group_id='gb')]
    tasks[1] = Task(id='tb', run_id='r', objective=f'sum {list(second)}',
                    description=json.dumps(list(second)), group_id='gb',
                    acceptance_criterion_ids=('c2',), required_tools=('arithmetic',))
    setup_completing_run(repo, tasks, [agent(workers[0], 'ga'), agent(workers[1], 'gb'),
                                       *(agent(name) for name in free)],
                         run=run,
                         groups=[AgentGroup(id='ga', run_id='r', agent_ids=(workers[0],), task_ids=('ta',)),
                                 AgentGroup(id='gb', run_id='r', agent_ids=(workers[1],), task_ids=('tb',))])
    return tasks


def one_branch_run(repo, *, run=None, numbers=(1, 2, 3), free=('critic', 'validator', 'writer', 'judge')):
    task = explore('ta', list(numbers), group_id='ga')
    setup_completing_run(repo, [task], [agent('a', 'ga'), *(agent(name) for name in free)], run=run,
                         groups=[AgentGroup(id='ga', run_id='r', agent_ids=('a',), task_ids=('ta',))])
    return task


class CompletingProvider(ReconsideringProvider):
    """Adds SYNTHESIZER and FINAL_REVIEWER behaviour to the Stage-6 provider.

    ``verdicts`` is a queue of final-review decisions; each entry is either a decision
    string or a callable receiving the context. ``synthesizer`` is a callable or a queue of
    them, so a scenario can make the first attempt defective and the next one whole.
    ``repair`` supplies the numbers a repair assignment should claim, so a scenario can
    decide whether repair actually succeeds.
    """

    def __init__(self, *, verdicts=(), synthesizer=None, final_reviewer=None, repair=None,
                 omit_criteria=(), **kwargs):
        super().__init__(**kwargs)
        self.verdicts = list(verdicts)
        self.synthesizers = list(synthesizer) if isinstance(synthesizer, (list, tuple)) else None
        self.synthesizer = None if self.synthesizers is not None else synthesizer
        self.final_reviewer, self.repair = final_reviewer, repair
        self.omit_criteria = set(omit_criteria)
        self.results, self.reviews_seen = [], []

    def _next_synthesizer(self):
        if self.synthesizers is None:
            return self.synthesizer
        return self.synthesizers.pop(0) if self.synthesizers else None

    @staticmethod
    def _role(instructions):
        if instructions.startswith('Compose'):
            return 'synthesizer'
        if instructions.startswith('Judge'):
            return 'final_reviewer'
        if instructions.startswith('Apply'):
            return 'specialist'
        return ReconsideringProvider._role(instructions)

    async def generate(self, request):
        context = json.loads(json.loads(request.messages[1].content)['context'])
        role = self._role(request.messages[0].content)
        tool = json.loads(request.messages[-1].content) if request.messages[-1].role == 'tool' else None
        if role not in ('synthesizer', 'final_reviewer', 'specialist'):
            return await super().generate(request)
        self.calls.append((role, context['task']['id']))
        self.contexts.append((role, context))
        if self.before is not None:
            self.before(role, context)
        if role == 'synthesizer':
            return self._synthesize(context)
        if role == 'specialist':
            return self._repair(context, tool)
        return self._judge(context)

    # --- synthesis ---------------------------------------------------------------

    def _synthesize(self, context):
        """Cite every validated finding the controller supplied and declare every criterion.

        The declaration is only a declaration: the host recomputes coverage from the cited
        findings, so this fixture cannot manufacture support it was not given.
        """
        self.results.append(context)
        hook = self._next_synthesizer()
        if hook is not None:
            return hook(context)
        supported = [f for f in context['findings'] if f['status'] == 'VALIDATED']
        cited = sorted({f['id'] for f in supported})
        criteria = [c['id'] for c in context['criteria'] if c['id'] not in self.omit_criteria]
        claims = [{'claim': f['claim'], 'finding_ids': [f['id']]} for f in supported]
        answer = 'total: ' + '; '.join(f['claim'] for f in supported) if supported else 'no support'
        return done(summary='synthesized',
                    result={'answer': answer, 'finding_ids': cited, 'criterion_ids': criteria,
                            'claims': claims,
                            'limitations': list(context.get('limitations', []))})

    # --- repair --------------------------------------------------------------------

    def _repair(self, context, tool):
        if self.repair is None:
            return done(status='FAILED', summary='no repair strategy configured')
        numbers, total = self.repair
        if tool is None:
            return call('arithmetic', {'numbers': list(numbers), 'expected': total})
        return done(summary='repaired',
                    findings=[{'claim': f'sum({list(numbers)}) = {total}', 'evidence_ids': [tool['id']]}])

    # --- final review ---------------------------------------------------------------

    def _judge(self, context):
        if self.final_reviewer is not None:
            return self.final_reviewer(context)
        self.reviews_seen.append(context)
        step = self.verdicts.pop(0) if self.verdicts else 'PASS'
        if callable(step):
            return step(context)
        return final_review(context, step)


def final_review(context, decision, *, criterion_ids=(), unsupported_claims=(), issues=(), checks=()):
    """A final-review envelope naming the exact result version in context."""
    result = context['result']
    payload = {'target_id': result['id'], 'target_revision': result['revision'],
               'decision': decision, 'summary': f'final review {decision}'}
    if criterion_ids:
        payload['criterion_ids'] = list(criterion_ids)
    if unsupported_claims:
        payload['unsupported_claims'] = list(unsupported_claims)
    if issues:
        payload['blocking_issues'] = list(issues)
    if checks:
        payload['checks'] = list(checks)
    return done(summary='judged', review=payload)


def omit_support(marker):
    """A synthesizer that leaves out every finding whose claim contains ``marker``.

    Used to produce the one defect a presentation revision can actually repair: knowledge
    that exists and is validated, and an answer that simply failed to present it.
    """
    def synthesize(context):
        supported = [f for f in context['findings'] if f['status'] == 'VALIDATED']
        kept = [f for f in supported if marker not in f['claim']]
        cited = sorted({f['id'] for f in kept})
        return done(summary='partial synthesis',
                    result={'answer': 'partial: ' + '; '.join(f['claim'] for f in kept),
                            'finding_ids': cited,
                            'criterion_ids': [c['id'] for c in context['criteria']],
                            'claims': [{'claim': f['claim'], 'finding_ids': [f['id']]} for f in kept]})
    return synthesize


# --- inspection ------------------------------------------------------------------

def results_of(snapshot):
    return sorted((r for r in snapshot.values() if isinstance(r, Result)), key=lambda r: r.version)


def accepted(snapshot):
    return next((r for r in results_of(snapshot) if r.status == ResultStatus.ACCEPTED), None)


def final_reviews(snapshot):
    return sorted((r for r in snapshot.values() if isinstance(r, ReviewRecord)
                   and r.kind == ReviewKind.FINAL), key=lambda r: r.id)


def report_of(snapshot):
    return next((r for r in snapshot.values() if isinstance(r, TerminalReport)), None)


def state_of_run(snapshot):
    return snapshot['r'].state


def repairs_of(snapshot):
    return tasks_of(snapshot, 'repair')


def syntheses_of(snapshot):
    return tasks_of(snapshot, 'synthesis')
