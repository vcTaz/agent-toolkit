"""Running one validated scenario end to end.

This is the only place a scenario becomes a run, and it deliberately uses the same
``WorkController`` the test suite drives: there is no CLI-only orchestration path, and
nothing here can reach a terminal state the workflow would not have reached on its own.
"""
import asyncio
from dataclasses import dataclass
from uuid import uuid4
from .domain import RunState
from .orchestration import WorkController
from .providers.scripted import build_provider
from .scenario import build_records, seed
from .tools.arithmetic import ArithmeticTool


def default_tools():
    """The host tool registry for the shipped demonstration."""
    return {'arithmetic': ArithmeticTool()}


TOOL_NAMES = tuple(sorted(default_tools()))

EXIT_CODES = {RunState.COMPLETED: 0, RunState.EXHAUSTED: 1, RunState.FAILED: 2,
              RunState.CANCELLED: 3}
"""A terminal state is an outcome, not a crash: EXHAUSTED and FAILED are reported, and
they are told apart by the exit code as well as by the report."""
CONFIG_REJECTED = 4
STORAGE_ERROR = 5
UNKNOWN_STATE = 1


def new_run_id(scenario):
    return f'{scenario.name}-{uuid4().hex[:12]}'


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    state: RunState
    exit_code: int
    snapshot: dict


def execute_scenario(repository, scenario, *, run_id=None, tools=None):
    """Seed one run from a validated scenario and drive it to a terminal state."""
    run_id = run_id or new_run_id(scenario)
    seed(repository, run_id, build_records(scenario, run_id))
    controller = WorkController(repository, run_id, build_provider(scenario.provider),
                                tools if tools is not None else default_tools())
    snapshot = asyncio.run(controller.run_until_idle())
    state = snapshot[run_id].state
    return RunOutcome(run_id, state, EXIT_CODES.get(state, UNKNOWN_STATE), snapshot)
