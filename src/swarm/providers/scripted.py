"""The scenario-driven demonstration provider: deterministic, local, and openly a fake.

This provider exists to exercise the swarm runtime, not to be believed. Every answer it
gives is scripted by the scenario file, and none of them can promote anything: a claim it
makes reaches validated knowledge only if the trusted arithmetic tool, read by the host
verifier, entails that exact claim. A scenario can therefore script a *wrong* answer and
watch the epistemic boundary reject it.

Role dispatch is by exact match against the registered role instructions rather than by
guessing at a prefix, so a role whose instructions change is a hard failure here instead of
a silently mis-scripted run.
"""
import json
from ..contracts import ModelResponse, ToolCall
from ..domain import RoleName
from ..roles import INSTRUCTIONS
from ..verification import parse_sum_claim

SCRIPTED_FIELDS = ('claims', 'critiques', 'repairs', 'reconsideration', 'synthesis',
                   'final_reviews')
PROVIDER_KINDS = {'scripted': SCRIPTED_FIELDS}

CRITIQUE_FIELDS = ('claim_contains', 'decision', 'summary', 'blocking_issues', 'nonblocking_issues')
CRITIQUE_DECISIONS = ('PASS', 'CHALLENGE', 'INCONCLUSIVE')
REPAIR_FIELDS = ('numbers', 'total')
RECONSIDERATION_FIELDS = ('outcome', 'reason')
RECONSIDERATION_OUTCOMES = ('APPLIED', 'NO_CHANGE', 'FOLLOW_UP_REQUESTED')
SYNTHESIS_FIELDS = ('omit_support_matching', 'omit_criteria')
FINAL_REVIEW_FIELDS = ('decision', 'summary', 'criterion_ids', 'blocking_issues',
                       'nonblocking_issues', 'unsupported_claims', 'checks')
FINAL_REVIEW_DECISIONS = ('PASS', 'REVISE', 'REJECT')

ROLE_BY_INSTRUCTIONS = {text: name for name, text in INSTRUCTIONS.items()}
WORK_ROLES = (RoleName.EXPLORER, RoleName.SPECIALIST, RoleName.COLLABORATOR)


def _done(**extra):
    return ModelResponse(content=json.dumps({'status': 'SUCCEEDED', 'summary': 'ok', **extra}))


def _failed(summary):
    return ModelResponse(content=json.dumps({'status': 'FAILED', 'summary': summary}))


