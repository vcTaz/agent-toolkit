"""A small deterministic evaluation layer over the packaged scenarios.

This is not a benchmark platform and does not try to become one. It answers one question:
did the swarm still behave the way this scenario says it must? Each expectation is a
property of the *architecture* — a terminal state that was earned, a bad candidate that was
rejected by evidence, a discovery that reached the branch it was relevant to and no other,
an independent final review, no invariant violation — so a regression in swarm behaviour
shows up as a named failing check rather than as a differently worded answer.

Expectations live in the scenario file's ``expect`` block, beside the configuration they
describe. Scenarios that are invalid *by design* cannot carry their own expectations, since
validation refuses them before ``expect`` is ever read; those few are listed in
``REJECTIONS`` here, with the problem codes their refusal must produce.
"""
import json
from . import inspection, runner, scenario as scenario_module
from .domain import validate_records
from .examples import catalogue, resolve
from .persistence import SQLiteRepository

REJECTIONS = {'unsupported_verifier': ('UNSUPPORTED_VERIFIER_KIND',)}
"""Scenarios whose whole point is to be refused, and the codes the refusal must carry."""

VOLATILE_KEYS = ('created_at', 'updated_at', 'started_at', 'ended_at', 'resolved_at',
                 'timestamp', 'deadline_at', 'duration_seconds', 'reference',
                 'context_hash', 'progress_signature')
"""Values that legitimately differ between two runs of the same scenario: wall-clock
moments, and digests over per-execution tool-result identifiers."""


