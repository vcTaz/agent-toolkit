"""Human-readable rendering of runs, results, inspections and traces.

Rendering is the whole of this module: every fact it prints was computed by ``inspection``,
``metrics`` or ``timeline`` from committed records. Nothing here recomputes a verdict, and
nothing here presents partial knowledge as an answer — a non-success run prints what it
established beside what it could not, and says which is which.
"""
from .timeline import identifiers

WIDTH = 13
BULLET = '  '

TERMINAL_NOTES = {
    'COMPLETED': 'An independent final reviewer passed this result version, and the '
                 'synthesis gate still held against current state when it was accepted.',
    'EXHAUSTED': 'EXHAUSTED means the system worked and the evidence or the configured '
                 'limits did not suffice. The knowledge below is partial and is not an answer.',
    'FAILED': 'FAILED means the run could not work at all — a configuration, storage or '
              'provider-contract problem. This is not EXHAUSTED, which means the system '
              'worked and the evidence or the limits did not suffice.',
    'CANCELLED': 'The run was cancelled before it could reach an outcome.',
}


def field(name, value):
    return f'{name:<{WIDTH}}{value}'


def lines(*items):
    return '\n'.join(item for item in items if item is not None)


def _bullets(values, prefix=BULLET):
    return [f'{prefix}{value}' for value in values]


# --- problems and catalogues ---------------------------------------------------------

def problems(scenario_problems, source=''):
    """A refused configuration: every problem, with the field that caused it."""
    head = [field('scenario', source) if source else None,
            field('status', 'REJECTED — the configuration was refused before any run existed'),
            f'{len(scenario_problems)} problem(s):']
    return lines(*head, *(f'{BULLET}{problem.code}\n{BULLET}  at {problem.path}\n'
                          f'{BULLET}  {problem.message}' for problem in scenario_problems))


def examples(catalogue):
    if not catalogue:
        return 'no packaged scenarios'
    out = [f'{len(catalogue)} packaged scenario(s):']
    for entry in catalogue:
        out.append(f'{BULLET}{entry["name"]}')
        if entry['description']:
            out.append(f'{BULLET}  {entry["description"]}')
    out.append('')
    out.append('run one with:  python -m swarm run --scenario <name>')
    return lines(*out)


def runs(rows):
    if not rows:
        return 'no runs in this database'
    out = [f'{len(rows)} run(s), newest first:']
    for row in rows:
        out.append(f'{BULLET}{row["run_id"]}')
        out.append(f'{BULLET}  {row["state"]:<10}{row["created_at"]}')
        if row['stop_reason']:
            out.append(f'{BULLET}  reason: {row["stop_reason"]}')
    out.append('')
    out.append('inspect one with:  python -m swarm inspect <run-id>')
    return lines(*out)


def scenario_summary(summary):
    out = [field('scenario', summary['name']),
           field('status', 'VALID — this configuration may be run'),
           field('objective', summary['objective'])]
    if summary['description']:
        out.append(field('about', summary['description']))
    out.append(field('criteria', ', '.join(
        f'{c["id"]} ({c["verifier_kind"]}{"" if c["required"] else ", optional"})'
        for c in summary['criteria'])))
    out.append(field('agents', ', '.join(summary['agents'])))
    out.append(field('groups', ', '.join(summary['groups']) or 'none'))
    out.append(field('tasks', ', '.join(summary['tasks']) or 'none declared'))
    out.append(field('provider', summary['provider_kind']))
    if summary['limits']:
        out.append(field('limits', ', '.join(f'{k}={v}' for k, v in summary['limits'].items())))
    return lines(*out)


# --- results and outcomes --------------------------------------------------------------

def _coverage(result, described=None, indent=BULLET):
    described = described or {}
    out = []
    for entry in result['coverage']:
        mark = 'required' if entry['required'] else 'optional'
        support = ', '.join(entry['finding_ids']) or 'no support'
        out.append(f'{indent}{entry["criterion_id"]:<6}{mark:<10}{support}')
        if described.get(entry['criterion_id']):
            out.append(f'{indent}{"":<6}{described[entry["criterion_id"]]}')
    return out


