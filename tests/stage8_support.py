"""Shared Stage-8 fixtures: scenario documents, captured CLI output and a run cache.

The end-to-end examples are executed once per process and reused, because they are real
runs of the real controller: every assertion below is made against a run that actually
happened, not against a fixture that describes one.
"""
import atexit
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from swarm import cli, inspection, runner, scenario as scenario_module
from swarm.examples import resolve

TOOL_NAMES = ('arithmetic',)

MINIMAL = {
    'schema_version': 1,
    'name': 'fixture',
    'objective': 'sum one integer list',
    'acceptance_criteria': [
        {'id': 'c1', 'description': 'the total is correct', 'verifier_kind': 'arithmetic'}],
    'permissions': ['arithmetic'],
    'groups': [{'id': 'ga', 'tags': ['sums']}],
    'agents': [{'id': 'worker', 'group_id': 'ga'}, {'id': 'critic'}, {'id': 'validator'}],
    'tasks': [{'id': 'ta', 'numbers': [1, 2, 3], 'group_id': 'ga',
               'acceptance_criterion_ids': ['c1'], 'required_tools': ['arithmetic']}],
    'provider': {'kind': 'scripted'},
}


def document(**overrides):
    """A valid scenario document with the named top-level fields replaced."""
    payload = copy.deepcopy(MINIMAL)
    payload.update(copy.deepcopy(overrides))
    return payload


def with_task(**fields):
    """The fixture document with its one task's fields replaced."""
    payload = document()
    payload['tasks'][0].update(fields)
    return payload


def parse(payload):
    return scenario_module.parse(payload, tool_names=TOOL_NAMES)


class ScenarioCase(unittest.TestCase):
    """Assertions about what a scenario validator accepts and what it refuses."""

    def refuse(self, payload):
        """The problem codes raised for one document, sorted. Fails if it validated."""
        with self.assertRaises(scenario_module.ScenarioError) as caught:
            parse(payload)
        return sorted({problem.code for problem in caught.exception.problems})

    def paths(self, payload):
        with self.assertRaises(scenario_module.ScenarioError) as caught:
            parse(payload)
        return sorted(problem.path for problem in caught.exception.problems)

    def entries(self, payload):
        """Every problem as ``(code, path)``, in report order.

        Stronger than ``refuse``: two different checks can raise the same code, so a test
        that only asserts the code cannot tell which one is actually doing the refusing.
        """
        with self.assertRaises(scenario_module.ScenarioError) as caught:
            parse(payload)
        return [(problem.code, problem.path) for problem in caught.exception.problems]

    def accept(self, payload):
        return parse(payload)


# --- CLI capture ------------------------------------------------------------------

class Captured:
    __slots__ = ('code', 'out', 'err')

    def __init__(self, code, out, err):
        self.code, self.out, self.err = code, out, err

    def json(self):
        return json.loads(self.out)


def invoke(*argv):
    """Run one CLI command, capturing its exit code and both streams."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return Captured(code, out.getvalue(), err.getvalue())


# --- executed examples --------------------------------------------------------------

_WORKSPACE = tempfile.TemporaryDirectory(prefix='swarm-stage8-')
atexit.register(_WORKSPACE.cleanup)
_RUNS = {}


class Executed:
    """One packaged example, actually run, with its persisted database kept open-able."""
    __slots__ = ('name', 'run_id', 'database', 'outcome', 'report')

    def __init__(self, name, run_id, database, outcome, report):
        self.name, self.run_id, self.database = name, run_id, database
        self.outcome, self.report = outcome, report

    def section(self, name):
        return self.report[name]

    def findings(self, status=None):
        return [f for f in self.report['findings']
                if status is None or f['status'] == status]

    def claims(self, status):
        return sorted(f['claim'] for f in self.findings(status))

    def reviews(self, kind):
        return [r for r in self.report['reviews'] if r['kind'] == kind]

    def events(self, *types):
        wanted = set(types)
        return [e for e in self.report['timeline'] if e['type'] in wanted]


def database_path(name):
    return str(Path(_WORKSPACE.name) / f'{name}.db')


def executed(name):
    """Execute one packaged example once per process; reuse it everywhere after that."""
    if name not in _RUNS:
        from swarm.persistence import SQLiteRepository
        scenario = scenario_module.load(resolve(name), tool_names=TOOL_NAMES)
        database = database_path(name)
        repository = SQLiteRepository(database)
        try:
            outcome = runner.execute_scenario(repository, scenario)
            report = inspection.build(repository.inspect(outcome.run_id), outcome.run_id,
                                      sections=inspection.SECTIONS, full=True)
        finally:
            repository.close()
        _RUNS[name] = Executed(name, outcome.run_id, database, outcome, report)
    return _RUNS[name]


class ExampleCase(unittest.TestCase):
    """A test case over one already-executed packaged example."""
    example = 'arithmetic_minimal'

    @classmethod
    def setUpClass(cls):
        # Not ``cls.run``: ``TestCase.run`` is the method unittest calls to run the test.
        cls.execution = executed(cls.example)

    @property
    def report(self):
        return self.execution.report