def normalise(value, run_id):
    """Strip a report of everything that may differ between two equivalent runs."""
    if isinstance(value, dict):
        return {key: '<volatile>' if key in VOLATILE_KEYS else normalise(item, run_id)
                for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [normalise(item, run_id) for item in value]
    if isinstance(value, str):
        return value.replace(run_id, '<run>')
    return value


# --- checks --------------------------------------------------------------------------

class _Context:
    """One executed scenario, with the views the expectations are written against."""

    def __init__(self, report, outcome):
        self.report, self.outcome = report, outcome
        self.result = report.get('result') if report['run']['result_id'] else None
        self.findings = report['findings']
        self.criteria = {entry['id']: entry for entry in report['criteria']}
        self.propagations = report['propagations']
        self.reviews = report['reviews']

    def claims(self, status):
        return {entry['claim'] for entry in self.findings if entry['status'] == status}


def _state(expected, ctx):
    actual = ctx.report['run']['state']
    return actual == expected, f'expected {expected}, run ended {actual}'


def _exit_code(expected, ctx):
    return ctx.outcome.exit_code == expected, f'expected {expected}, got {ctx.outcome.exit_code}'


def _no_result(expected, ctx):
    absent = ctx.report['run']['result_id'] is None
    return absent is bool(expected), f'accepted result present={not absent}'


def _result_versions(expected, ctx):
    actual = len(ctx.report['results'])
    return actual == expected, f'expected {expected} version(s), found {actual}'


def _answer_contains(expected, ctx):
    if ctx.result is None:
        return False, 'no accepted result to read'
    missing = [text for text in expected if text not in ctx.result['answer']]
    return not missing, f'missing from the answer: {missing}' if missing else 'all present'


def _criteria_covered(expected, ctx):
    uncovered = [name for name in expected
                 if not (ctx.criteria.get(name, {}).get('covered')
                         and ctx.criteria.get(name, {}).get('blocking_gap') is None)]
    return not uncovered, f'not cleanly covered: {uncovered}' if uncovered else 'all covered'


def _validated_claims(expected, ctx):
    missing = sorted(set(expected) - ctx.claims('VALIDATED'))
    return not missing, f'never validated: {missing}' if missing else f'{len(expected)} validated'


def _rejected_claims(expected, ctx):
    missing = sorted(set(expected) - ctx.claims('REJECTED'))
    return not missing, f'never rejected: {missing}' if missing else f'{len(expected)} rejected'


def _no_rejected_findings(expected, ctx):
    rejected = sorted(ctx.claims('REJECTED'))
    return (not rejected) is bool(expected), f'rejected: {rejected}' if rejected else 'none rejected'


def _gaps(expected, ctx):
    report = ctx.report.get('outcome') or {}
    actual = sorted(f'{gap["criterion_id"]}:{gap["reason"]}' for gap in report.get('gaps', ()))
    return actual == sorted(expected), f'expected {sorted(expected)}, found {actual}'


def _propagated_to(expected, ctx):
    reached = {entry['target_task_id'] for entry in ctx.propagations
               if entry['status'] in ('DELIVERED', 'CONSUMED')}
    missing = sorted(set(expected) - reached)
    return not missing, f'never reached: {missing}' if missing else f'reached {sorted(reached)}'


def _not_propagated_to(expected, ctx):
    reached = {entry['target_task_id'] for entry in ctx.propagations}
    leaked = sorted(set(expected) & reached)
    return not leaked, f'unexpectedly propagated to: {leaked}' if leaked else 'no leakage'


def _reconsiderations_reported(expected, ctx):
    answered = [entry['id'] for entry in ctx.propagations
                if entry['outcome'] in ('APPLIED', 'NO_CHANGE', 'FOLLOW_UP_REQUESTED')]
    return bool(answered) is bool(expected), f'{len(answered)} delivery answered by a branch'


def _blocking_criticism(expected, ctx):
    raised = [r for r in ctx.reviews if r['kind'] == 'criticism' and r['blocking_issues']]
    resolved = [r for r in ctx.reviews if r['kind'] == 'validation' and r['resolved_issues']]
    happened = bool(raised) and bool(resolved)
    return happened is bool(expected), (f'{len(raised)} blocking critique(s), '
                                        f'{len(resolved)} resolved by validation')


def _final_review_decisions(expected, ctx):
    actual = [r['decision'] for r in ctx.reviews if r['kind'] == 'final']
    return actual == list(expected), f'expected {list(expected)}, found {actual}'


def _stop_reason_contains(expected, ctx):
    reason = ctx.report['run']['stop_reason'] or ''
    return expected in reason, f'stop reason is {reason!r}'


def _repair_attempted(expected, ctx):
    admitted = [d for d in ctx.report['provenance']['repair_decisions'] if d['admitted']]
    return bool(admitted) is bool(expected), f'{len(admitted)} repair task(s) admitted'


CHECKS = {'terminal_state': _state, 'exit_code': _exit_code, 'no_result': _no_result,
          'result_versions': _result_versions, 'answer_contains': _answer_contains,
          'criteria_covered': _criteria_covered, 'validated_claims': _validated_claims,
          'rejected_claims': _rejected_claims, 'no_rejected_findings': _no_rejected_findings,
          'gaps': _gaps, 'propagated_to': _propagated_to, 'not_propagated_to': _not_propagated_to,
          'reconsiderations_reported': _reconsiderations_reported,
          'blocking_criticism': _blocking_criticism,
          'final_review_decisions': _final_review_decisions,
          'stop_reason_contains': _stop_reason_contains, 'repair_attempted': _repair_attempted}


def _invariants(snapshot):
    try:
        validate_records(snapshot.values())
    except Exception as exc:                      # noqa: BLE001 - reported, never swallowed
        return False, f'{type(exc).__name__}: {exc}'
    return True, 'the terminal snapshot satisfies every invariant'


def _provenance(ctx):
    """Every validated claim must name the review and the host-verified evidence behind it."""
    unsupported = [entry['id'] for entry in ctx.findings
                   if entry['status'] == 'VALIDATED' and not entry['verified_evidence']]
    return not unsupported, (f'validated without host-verified evidence: {unsupported}'
                             if unsupported else 'every validated claim is reconstructible')


# --- execution -------------------------------------------------------------------------

def _check(name, ok, detail):
    return {'name': name, 'ok': bool(ok), 'detail': detail}


def _rejection_result(name, path, expected_codes):
    """A scenario that must be refused: run validation and check the refusal itself."""
    try:
        scenario_module.load(path, tool_names=runner.TOOL_NAMES)
    except scenario_module.ScenarioError as exc:
        codes = sorted({problem.code for problem in exc.problems})
        ok = sorted(expected_codes) == codes
        return {'scenario': name, 'ok': ok, 'terminal_state': 'CONFIG_REJECTED', 'run_id': None,
                'checks': [_check('config_rejected', ok,
                                  f'expected {sorted(expected_codes)}, got {codes}')]}
    return {'scenario': name, 'ok': False, 'terminal_state': 'ACCEPTED', 'run_id': None,
            'checks': [_check('config_rejected', False,
                              'the scenario validated, but it must be refused')]}


def evaluate_scenario(name, *, database=':memory:', repeat=1):
    """Execute one packaged scenario and check every expectation it declares."""
    path = resolve(name)
    if path is None:
        return {'scenario': name, 'ok': False, 'terminal_state': 'UNKNOWN', 'run_id': None,
                'checks': [_check('scenario_found', False, 'no such scenario')]}
    if name in REJECTIONS:
        return _rejection_result(name, path, REJECTIONS[name])
    scenario = scenario_module.load(path, tool_names=runner.TOOL_NAMES)
    checks, normalised, run_id = [], None, None
    for attempt in range(max(1, repeat)):
        repository = SQLiteRepository(database)
        try:
            outcome = runner.execute_scenario(repository, scenario)
            report = inspection.build(repository.inspect(outcome.run_id), outcome.run_id,
                                      sections=inspection.SECTIONS)
        finally:
            repository.close()
        current = normalise({key: report[key] for key in
                             ('run', 'criteria', 'result', 'results', 'outcome', 'findings',
                              'reviews', 'propagations', 'cycles', 'provenance')},
                            outcome.run_id)
        if attempt == 0:
            run_id, normalised = outcome.run_id, current
            checks = _expectation_checks(scenario, report, outcome)
        else:
            checks.append(_check('determinism', current == normalised,
                                 f'run {attempt + 1} of {repeat} produced '
                                 + ('the same normalised report'
                                    if current == normalised else 'a different report')))
    return {'scenario': name, 'ok': all(entry['ok'] for entry in checks),
            'terminal_state': normalised['run']['state'], 'run_id': run_id, 'checks': checks}


def _expectation_checks(scenario, report, outcome):
    ctx = _Context(report, outcome)
    checks = [_check('invariants', *_invariants(outcome.snapshot)),
              _check('provenance_reconstructible', *_provenance(ctx))]
    for name in sorted(scenario.expect):
        check = CHECKS.get(name)
        if check is None:
            checks.append(_check(name, False, 'unknown expectation; the harness fails closed'))
            continue
        checks.append(_check(name, *check(scenario.expect[name], ctx)))
    if not scenario.expect:
        checks.append(_check('expectations_declared', False,
                             'the scenario declares no expect block'))
    return checks


def suite_names():
    """Every packaged scenario, in deterministic order."""
    return tuple(entry['name'] for entry in catalogue())


def run_suite(names=None, *, database=':memory:', repeat=1):
    """Evaluate the packaged scenarios and summarise every check."""
    results = [evaluate_scenario(name, database=database, repeat=repeat)
               for name in (names or suite_names())]
    checks = [check for entry in results for check in entry['checks']]
    return {'scenarios': len(results),
            'passed': sum(check['ok'] for check in checks),
            'failed': sum(not check['ok'] for check in checks),
            'ok': all(entry['ok'] for entry in results),
            'results': results}


def as_json(outcome):
    return json.dumps(outcome, indent=2, sort_keys=True)