class ScenarioProvider:
    """One run's scripted answers. Stateful only in the queues the scenario declared."""

    def __init__(self, config=None):
        config = dict(config or {})
        self.claims = dict(config.get('claims') or {})
        self.critiques = list(config.get('critiques') or [])
        self.repairs = dict(config.get('repairs') or {})
        self.reconsideration = dict(config.get('reconsideration') or {})
        self.synthesis = list(config.get('synthesis') or [])
        self.final_reviews = list(config.get('final_reviews') or [])
        self.calls = []
        self._serial = 0

    # --- dispatch ----------------------------------------------------------------

    async def generate(self, request):
        role = ROLE_BY_INSTRUCTIONS.get(request.messages[0].content)
        if role is None:
            return _failed('UNSCRIPTED_ROLE: this provider answers registered roles only')
        context = json.loads(json.loads(request.messages[1].content)['context'])
        last = request.messages[-1]
        tool = json.loads(last.content) if last.role == 'tool' else None
        self.calls.append((str(role), context['task']['id']))
        if role in WORK_ROLES:
            return self._work(role, context, tool)
        if role == RoleName.CRITIC:
            return self._critique(context)
        if role == RoleName.VALIDATOR:
            return self._validate(context, tool)
        if role == RoleName.SYNTHESIZER:
            return self._synthesize(context)
        if role == RoleName.FINAL_REVIEWER:
            return self._judge(context)
        return _failed(f'UNSCHEDULED_ROLE: {role}')

    def _call(self, name, arguments):
        self._serial += 1
        return ModelResponse(tool_calls=(ToolCall(
            id=f'call-{self._serial:04}', name=name,
            arguments_json=json.dumps(arguments, sort_keys=True)),))

    # --- work --------------------------------------------------------------------

    @staticmethod
    def _numbers(context):
        """Integer operands a scenario task carries in its description, or None."""
        try:
            numbers = json.loads(context['task']['description'])
        except ValueError:
            return None
        if isinstance(numbers, list) and numbers and all(type(n) is int for n in numbers):
            return numbers
        return None

    def _target(self, role, context):
        """What this assignment should claim: ``(numbers, total)``, or None for no claim."""
        numbers = self._numbers(context)
        if numbers is not None:
            return numbers, self.claims.get(context['task']['id'], sum(numbers))
        if role != RoleName.SPECIALIST:
            return None
        criteria = [entry['id'] for entry in context.get('criteria', [])]
        for identity in criteria:
            repair = self.repairs.get(identity)
            if repair is not None:
                return list(repair['numbers']), repair['total']
        return None

    def _answers(self, context):
        """Answer every delivery this assignment was asked to consume, and only those."""
        outcome = self.reconsideration.get('outcome', 'NO_CHANGE')
        reason = self.reconsideration.get('reason', 'the branch rechecked its own evidence')
        answers = [{'propagation_id': entry['id'], 'outcome': outcome, 'reason': reason}
                   for entry in context.get('propagations', []) if entry['consumable']]
        return {'reconsiderations': answers} if answers else {}

    def _work(self, role, context, tool):
        answers = self._answers(context)
        target = self._target(role, context)
        if target is None:
            if role == RoleName.SPECIALIST:
                return _failed('NO_REPAIR_STRATEGY: the scenario scripts no repair for this gap')
            return _done(summary='reconsidered', **answers)
        numbers, total = target
        if tool is None:
            return self._call('arithmetic', {'numbers': numbers, 'expected': total})
        return _done(summary=f'claimed sum({numbers}) = {total}',
                     findings=[{'claim': f'sum({numbers}) = {total}',
                                'evidence_ids': [tool['id']]}], **answers)

    # --- criticism and validation -------------------------------------------------

    @staticmethod
    def _target_finding(context):
        return next(f for f in context['findings'] if f['id'] == context['target_id'])

    def _rule(self, claim):
        for rule in self.critiques:
            if rule.get('claim_contains', '') in claim:
                return rule
        return {}

    def _critique(self, context):
        target = self._target_finding(context)
        rule = self._rule(target['claim'])
        review = {'target_id': target['id'], 'target_revision': target['revision'],
                  'decision': rule.get('decision', 'PASS'),
                  'summary': rule.get('summary', 'adversarial examination of the exact claim')}
        for name in ('blocking_issues', 'nonblocking_issues'):
            if rule.get(name):
                review[name] = list(rule[name])
        return _done(summary='critiqued', review=review)

    def _validate(self, context, tool):
        """Recompute the claim's own operands with the trusted tool, then report.

        A PASS here is necessary and never sufficient: the host verifier reads the recorded
        arguments and result and decides whether they entail this exact claim.
        """
        target = self._target_finding(context)
        parsed = parse_sum_claim(target['claim'])
        if parsed is None:
            return _done(summary='validated', review={
                'target_id': target['id'], 'target_revision': target['revision'],
                'decision': 'INCONCLUSIVE',
                'summary': 'the claim is not in a form this validator can check'})
        numbers, total = parsed
        if tool is None:
            return self._call('arithmetic', {'numbers': list(numbers), 'expected': total})
        resolved = [issue['key'] for review in context.get('reviews', [])
                    for issue in review.get('blocking_issues', [])]
        return _done(summary='validated', review={
            'target_id': target['id'], 'target_revision': target['revision'], 'decision': 'PASS',
            'summary': 'recomputed the claim with the trusted tool',
            'evidence_ids': [tool['id']], 'checks': ['recomputed the sum over the claim operands'],
            'resolved_issues': resolved})

    # --- synthesis and final review ------------------------------------------------

    def _synthesize(self, context):
        step = self.synthesis.pop(0) if self.synthesis else {}
        omit = step.get('omit_support_matching')
        omitted_criteria = set(step.get('omit_criteria') or ())
        supported = [f for f in context['findings'] if f['status'] == 'VALIDATED'
                     and (omit is None or omit not in f['claim'])]
        cited = sorted({f['id'] for f in supported})
        criteria = [c['id'] for c in context['criteria'] if c['id'] not in omitted_criteria]
        answer = ('; '.join(f['claim'] for f in supported)
                  if supported else 'no validated support was supplied')
        return _done(summary='synthesized', result={
            'answer': answer, 'finding_ids': cited, 'criterion_ids': criteria,
            'claims': [{'claim': f['claim'], 'finding_ids': [f['id']]} for f in supported],
            'limitations': list(context.get('limitations', []))})

    def _judge(self, context):
        step = self.final_reviews.pop(0) if self.final_reviews else {}
        result = context['result']
        review = {'target_id': result['id'], 'target_revision': result['revision'],
                  'decision': step.get('decision', 'PASS'),
                  'summary': step.get('summary', 'independent review of this result version')}
        for name in ('criterion_ids', 'blocking_issues', 'nonblocking_issues',
                     'unsupported_claims', 'checks'):
            if step.get(name):
                review[name] = list(step[name])
        return _done(summary='judged', review=review)