def result_block(result, criteria=()):
    """A COMPLETED run's concise final result: answer, coverage, support, limitations."""
    described = {entry['id']: entry.get('description', '') for entry in criteria}
    out = [field('answer', result['answer']),
           field('result', f'version {result["version"]} ({result["status"]})')]
    if result['review_id']:
        out.append(field('final review', f'{result["decision"]} by {result["review_id"]}'))
    out.append('coverage:')
    out += _coverage(result, described)
    if result['claims']:
        out.append('claims and their support:')
        out += _bullets(f'{c["claim"]}  <- {", ".join(c["finding_ids"])}' for c in result['claims'])
    out.append(field('support', ', '.join(result['finding_ids']) or 'none'))
    out.append('limitations:')
    out += _bullets(result['limitations'] or ['none recorded'])
    return lines(*out)


def outcome_block(report, findings=()):
    """A non-success run: what it established, what it did not, and why it stopped."""
    claims = {entry['id']: entry['claim'] for entry in findings}
    out = [field('stop reason', report['stop_reason'])]
    # A completed run's knowledge is the support behind its answer; a non-success run's is
    # partial by definition, and saying so is the point of the report.
    out.append('validated knowledge:' if report['state'] == 'COMPLETED'
               else 'validated partial knowledge:')
    out += _bullets(f'{identity}  {claims.get(identity, "")}'.rstrip()
                    for identity in report['validated_finding_ids']) or _bullets(['none'])
    out.append('unresolved criteria:')
    out += _bullets(f'{gap["criterion_id"]:<6}{gap["reason"]:<26}'
                    f'{"required" if gap["required"] else "optional"}'
                    for gap in report['gaps']) or _bullets(['none'])
    if report['branch_stops']:
        out.append('branches stopped:')
        out += _bullets(report['branch_stops'])
    if report['final_review_issues']:
        out.append('final-review issues:')
        out += _bullets(report['final_review_issues'])
    if report['unconsumed_knowledge']:
        out.append('knowledge nothing consumed:')
        out += _bullets(report['unconsumed_knowledge'])
    return lines(*out)


def metrics_line(values):
    return field('metrics', ' '.join([
        f'requests={values["provider_requests"]}/{values["provider_request_limit"]}',
        f'tools={values["tool_calls"]}/{values["tool_call_limit"]}',
        f'tasks={values["tasks"]["total"]}',
        f'findings={values["findings"]["VALIDATED"]}v/{values["findings"]["REJECTED"]}r',
        f'reviews={values["reviews"]["total"]}',
        f'propagations={values["propagations"]["total"]}',
        f'cycles={values["cycles_charged"]}/{values["cycle_limit"]}',
        f'results={values["results"]["versions"]}',
        f'repairs={values["repair_rounds"]}',
        f'revisions={values["presentation_revisions"]}',
        f'duration={values["duration_seconds"]}s']))


def run_report(report):
    """What one finished run tells its operator, in one screen."""
    run, state = report['run'], report['run']['state']
    out = [field('run', run['id']), field('state', state), field('objective', run['objective'])]
    result = report.get('result')
    if state == 'COMPLETED' and result is not None:
        out.append(result_block(result, report.get('criteria', ())))
    elif report.get('outcome') is not None:
        out.append(outcome_block(report['outcome'], report.get('findings', ())))
    else:
        out.append(field('stop reason', run['stop_reason'] or 'no terminal report was written'))
    out.append(metrics_line(report['metrics']))
    out.append('')
    out.append(TERMINAL_NOTES.get(state, 'This run has not reached a terminal state.'))
    out.append(f'inspect it with:  python -m swarm inspect {run["id"]}')
    return lines(*out)


# --- inspection sections -----------------------------------------------------------------

def _rows(entries, columns):
    out = []
    for entry in entries:
        out.append(BULLET + '  '.join(str(entry.get(name, '') or '') for name in columns))
    return out or [BULLET + 'none']


