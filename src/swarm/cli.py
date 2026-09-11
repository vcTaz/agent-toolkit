"""The local command line: run a scenario, inspect a run, evaluate the fixtures.

Deliberately narrow. There is no CLI-only orchestration path: ``run`` seeds a scenario and
hands it to the same ``WorkController`` the test suite drives, and every other command is a
read over the same SQLite database the controller committed to.

Exit codes are part of the contract, because a terminal outcome is information rather than
a crash:

```text
0  COMPLETED          a reviewed answer the gate still held for
1  EXHAUSTED          the system worked; evidence or limits did not suffice
2  FAILED             the run could not work at all
3  CANCELLED
4  REFUSED            the request itself was refused: invalid scenario, unknown run
5  STORAGE_ERROR      durable state could not be read or written
```
"""
import argparse
import json
import sys
from . import evaluation, inspection, render, runner, scenario as scenario_module
from .examples import catalogue, resolve
from .persistence import SQLiteRepository, StorageError

DEFAULT_DATABASE = 'swarm-runs.db'
REFUSED = runner.CONFIG_REJECTED
STORAGE = runner.STORAGE_ERROR
RUN_SECTIONS = ('run', 'criteria', 'result', 'outcome', 'metrics', 'provenance', 'findings')


def _emit(payload, text, as_json, stream=None):
    print(json.dumps(payload, indent=2, sort_keys=True) if as_json else text,
          file=stream or sys.stdout)


def _load(reference, args):
    """Resolve and validate one scenario, or explain the refusal. Returns None on refusal."""
    path = resolve(reference)
    if path is None:
        names = ', '.join(entry['name'] for entry in catalogue())
        print(f'REFUSED: no scenario file or packaged example named {reference!r}\n'
              f'packaged examples: {names}', file=sys.stderr)
        return None
    try:
        return scenario_module.load(path, tool_names=runner.TOOL_NAMES)
    except scenario_module.ScenarioError as exc:
        _emit({'status': 'REJECTED', 'scenario': str(path),
               'problems': [problem.detail() for problem in exc.problems]},
              render.problems(exc.problems, str(path)), args.json, sys.stderr)
        return None


def _repository(path):
    return SQLiteRepository(path)


# --- commands ------------------------------------------------------------------------

def command_run(args):
    scenario = _load(args.scenario, args)
    if scenario is None:
        return REFUSED
    repository = _repository(args.database)
    try:
        outcome = runner.execute_scenario(repository, scenario, run_id=args.run_id)
        sections = RUN_SECTIONS + (('timeline',) if args.trace else ())
        report = inspection.build(repository.inspect(outcome.run_id), outcome.run_id,
                                  sections=sections, full=args.full)
    finally:
        repository.close()
    text = render.run_report(report)
    if args.trace:
        text += '\n\ntimeline:\n' + render.trace(report['timeline'])
    _emit(report, text, args.json)
    return outcome.exit_code


def command_validate(args):
    scenario = _load(args.scenario, args)
    if scenario is None:
        return REFUSED
    _emit({'status': 'VALID', **scenario.summary()}, render.scenario_summary(scenario.summary()),
          args.json)
    return 0


def command_inspect(args):
    if args.all:
        sections = inspection.SECTIONS
    elif args.section:
        unknown = sorted(set(args.section) - set(inspection.SECTIONS))
        if unknown:
            print(f'REFUSED: unknown section(s) {", ".join(unknown)}\n'
                  f'available: {", ".join(inspection.SECTIONS)}', file=sys.stderr)
            return REFUSED
        sections = tuple(args.section)
    else:
        sections = inspection.DEFAULT_SECTIONS + (('timeline',) if args.trace else ())
    repository = _repository(args.database)
    try:
        stored = repository.inspect(args.run_id)
        report = inspection.build(stored, args.run_id, sections=sections, full=args.full)
    except (LookupError, ValueError) as exc:
        print(f'REFUSED: no run {args.run_id!r} in {args.database} ({exc})', file=sys.stderr)
        return REFUSED
    finally:
        repository.close()
    _emit(report, render.inspection(report), args.json)
    return 0


def command_list_runs(args):
    repository = _repository(args.database)
    try:
        rows = list(repository.runs())
    finally:
        repository.close()
    _emit({'runs': rows}, render.runs(rows), args.json)
    return 0


def command_examples(args):
    entries = list(catalogue())
    _emit({'examples': entries}, render.examples(entries), args.json)
    return 0


def command_evaluate(args):
    outcome = evaluation.run_suite(args.scenario or None, database=args.database)
    _emit(outcome, render.evaluation(outcome), args.json)
    return 0 if outcome['failed'] == 0 else 1


# --- parsing --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m swarm',
        description='Run and inspect a local multi-agent swarm over a validated scenario.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    def database(target):
        target.add_argument('--database', default=DEFAULT_DATABASE,
                            help=f'SQLite database file (default: {DEFAULT_DATABASE})')

    def as_json(target):
        target.add_argument('--json', action='store_true', help='emit the structured report')

    run = subparsers.add_parser('run', help='execute one scenario end to end')
    run.add_argument('--scenario', required=True,
                     help='a scenario file, or the name of a packaged example')
    run.add_argument('--run-id', default=None, help='use this run identity instead of a new one')
    run.add_argument('--trace', action='store_true', help='also print the causal timeline')
    run.add_argument('--full', action='store_true',
                     help='include execution-seam bookkeeping in the timeline')
    database(run)
    as_json(run)
    run.set_defaults(handler=command_run)

    validate = subparsers.add_parser('validate', help='check a scenario without running it')
    validate.add_argument('--scenario', required=True)
    as_json(validate)
    validate.set_defaults(handler=command_validate)

    inspect = subparsers.add_parser('inspect', help='inspect one persisted run')
    inspect.add_argument('run_id')
    inspect.add_argument('--section', action='append',
                         help='a section to show; repeatable. Available: '
                              + ', '.join(inspection.SECTIONS))
    inspect.add_argument('--all', action='store_true', help='show every section')
    inspect.add_argument('--trace', action='store_true', help='include the causal timeline')
    inspect.add_argument('--full', action='store_true',
                         help='include execution-seam bookkeeping in the timeline')
    database(inspect)
    as_json(inspect)
    inspect.set_defaults(handler=command_inspect)

    listing = subparsers.add_parser('list-runs', help='list the runs in a database')
    database(listing)
    as_json(listing)
    listing.set_defaults(handler=command_list_runs)

    packaged = subparsers.add_parser('examples', help='list the packaged scenarios')
    as_json(packaged)
    packaged.set_defaults(handler=command_examples)

    evaluate = subparsers.add_parser('evaluate', help='run the deterministic evaluation suite')
    evaluate.add_argument('--scenario', action='append',
                          help='evaluate only this scenario; repeatable')
    evaluate.add_argument('--database', default=':memory:',
                          help='SQLite database file (default: an in-memory database)')
    as_json(evaluate)
    evaluate.set_defaults(handler=command_evaluate)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except StorageError as exc:
        print(f'STORAGE_ERROR: {exc}', file=sys.stderr)
        return STORAGE