# --- configuration validation ------------------------------------------------------

def _problem(code, path, message):
    from ..scenario import Problem
    return Problem(code, path, message)


def _check_object(problems, value, path, allowed, required=()):
    """Report this object's own problems, and say whether it may be read further.

    The verdict is about *this* object only: scanning the accumulated list by path prefix
    would let ``provider.synthesis[1]`` decide the fate of ``provider.synthesis[10]``.
    """
    if not isinstance(value, dict):
        problems.append(_problem('INVALID_TYPE', path, 'expected an object'))
        return False
    ok = True
    for name in sorted(set(value) - set(allowed)):
        problems.append(_problem('UNKNOWN_FIELD', f'{path}.{name}',
                                 'not a provider field; allowed: ' + ', '.join(sorted(allowed))))
        ok = False
    for name in required:
        if name not in value:
            problems.append(_problem('MISSING_FIELD', f'{path}.{name}', 'is required'))
            ok = False
    return ok


def _check_strings(problems, value, path, limit=16):
    if not isinstance(value, list) or len(value) > limit or any(
            not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in value):
        problems.append(_problem('INVALID_TYPE', path,
                                 f'expected an array of at most {limit} non-empty strings'))


def _check_claims(problems, raw):
    if not isinstance(raw, dict):
        problems.append(_problem('INVALID_TYPE', 'provider.claims',
                                 'expected an object mapping task id to the total to claim'))
        return
    for name, value in sorted(raw.items()):
        if type(value) is not int:
            problems.append(_problem('INVALID_TYPE', f'provider.claims.{name}',
                                     'expected an integer total'))


def _check_critiques(problems, raw):
    if not isinstance(raw, list):
        problems.append(_problem('INVALID_TYPE', 'provider.critiques', 'expected an array of rules'))
        return
    for index, rule in enumerate(raw):
        path = f'provider.critiques[{index}]'
        if not _check_object(problems, rule, path, CRITIQUE_FIELDS):
            continue
        decision = rule.get('decision', 'PASS')
        if decision not in CRITIQUE_DECISIONS:
            problems.append(_problem('INVALID_REVIEW_DECISION', f'{path}.decision',
                                     f'{decision!r} is not one of ' + ', '.join(CRITIQUE_DECISIONS)))
        for name in ('blocking_issues', 'nonblocking_issues'):
            if name in rule:
                _check_strings(problems, rule[name], f'{path}.{name}')