def _criteria(entries):
    out = []
    for entry in entries:
        mark = 'required' if entry['required'] else 'optional'
        gap = entry.get('blocking_gap') or 'clean'
        out.append(f'{BULLET}{entry["id"]:<6}{mark:<10}{entry["verifier_kind"]:<12}{gap}')
        out.append(f'{BULLET}  {entry["description"]}')
        support = ', '.join(entry.get('supporting_ids') or ()) or 'none'
        verified = ', '.join(entry.get('verified_ids') or ()) or 'none'
        out.append(f'{BULLET}  support: {support}   host-verified: {verified}')
    return out or [BULLET + 'none']


def _findings(entries):
    out = []
    for entry in entries:
        out.append(f'{BULLET}{entry["id"]}  {entry["status"]}')
        out.append(f'{BULLET}  claim: {entry["claim"]}')
        out.append(f'{BULLET}  task {entry["task_id"]} by {entry["agent_id"]}  '
                   f'criteria {", ".join(entry["criterion_ids"]) or "none"}')
        out.append(f'{BULLET}  why: {entry["why"]}')
        for item in entry['verified_evidence']:
            out.append(f'{BULLET}  verified: {item["tool_name"]}({item["arguments"]}) '
                       f'-> {item["value"]}')
    return out or [BULLET + 'none']


def _reviews(entries):
    out = []
    for entry in entries:
        out.append(f'{BULLET}{entry["id"]}  {entry["kind"]}  {entry["decision"]}  '
                   f'on {entry["target_id"]}@{entry["target_revision"]} by {entry["reviewer"]}')
        if entry['verification']:
            out.append(f'{BULLET}  verification: {entry["verification"]}')
        for name in ('blocking_issues', 'unsupported_claims', 'criterion_ids', 'checks'):
            if entry[name]:
                out.append(f'{BULLET}  {name}: {"; ".join(entry[name])}')
    return out or [BULLET + 'none']


def _propagations(entries):
    out = []
    for entry in entries:
        out.append(f'{BULLET}{entry["id"]}  {entry["kind"]}  {entry["status"]}')
        out.append(f'{BULLET}  {entry["canonical_finding_id"]}@{entry["knowledge_revision"]}'
                   f' -> {entry["target_task_id"]}  ({entry["why"]})')
        if entry['insight']:
            out.append(f'{BULLET}  insight: {entry["insight"]}')
        if entry['outcome']:
            out.append(f'{BULLET}  answered {entry["outcome"]}: {entry["outcome_reason"]}')
    return out or [BULLET + 'none']


def _evidence(entries):
    """Each verified item with the tool-result reference that distinguishes it.

    One claim commonly carries two: the author's own recorded tool result and the
    validator's independent recomputation. Without the reference they read as a duplicate.
    """
    out = []
    for entry in entries:
        out.append(f'{BULLET}{entry["review_id"]}  {entry["tool_name"]}  ref {entry["reference"]}')
        out.append(f'{BULLET}  on {entry["target_id"]}: {entry["claim"]}')
        out.append(f'{BULLET}  {entry["arguments"]} -> {entry["value"]}')
    return out or [BULLET + 'none']


def _provenance(entry):
    out = [f'{BULLET}terminal: {entry["terminal_state"]}  {entry["stop_reason"] or ""}'.rstrip()]
    gate = entry.get('final_gate')
    if gate:
        out.append(f'{BULLET}last gate: {gate.get("status")}  '
                   f'{"; ".join(gate.get("reasons") or []) or "no blocking reason"}')
    for decision in entry['repair_decisions']:
        verdict = 'admitted' if decision['admitted'] else 'refused'
        out.append(f'{BULLET}repair {verdict}: {decision["criterion_id"]} '
                   f'({decision["gap"]}) {decision.get("reason") or ""}'.rstrip())
    for gap in entry['review_gaps']:
        out.append(f'{BULLET}review gap: {gap["task_id"]} {gap["reason"]}')
    for stop in entry['branch_stops']:
        out.append(f'{BULLET}branch stopped: {stop["group_id"]} {stop["reason"]}')
    for review in entry['final_reviews']:
        out.append(f'{BULLET}final review {review["id"]}: {review["decision"]} '
                   f'({review["verification"]})')
    for support in entry['result_support']:
        out.append(f'{BULLET}answer support {support["criterion_id"]}: '
                   f'{", ".join(support["finding_ids"]) or "none"}')
    return out


