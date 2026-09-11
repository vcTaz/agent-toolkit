"""Scenario configuration: a validated, fail-closed description of one runnable run.

A scenario is *configuration*, not a second architecture. Every field maps onto a canonical
record — ``Run``, ``Criterion``, ``AgentGroup``, ``Agent``, ``Task`` — and carries the name
of the field it fills, so a run has exactly one vocabulary whether it is described in JSON
or in Python.

Validation refuses; it never repairs. An unknown field, an unsupported schema version, an
unknown role, an unsupported verifier kind, an invalid dependency, an impossible permission
or an invalid limit is reported before any run record exists, so a misconfigured scenario
can never present itself as a run that merely failed to find evidence.

Two boundaries are deliberate:

- **Controller-owned task kinds are refused.** A scenario may declare exploration,
  specialization and collaboration work. Criticism, validation, reconsideration, follow-up,
  repair, synthesis and final review are authored by the controller alone, and a
  configuration file is not a way around that.
- **An unsupported verifier kind is refused here**, not discovered at promotion time. The
  registry decides what can be verified; a criterion it cannot verify would make a run
  exhaust correctly and uselessly, so the run is never started.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from .domain import Agent, AgentGroup, Criterion, Run, Task
from .events import EventDraft, EventType
from .roles import default_roles
from .verification import VerificationRegistry

SCHEMA_VERSION = 1

SCENARIO_FIELDS = ('schema_version', 'name', 'description', 'objective', 'acceptance_criteria',
                   'permissions', 'limits', 'roles', 'groups', 'agents', 'tasks', 'provider',
                   'expect')
REQUIRED_FIELDS = ('schema_version', 'name', 'objective', 'acceptance_criteria', 'agents', 'tasks',
                   'provider')

CRITERION_FIELDS = ('id', 'description', 'verifier_kind', 'required')
GROUP_FIELDS = ('id', 'tags')
AGENT_FIELDS = ('id', 'group_id', 'permissions', 'provider_key')
TASK_FIELDS = ('id', 'objective', 'description', 'numbers', 'kind', 'group_id', 'priority',
               'required', 'tags', 'dependency_ids', 'acceptance_criterion_ids', 'required_tools')
ROLE_FIELDS = ('allowed_tools', 'review_tools')

SCENARIO_TASK_KINDS = ('exploration', 'specialization', 'collaboration')
"""The kinds a scenario may author. Everything else is controller-owned work."""

INTEGER_LIMITS = {'provider_request_limit': 1, 'tool_call_limit': 0, 'concurrency_limit': 1,
                  'task_limit': 1, 'assignment_attempt_limit': 1, 'cycle_limit': 1,
                  'no_progress_limit': 1, 'repair_round_limit': 0,
                  'presentation_revision_limit': 0, 'synthesis_attempt_limit': 1}
"""Run limit fields a scenario may set, with the smallest value the run machinery accepts."""
FLOAT_LIMITS = {'execution_timeout': 0.0, 'deadline_seconds': 0.0}
DERIVED_LIMITS = ('deadline_seconds',)
"""Not a ``Run`` field: it fixes ``deadline_at`` relative to the moment the run is created."""

MIN_UNBRANCHED_AGENTS = 2
"""Criticism and validation of one finding need two identities that are neither the author
nor each other. A scenario with fewer can never validate anything it discovers."""


@dataclass(frozen=True)
class Problem:
    code: str
    path: str
    message: str

    def __str__(self):
        return f'{self.code} at {self.path}: {self.message}'

    def detail(self):
        return {'code': self.code, 'path': self.path, 'message': self.message}


class ScenarioError(ValueError):
    """A scenario the host refuses to run, with every problem it found."""

    def __init__(self, problems):
        self.problems = tuple(problems)
        super().__init__('; '.join(str(problem) for problem in self.problems))


@dataclass(frozen=True)
class Scenario:
    """A validated scenario. Construction is only ever through ``parse``."""
    name: str
    objective: str
    description: str
    criteria: tuple[Criterion, ...]
    permissions: tuple[str, ...]
    limits: dict
    role_tools: dict
    groups: tuple[dict, ...]
    agents: tuple[dict, ...]
    tasks: tuple[dict, ...]
    provider: dict
    expect: dict = field(default_factory=dict)
    source: str = ''

    @property
    def deadline_seconds(self):
        return self.limits.get('deadline_seconds')

    def summary(self):
        return {'name': self.name, 'objective': self.objective, 'description': self.description,
                'criteria': [{'id': c.id, 'description': c.description,
                              'verifier_kind': c.verifier_kind, 'required': c.required}
                             for c in self.criteria],
                'permissions': list(self.permissions),
                'groups': [g['id'] for g in self.groups],
                'agents': [a['id'] for a in self.agents],
                'tasks': [t['id'] for t in self.tasks],
                'provider_kind': self.provider.get('kind'),
                'limits': {k: v for k, v in sorted(self.limits.items())},
                'source': self.source}


# --- validation ------------------------------------------------------------------

class _Check:
    """Accumulates every problem rather than stopping at the first one.

    A configuration error is cheapest to fix when the whole list is visible, and a partial
    report invites fixing one field at a time until something unrelated finally runs.
    """

    def __init__(self, tool_names, verifier_kinds, provider_kinds):
        self.problems = []
        self.tool_names = frozenset(tool_names)
        self.verifier_kinds = frozenset(verifier_kinds)
        self.provider_kinds = frozenset(provider_kinds)

    def fail(self, code, path, message):
        self.problems.append(Problem(code, path, message))
        return False

    def obj(self, value, path, allowed, required=()):
        if not isinstance(value, dict):
            return self.fail('INVALID_TYPE', path, 'expected an object')
        ok = True
        for name in sorted(set(value) - set(allowed)):
            ok = self.fail('UNKNOWN_FIELD', f'{path}.{name}',
                           'not a scenario field; allowed: ' + ', '.join(sorted(allowed)))
        for name in required:
            if name not in value:
                ok = self.fail('MISSING_FIELD', f'{path}.{name}', 'is required')
        return ok

    def text(self, value, path, *, allow_empty=False, limit=4000):
        if not isinstance(value, str) or len(value) > limit:
            return self.fail('INVALID_TYPE', path, f'expected a string of at most {limit} characters')
        if not allow_empty and not value.strip():
            return self.fail('EMPTY_VALUE', path, 'must not be empty')
        return True

    def flag(self, value, path):
        if type(value) is not bool:
            return self.fail('INVALID_TYPE', path, 'expected true or false')
        return True

    def names(self, value, path, *, limit=32):
        if not isinstance(value, list) or len(value) > limit:
            return self.fail('INVALID_TYPE', path, f'expected an array of at most {limit} strings')
        return all(self.text(item, f'{path}[{index}]', limit=128)
                   for index, item in enumerate(value))

    def identifier(self, value, path):
        if not isinstance(value, str) or not value or len(value) > 128 or value.strip() != value:
            return self.fail('INVALID_IDENTIFIER', path,
                             'expected a non-empty identifier of at most 128 characters')
        return True


def _check_criteria(check, raw):
    """Return the admissible criteria and every id the author declared.

    The declared set is wider than the admissible one on purpose: a criterion refused for
    an unsupported verifier kind still counts as *declared*, so a task that references it
    reports nothing further and the author sees one problem rather than a cascade.
    """
    criteria, seen = [], set()
    if not isinstance(raw, list) or not raw:
        check.fail('NO_ACCEPTANCE_CRITERIA', 'acceptance_criteria',
                   'a run must declare at least one acceptance criterion')
        return (), frozenset()
    for index, item in enumerate(raw):
        path = f'acceptance_criteria[{index}]'
        if not check.obj(item, path, CRITERION_FIELDS, ('id', 'description', 'verifier_kind')):
            continue
        if not (check.identifier(item.get('id'), f'{path}.id')
                and check.text(item.get('description'), f'{path}.description')):
            continue
        if item['id'] in seen:
            check.fail('DUPLICATE_CRITERION_ID', f'{path}.id', f'{item["id"]} is declared twice')
            continue
        seen.add(item['id'])
        kind = item.get('verifier_kind')
        if kind not in check.verifier_kinds:
            check.fail('UNSUPPORTED_VERIFIER_KIND', f'{path}.verifier_kind',
                       f'{kind!r} has no verification policy; supported kinds: '
                       + ', '.join(sorted(check.verifier_kinds)))
            continue
        required = item.get('required', True)
        if not check.flag(required, f'{path}.required'):
            continue
        criteria.append(Criterion(id=item['id'], description=item['description'],
                                  verifier_kind=kind, required=required))
    if criteria and not any(c.required for c in criteria):
        check.fail('NO_REQUIRED_CRITERION', 'acceptance_criteria',
                   'a run must declare at least one required criterion')
    return tuple(criteria), frozenset(seen)


def _check_limits(check, raw):
    if raw is None:
        return {}
    if not check.obj(raw, 'limits', tuple(INTEGER_LIMITS) + tuple(FLOAT_LIMITS)):
        return {}
    limits = {}
    for name, value in sorted(raw.items()):
        path = f'limits.{name}'
        if name in INTEGER_LIMITS:
            if type(value) is not int or value < INTEGER_LIMITS[name]:
                check.fail('INVALID_LIMIT', path,
                           f'expected an integer of at least {INTEGER_LIMITS[name]}')
                continue
        elif name in FLOAT_LIMITS:
            if type(value) not in (int, float) or value <= FLOAT_LIMITS[name]:
                check.fail('INVALID_LIMIT', path,
                           f'expected a number greater than {FLOAT_LIMITS[name]}')
                continue
            value = float(value)
        limits[name] = value
    return limits


def _check_permissions(check, raw):
    if raw is None:
        return ()
    if not check.names(raw, 'permissions'):
        return ()
    unknown = sorted(set(raw) - check.tool_names)
    if unknown:
        check.fail('UNKNOWN_TOOL', 'permissions',
                   f'{", ".join(unknown)} not registered; available: '
                   + (', '.join(sorted(check.tool_names)) or 'none'))
    return tuple(dict.fromkeys(raw))


def _check_role_tools(check, raw, permissions):
    if raw is None:
        return {'allowed_tools': permissions, 'review_tools': permissions}
    if not check.obj(raw, 'roles', ROLE_FIELDS):
        return {'allowed_tools': permissions, 'review_tools': permissions}
    tools = {}
    for name in ROLE_FIELDS:
        value = raw.get(name)
        if value is None:
            tools[name] = permissions
            continue
        if not check.names(value, f'roles.{name}'):
            tools[name] = permissions
            continue
        outside = sorted(set(value) - set(permissions))
        if outside:
            check.fail('IMPOSSIBLE_PERMISSIONS', f'roles.{name}',
                       f'{", ".join(outside)} is not among the run permissions')
        tools[name] = tuple(dict.fromkeys(value))
    return tools


def _check_groups(check, raw):
    groups, seen = [], set()
    if raw is None:
        return ()
    if not isinstance(raw, list):
        check.fail('INVALID_TYPE', 'groups', 'expected an array')
        return ()
    for index, item in enumerate(raw):
        path = f'groups[{index}]'
        if not check.obj(item, path, GROUP_FIELDS, ('id',)):
            continue
        if not check.identifier(item.get('id'), f'{path}.id'):
            continue
        if item['id'] in seen:
            check.fail('DUPLICATE_GROUP_ID', f'{path}.id', f'{item["id"]} is declared twice')
            continue
        seen.add(item['id'])
        tags = item.get('tags', [])
        if not check.names(tags, f'{path}.tags'):
            continue
        groups.append({'id': item['id'], 'tags': tuple(tags)})
    return tuple(groups)


def _check_agents(check, raw, group_ids, permissions, provider_key):
    agents, seen = [], set()
    if not isinstance(raw, list) or not raw:
        check.fail('NO_AGENTS', 'agents', 'a run needs at least one agent identity')
        return ()
    for index, item in enumerate(raw):
        path = f'agents[{index}]'
        if not check.obj(item, path, AGENT_FIELDS, ('id',)):
            continue
        if not check.identifier(item.get('id'), f'{path}.id'):
            continue
        if item['id'] in seen:
            check.fail('DUPLICATE_AGENT_ID', f'{path}.id', f'{item["id"]} is declared twice')
            continue
        seen.add(item['id'])
        group_id = item.get('group_id')
        if group_id is not None:
            if not check.identifier(group_id, f'{path}.group_id'):
                continue
            if group_id not in group_ids:
                check.fail('UNKNOWN_GROUP', f'{path}.group_id', f'{group_id} is not declared')
                continue
        granted = item.get('permissions', list(permissions))
        if not check.names(granted, f'{path}.permissions'):
            continue
        outside = sorted(set(granted) - set(permissions))
        if outside:
            check.fail('IMPOSSIBLE_PERMISSIONS', f'{path}.permissions',
                       f'{", ".join(outside)} is not among the run permissions')
            continue
        # ``provider_key`` is None when the provider block was itself refused: reporting
        # every agent as naming an unknown provider would bury the one real problem.
        key = item.get('provider_key', provider_key or '')
        if provider_key is not None:
            if not check.identifier(key, f'{path}.provider_key'):
                continue
            if key != provider_key:
                check.fail('UNKNOWN_PROVIDER_KEY', f'{path}.provider_key',
                           f'{key} is not the provider this scenario configures ({provider_key})')
                continue
        agents.append({'id': item['id'], 'group_id': group_id,
                       'permissions': tuple(dict.fromkeys(granted)), 'provider_key': key})
    return tuple(agents)


def _check_task(check, item, path, declared_criteria, group_ids, permissions):
    if not check.obj(item, path, TASK_FIELDS, ('id',)):
        return None
    if not check.identifier(item.get('id'), f'{path}.id'):
        return None
    kind = item.get('kind', 'exploration')
    if kind not in SCENARIO_TASK_KINDS:
        check.fail('CONTROLLER_OWNED_TASK_KIND', f'{path}.kind',
                   f'{kind!r} is authored by the controller; a scenario may declare '
                   + ', '.join(SCENARIO_TASK_KINDS))
        return None
    numbers, description = item.get('numbers'), item.get('description')
    if numbers is not None:
        if description is not None:
            check.fail('CONFLICTING_FIELDS', f'{path}.numbers',
                       'a task declares either numbers or description, never both')
            return None
        if (not isinstance(numbers, list) or not numbers or len(numbers) > 64
                or any(type(n) is not int for n in numbers)):
            check.fail('INVALID_TYPE', f'{path}.numbers',
                       'expected an array of 1 to 64 integers')
            return None
        description = json.dumps(numbers)
    elif description is None:
        description = ''
    elif not check.text(description, f'{path}.description', allow_empty=True):
        return None
    objective = item.get('objective', f'sum {numbers}' if numbers is not None else '')
    if not check.text(objective, f'{path}.objective'):
        return None
    group_id = item.get('group_id')
    if group_id is not None:
        if not check.identifier(group_id, f'{path}.group_id'):
            return None
        if group_id not in group_ids:
            check.fail('UNKNOWN_GROUP', f'{path}.group_id', f'{group_id} is not declared')
            return None
    linked = item.get('acceptance_criterion_ids', [])
    if not check.names(linked, f'{path}.acceptance_criterion_ids'):
        return None
    unknown = sorted(set(linked) - set(declared_criteria))
    if unknown:
        check.fail('UNKNOWN_CRITERION', f'{path}.acceptance_criterion_ids',
                   f'{", ".join(unknown)} is not an acceptance criterion of this run')
        return None
    tools = item.get('required_tools', [])
    if not check.names(tools, f'{path}.required_tools'):
        return None
    outside = sorted(set(tools) - set(permissions))
    if outside:
        check.fail('IMPOSSIBLE_PERMISSIONS', f'{path}.required_tools',
                   f'{", ".join(outside)} is not among the run permissions')
        return None
    tags, dependencies = item.get('tags', []), item.get('dependency_ids', [])
    if not (check.names(tags, f'{path}.tags') and check.names(dependencies, f'{path}.dependency_ids')):
        return None
    priority, required = item.get('priority', 0), item.get('required', True)
    if type(priority) is not int or not -100 <= priority <= 100:
        check.fail('INVALID_TYPE', f'{path}.priority', 'expected an integer between -100 and 100')
        return None
    if not check.flag(required, f'{path}.required'):
        return None
    return {'id': item['id'], 'objective': objective, 'description': description, 'kind': kind,
            'group_id': group_id, 'priority': priority, 'required': required,
            'tags': tuple(tags), 'dependency_ids': tuple(dict.fromkeys(dependencies)),
            'acceptance_criterion_ids': tuple(dict.fromkeys(linked)),
            'required_tools': tuple(dict.fromkeys(tools)), 'numbers': numbers}


def _check_dependencies(check, tasks):
    """Unknown, self and cyclic task dependencies, reported per offending task."""
    identities = {task['id'] for task in tasks}
    edges = {}
    for index, task in enumerate(tasks):
        path = f'tasks[{index}].dependency_ids'
        kept = []
        for dependency in task['dependency_ids']:
            if dependency == task['id']:
                check.fail('SELF_DEPENDENCY', path, 'a task cannot depend on itself')
            elif dependency not in identities:
                check.fail('UNKNOWN_DEPENDENCY', path, f'{dependency} is not a declared task')
            else:
                kept.append(dependency)
        edges[task['id']] = kept
    colour = {}
    for start in sorted(edges):
        stack = [(start, False)]
        while stack:
            identity, expanded = stack.pop()
            if expanded:
                colour[identity] = 'done'
                continue
            if colour.get(identity) == 'done':
                continue
            if colour.get(identity) == 'open':
                check.fail('DEPENDENCY_CYCLE', 'tasks',
                           f'{identity} takes part in a dependency cycle')
                colour[identity] = 'done'
                continue
            colour[identity] = 'open'
            stack.append((identity, True))
            stack += [(link, False) for link in edges[identity]]


def _check_capacity(check, tasks, agents, role_tools):
    """Whether the declared identities could execute the declared work at all."""
    if not tasks:
        return
    unbranched = [a for a in agents if a['group_id'] is None]
    if len(unbranched) < MIN_UNBRANCHED_AGENTS:
        check.fail('NO_REVIEW_CAPACITY', 'agents',
                   f'criticism and validation need {MIN_UNBRANCHED_AGENTS} agents outside every '
                   f'branch; {len(unbranched)} declared')
    allowed = set(role_tools['allowed_tools'])
    review = set(role_tools['review_tools'])
    for index, task in enumerate(tasks):
        needed = set(task['required_tools'])
        workers = [a for a in agents if a['group_id'] == task['group_id']
                   and needed <= set(a['permissions']) & allowed]
        if not workers:
            check.fail('IMPOSSIBLE_PERMISSIONS', f'tasks[{index}]',
                       f'no declared agent in group {task["group_id"]!r} can execute '
                       f'{", ".join(sorted(needed)) or "this task"}')
        reviewers = [a for a in unbranched if needed <= set(a['permissions']) & review]
        if needed and len(reviewers) < MIN_UNBRANCHED_AGENTS:
            check.fail('IMPOSSIBLE_PERMISSIONS', f'tasks[{index}].required_tools',
                       f'fewer than {MIN_UNBRANCHED_AGENTS} unbranched agents may use '
                       f'{", ".join(sorted(needed))}')


def _check_provider(check, raw):
    """The provider block, validated by the provider that owns its vocabulary."""
    from .providers.scripted import check_provider_config
    if not isinstance(raw, dict):
        check.fail('INVALID_TYPE', 'provider', 'expected an object')
        return {}
    kind = raw.get('kind')
    if kind not in check.provider_kinds:
        check.fail('UNKNOWN_PROVIDER_KIND', 'provider.kind',
                   f'{kind!r} is not a configured provider; available: '
                   + ', '.join(sorted(check.provider_kinds)))
        return {}
    check.problems.extend(check_provider_config(raw))
    return dict(raw)


def parse(payload, *, tool_names=('arithmetic',), source=''):
    """Validate one scenario document and return a ``Scenario``, or raise ``ScenarioError``.

    ``payload`` is already-decoded JSON. Nothing is defaulted for a field the author got
    wrong: a rejected scenario produces problems, never a partially repaired run.
    """
    from .providers.scripted import PROVIDER_KINDS
    check = _Check(tool_names, {p.verifier_kind for p in VerificationRegistry().policies},
                   PROVIDER_KINDS)
    if not isinstance(payload, dict):
        check.fail('INVALID_TYPE', 'scenario', 'expected an object')
        raise ScenarioError(check.problems)
    # The version is checked before the shape: a document written against another schema
    # would otherwise be reported as a list of unknown fields, which explains nothing.
    if payload.get('schema_version') != SCHEMA_VERSION:
        check.fail('UNSUPPORTED_SCHEMA_VERSION', 'schema_version',
                   f'this host reads scenario schema {SCHEMA_VERSION}; '
                   f'the file declares {payload.get("schema_version")!r}')
        raise ScenarioError(check.problems)
    if not check.obj(payload, 'scenario', SCENARIO_FIELDS, REQUIRED_FIELDS):
        raise ScenarioError(check.problems)
    check.identifier(payload.get('name'), 'name')
    check.text(payload.get('objective'), 'objective')
    description = payload.get('description', '')
    check.text(description, 'description', allow_empty=True)
    criteria, declared_criteria = _check_criteria(check, payload.get('acceptance_criteria'))
    permissions = _check_permissions(check, payload.get('permissions'))
    limits = _check_limits(check, payload.get('limits'))
    role_tools = _check_role_tools(check, payload.get('roles'), permissions)
    groups = _check_groups(check, payload.get('groups'))
    provider = _check_provider(check, payload.get('provider'))
    agents = _check_agents(check, payload.get('agents'), {g['id'] for g in groups}, permissions,
                           provider.get('kind'))
    raw_tasks = payload.get('tasks')
    tasks = []
    if not isinstance(raw_tasks, list):
        check.fail('INVALID_TYPE', 'tasks', 'expected an array (an empty one declares no work)')
    else:
        seen = set()
        for index, item in enumerate(raw_tasks):
            task = _check_task(check, item, f'tasks[{index}]', declared_criteria,
                               {g['id'] for g in groups}, permissions)
            if task is None:
                continue
            if task['id'] in seen:
                check.fail('DUPLICATE_TASK_ID', f'tasks[{index}].id',
                           f'{task["id"]} is declared twice')
                continue
            seen.add(task['id'])
            tasks.append(task)
        _check_dependencies(check, tasks)
        _check_capacity(check, tasks, agents, role_tools)
    expect = payload.get('expect', {})
    if not isinstance(expect, dict):
        check.fail('INVALID_TYPE', 'expect', 'expected an object')
        expect = {}
    if check.problems:
        raise ScenarioError(check.problems)
    return Scenario(name=payload['name'], objective=payload['objective'], description=description,
                    criteria=criteria, permissions=permissions, limits=limits,
                    role_tools=role_tools, groups=groups, agents=agents, tasks=tuple(tasks),
                    provider=provider, expect=expect, source=source)


def load(path, *, tool_names=('arithmetic',)):
    """Read and validate a scenario file. A malformed document is a configuration error."""
    try:
        with open(path, encoding='utf-8') as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise ScenarioError([Problem('UNREADABLE_SCENARIO', str(path), str(exc))]) from exc
    except ValueError as exc:
        raise ScenarioError([Problem('INVALID_JSON', str(path), str(exc))]) from exc
    return parse(payload, tool_names=tool_names, source=str(path))


# --- records ---------------------------------------------------------------------

def build_records(scenario, run_id, *, created_at=None):
    """The canonical records one validated scenario seeds a run with.

    Nothing here is a new kind of state: this is the same ``Run``/``Role``/``Agent``/
    ``AgentGroup``/``Task`` graph the test fixtures build by hand.
    """
    limits = {name: value for name, value in scenario.limits.items() if name not in DERIVED_LIMITS}
    if scenario.deadline_seconds is not None:
        moment = created_at or datetime.now(timezone.utc)
        limits['deadline_at'] = (moment + timedelta(seconds=scenario.deadline_seconds)).isoformat()
    run = Run(id=run_id, objective=scenario.objective, acceptance_criteria=scenario.criteria,
              permissions=scenario.permissions, **limits)
    roles = default_roles(allowed_tools=scenario.role_tools['allowed_tools'],
                          review_tools=scenario.role_tools['review_tools'])
    members = {group['id']: [] for group in scenario.groups}
    agents = []
    for entry in scenario.agents:
        agents.append(Agent(id=entry['id'], run_id=run_id, group_id=entry['group_id'],
                            permissions=entry['permissions'], provider_key=entry['provider_key']))
        if entry['group_id'] is not None:
            members[entry['group_id']].append(entry['id'])
    work = {group['id']: [] for group in scenario.groups}
    tasks = []
    for entry in scenario.tasks:
        tasks.append(Task(id=entry['id'], run_id=run_id, objective=entry['objective'],
                          description=entry['description'], kind=entry['kind'],
                          group_id=entry['group_id'], priority=entry['priority'],
                          required=entry['required'], tags=entry['tags'],
                          dependency_ids=entry['dependency_ids'],
                          acceptance_criterion_ids=entry['acceptance_criterion_ids'],
                          required_tools=entry['required_tools']))
        if entry['group_id'] is not None:
            work[entry['group_id']].append(entry['id'])
    groups = [AgentGroup(id=group['id'], run_id=run_id, tags=group['tags'],
                         agent_ids=tuple(members[group['id']]), task_ids=tuple(work[group['id']]))
              for group in scenario.groups]
    return (run, *roles, *groups, *agents, *tasks)


def seed(repository, run_id, records):
    """Commit the scenario's records as the run's first transaction."""
    events = [EventDraft(type=EventType.RUN_CREATED if record.id == run_id
                         else EventType.RECORD_CHANGED,
                         record_id=record.id, record_revision=record.revision,
                         correlation_id=run_id) for record in records]
    repository.commit(run_id, records, events)
    return records