def _check_repairs(problems, raw):
    if not isinstance(raw, dict):
        problems.append(_problem('INVALID_TYPE', 'provider.repairs',
                                 'expected an object keyed by criterion id'))
        return
    for name, value in sorted(raw.items()):
        path = f'provider.repairs.{name}'
        if not _check_object(problems, value, path, REPAIR_FIELDS, REPAIR_FIELDS):
            continue
        numbers = value['numbers']
        if (not isinstance(numbers, list) or not numbers or len(numbers) > 64
                or any(type(n) is not int for n in numbers)):
            problems.append(_problem('INVALID_TYPE', f'{path}.numbers',
                                     'expected an array of 1 to 64 integers'))
        if type(value['total']) is not int:
            problems.append(_problem('INVALID_TYPE', f'{path}.total', 'expected an integer'))


def _check_reconsideration(problems, raw):
    if not _check_object(problems, raw, 'provider.reconsideration', RECONSIDERATION_FIELDS):
        return
    outcome = raw.get('outcome', 'NO_CHANGE')
    if outcome not in RECONSIDERATION_OUTCOMES:
        problems.append(_problem('INVALID_RECONSIDERATION_OUTCOME', 'provider.reconsideration.outcome',
                                 f'{outcome!r} is not one of ' + ', '.join(RECONSIDERATION_OUTCOMES)
                                 + ' (UNREPORTED is host-recorded)'))


def _check_synthesis(problems, raw):
    if not isinstance(raw, list):
        problems.append(_problem('INVALID_TYPE', 'provider.synthesis', 'expected an array of steps'))
        return
    for index, step in enumerate(raw):
        path = f'provider.synthesis[{index}]'
        if not _check_object(problems, step, path, SYNTHESIS_FIELDS):
            continue
        if 'omit_support_matching' in step and not isinstance(step['omit_support_matching'], str):
            problems.append(_problem('INVALID_TYPE', f'{path}.omit_support_matching',
                                     'expected a string to match against a claim'))
        if 'omit_criteria' in step:
            _check_strings(problems, step['omit_criteria'], f'{path}.omit_criteria')


def _check_final_reviews(problems, raw):
    if not isinstance(raw, list):
        problems.append(_problem('INVALID_TYPE', 'provider.final_reviews',
                                 'expected an array of verdicts'))
        return
    for index, step in enumerate(raw):
        path = f'provider.final_reviews[{index}]'
        if not _check_object(problems, step, path, FINAL_REVIEW_FIELDS):
            continue
        decision = step.get('decision', 'PASS')
        if decision not in FINAL_REVIEW_DECISIONS:
            problems.append(_problem('INVALID_REVIEW_DECISION', f'{path}.decision',
                                     f'{decision!r} is not one of '
                                     + ', '.join(FINAL_REVIEW_DECISIONS)))
        for name in ('criterion_ids', 'blocking_issues', 'nonblocking_issues',
                     'unsupported_claims', 'checks'):
            if name in step:
                _check_strings(problems, step[name], f'{path}.{name}')


_CHECKS = {'claims': _check_claims, 'critiques': _check_critiques, 'repairs': _check_repairs,
           'reconsideration': _check_reconsideration, 'synthesis': _check_synthesis,
           'final_reviews': _check_final_reviews}


def check_provider_config(raw):
    """Every problem in one provider block. The kind itself is checked by the scenario."""
    problems = []
    if not isinstance(raw, dict):
        return [_problem('INVALID_TYPE', 'provider', 'expected an object')]
    allowed = ('kind',) + SCRIPTED_FIELDS
    for name in sorted(set(raw) - set(allowed)):
        problems.append(_problem('UNKNOWN_FIELD', f'provider.{name}',
                                 'not a provider field; allowed: ' + ', '.join(sorted(allowed))))
    for name, check in _CHECKS.items():
        if name in raw:
            check(problems, raw[name])
    return problems


def build_provider(config):
    """The provider one validated scenario configures, keyed by its declared kind."""
    kind = config.get('kind')
    if kind not in PROVIDER_KINDS:
        raise ValueError(f'unknown provider kind: {kind!r}')
    return {kind: ScenarioProvider(config)}