def trace(entries):
    """The causal narrative: sequence, event, the ids to inspect further, and a summary."""
    out = []
    for item in entries:
        ids = ' '.join(identifiers(item))
        out.append(f'{item["sequence"]:>5}  {item["type"]:<28}{ids}')
        if item['summary']:
            out.append(f'       {item["summary"]}')
    return lines(*out) if out else 'no events'


SECTION_RENDERERS = {
    'criteria': _criteria,
    'findings': _findings,
    'reviews': _reviews,
    'propagations': _propagations,
    'tasks': lambda entries: _rows(entries, ('id', 'kind', 'status', 'objective')),
    'agents': lambda entries: _rows(entries, ('id', 'status', 'group_id', 'role_id')),
    'assignments': lambda entries: _rows(entries, ('id', 'task_id', 'agent_id', 'role_id',
                                                   'status')),
    'groups': lambda entries: _rows(entries, ('id', 'status', 'stop_reason', 'idle_cycles')),
    'conflicts': lambda entries: _rows(entries, ('id', 'kind', 'status', 'reason')),
    'cycles': lambda entries: _rows(entries, ('number', 'status', 'trigger', 'reason')),
    'messages': lambda entries: _rows(entries, ('id', 'sender', 'recipient', 'status')),
    'task_requests': lambda entries: _rows(entries, ('id', 'objective', 'note')),
    'evidence': _evidence,
    'events': lambda entries: _rows(entries, ('sequence', 'type', 'record_id')),
}


def inspection(report):
    """Render whichever sections the caller asked for, in a stable order."""
    out = [field('run', report['run_id']), field('status', report['status'])]
    if 'run' in report and report['run']:
        out.append(field('objective', report['run']['objective']))
        out.append(field('state', report['run']['state']))
        out.append(field('limits', ', '.join(f'{k}={v}' for k, v in
                                             sorted(report['run']['limits'].items()))))
    for name in ('criteria', 'tasks', 'agents', 'assignments', 'groups', 'findings', 'reviews',
                 'evidence', 'conflicts', 'propagations', 'cycles', 'messages', 'task_requests',
                 'events'):
        if name in report:
            out.append('')
            out.append(f'{name}:')
            out += SECTION_RENDERERS[name](report[name])
    if 'state' in report and report['state']:
        out.append('')
        out.append('shared state:')
        out += [f'{BULLET}{key}: {", ".join(value) if isinstance(value, list) else value}'
                for key, value in sorted(report['state'].items())]
    if 'results' in report:
        out.append('')
        out.append('result versions:')
        for version in report['results']:
            out.append(f'{BULLET}v{version["version"]}  {version["status"]}  '
                       f'{version["decision"] or "unjudged"}  by {version["author"]}')
            out.append(f'{BULLET}  {version["answer"]}')
    if report.get('result') is not None and 'result' in report:
        out.append('')
        out.append(result_block(report['result'], report.get('criteria', ())))
    if report.get('outcome') is not None and 'outcome' in report:
        out.append('')
        out.append('terminal report:')
        out.append(outcome_block(report['outcome'], report.get('findings', ())))
    if 'provenance' in report:
        out.append('')
        out.append('provenance:')
        out += _provenance(report['provenance'])
    if 'metrics' in report:
        out.append('')
        out.append(metrics_line(report['metrics']))
    if 'timeline' in report:
        out.append('')
        out.append('timeline:')
        out.append(trace(report['timeline']))
    return lines(*out)


# --- evaluation ---------------------------------------------------------------------------

def evaluation(outcome):
    out = [field('evaluated', f'{outcome["scenarios"]} scenario(s)'),
           field('checks', f'{outcome["passed"]} passed, {outcome["failed"]} failed')]
    for entry in outcome['results']:
        status = 'PASS' if entry['ok'] else 'FAIL'
        out.append('')
        out.append(f'{status}  {entry["scenario"]}  ({entry["terminal_state"]})')
        for check in entry['checks']:
            mark = 'ok  ' if check['ok'] else 'FAIL'
            out.append(f'{BULLET}{mark} {check["name"]}: {check["detail"]}')
    out.append('')
    out.append('OK' if outcome['failed'] == 0 else f'{outcome["failed"]} check(s) failed')
    return lines(*out)
