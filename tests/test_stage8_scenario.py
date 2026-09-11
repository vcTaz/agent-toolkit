"""The scenario boundary: what configuration the host accepts, and what it refuses.

A scenario is the only way a run enters the system from outside, so this is where the
authority boundary is enforced at configuration time. Every refusal below is a case where
starting the run would have produced a misleading outcome — a criterion nothing can verify,
work no declared identity can execute, a task kind only the controller may author — and
each one is refused before any record exists rather than discovered halfway through.
"""
import json
import unittest
from stage8_support import MINIMAL, ScenarioCase, TOOL_NAMES, document, parse, with_task
from swarm import scenario as scenario_module
from swarm.domain import (Agent, AgentGroup, Role, RoleName, Run, RunState, Task,
                          validate_records)
from swarm.providers.scripted import ROLE_BY_INSTRUCTIONS, ScenarioProvider
from swarm.examples import catalogue, resolve
from swarm.persistence import SQLiteRepository


class AcceptanceTests(ScenarioCase):
    def test_the_fixture_document_is_a_valid_scenario(self):
        scenario = self.accept(MINIMAL)
        self.assertEqual(scenario.name, 'fixture')
        self.assertEqual([c.id for c in scenario.criteria], ['c1'])
        self.assertEqual(scenario.permissions, ('arithmetic',))

    def test_every_packaged_example_parses_or_is_refused_on_purpose(self):
        for entry in catalogue():
            with self.subTest(example=entry['name']):
                try:
                    scenario_module.load(resolve(entry['name']), tool_names=TOOL_NAMES)
                except scenario_module.ScenarioError as exc:
                    self.assertEqual(entry['name'], 'unsupported_verifier',
                                     f'unexpected refusal: {exc}')

    def test_numbers_become_the_task_description_the_provider_reads(self):
        scenario = self.accept(with_task(numbers=[7, 8]))
        self.assertEqual(json.loads(scenario.tasks[0]['description']), [7, 8])
        self.assertEqual(scenario.tasks[0]['objective'], 'sum [7, 8]')

    def test_an_explicit_objective_and_description_survive(self):
        scenario = self.accept(with_task(numbers=None, objective='look into it',
                                         description='free text'))
        self.assertEqual(scenario.tasks[0]['objective'], 'look into it')
        self.assertEqual(scenario.tasks[0]['description'], 'free text')

    def test_an_empty_task_graph_is_legal_configuration(self):
        # The MVP has no decomposer, so this is a run that will FAIL — but it is not a
        # malformed document, and refusing it here would hide the distinction.
        scenario = self.accept(document(tasks=[], groups=[],
                                        agents=[{'id': 'a'}, {'id': 'b'}]))
        self.assertEqual(scenario.tasks, ())

    def test_optional_criteria_are_allowed_beside_a_required_one(self):
        scenario = self.accept(document(acceptance_criteria=[
            dict(MINIMAL['acceptance_criteria'][0]),
            {'id': 'c2', 'description': 'nice to have', 'verifier_kind': 'arithmetic',
             'required': False}]))
        self.assertEqual([c.required for c in scenario.criteria], [True, False])


class SchemaRefusalTests(ScenarioCase):
    def test_an_unknown_top_level_field_is_refused(self):
        self.assertIn('UNKNOWN_FIELD', self.refuse(document(surprise=1)))

    def test_an_unknown_nested_field_is_refused(self):
        self.assertIn('UNKNOWN_FIELD', self.refuse(with_task(surprise=1)))

    def test_an_unsupported_schema_version_is_refused_before_the_shape(self):
        # A document written against another schema must not be reported as a pile of
        # unknown fields; the version is the only thing that explains it.
        self.assertEqual(self.refuse(document(schema_version=99, surprise=1)),
                         ['UNSUPPORTED_SCHEMA_VERSION'])

    def test_a_missing_required_field_is_named(self):
        payload = document()
        del payload['objective']
        self.assertIn('objective', ' '.join(self.paths(payload)))

    def test_a_non_object_document_is_refused(self):
        with self.assertRaises(scenario_module.ScenarioError):
            parse([1, 2, 3])


class CriterionRefusalTests(ScenarioCase):
    def test_no_acceptance_criteria_is_refused(self):
        self.assertIn('NO_ACCEPTANCE_CRITERIA', self.refuse(document(acceptance_criteria=[])))

    def test_duplicate_criterion_ids_are_refused(self):
        entry = MINIMAL['acceptance_criteria'][0]
        self.assertIn('DUPLICATE_CRITERION_ID',
                      self.refuse(document(acceptance_criteria=[dict(entry), dict(entry)])))

    def test_a_scenario_with_no_required_criterion_is_refused(self):
        entry = dict(MINIMAL['acceptance_criteria'][0], required=False)
        self.assertIn('NO_REQUIRED_CRITERION', self.refuse(document(acceptance_criteria=[entry])))

    def test_an_unsupported_verifier_kind_is_refused_before_the_run_exists(self):
        entry = dict(MINIMAL['acceptance_criteria'][0], verifier_kind='prose')
        self.assertEqual(self.refuse(document(acceptance_criteria=[entry])),
                         ['UNSUPPORTED_VERIFIER_KIND'])

    def test_the_default_tool_verifier_kind_is_not_silently_accepted(self):
        # ``Criterion.verifier_kind`` defaults to 'tool', which no policy implements. A
        # scenario may not inherit a kind that fails closed at promotion time.
        entry = dict(MINIMAL['acceptance_criteria'][0], verifier_kind='tool')
        self.assertIn('UNSUPPORTED_VERIFIER_KIND', self.refuse(document(acceptance_criteria=[entry])))

    def test_a_rejected_verifier_kind_does_not_cascade_into_its_tasks(self):
        entry = dict(MINIMAL['acceptance_criteria'][0], verifier_kind='prose')
        self.assertEqual(self.refuse(document(acceptance_criteria=[entry])),
                         ['UNSUPPORTED_VERIFIER_KIND'])

    def test_a_task_naming_an_undeclared_criterion_is_refused(self):
        self.assertIn('UNKNOWN_CRITERION', self.refuse(with_task(acceptance_criterion_ids=['cx'])))


class GraphRefusalTests(ScenarioCase):
    def test_a_self_dependency_is_refused(self):
        self.assertIn('SELF_DEPENDENCY', self.refuse(with_task(dependency_ids=['ta'])))

    def test_an_unknown_dependency_is_refused(self):
        self.assertIn('UNKNOWN_DEPENDENCY', self.refuse(with_task(dependency_ids=['nope'])))

    def test_a_dependency_cycle_is_refused(self):
        payload = document(tasks=[
            {'id': 'ta', 'numbers': [1], 'group_id': 'ga', 'dependency_ids': ['tb'],
             'acceptance_criterion_ids': ['c1']},
            {'id': 'tb', 'numbers': [2], 'group_id': 'ga', 'dependency_ids': ['ta'],
             'acceptance_criterion_ids': ['c1']}])
        self.assertIn('DEPENDENCY_CYCLE', self.refuse(payload))

    def test_a_long_dependency_chain_is_not_mistaken_for_a_cycle(self):
        payload = document(tasks=[
            {'id': f't{index}', 'numbers': [index + 1], 'group_id': 'ga',
             'acceptance_criterion_ids': ['c1'],
             'dependency_ids': [f't{index - 1}'] if index else []} for index in range(6)])
        self.assertEqual(len(self.accept(payload).tasks), 6)

    def test_duplicate_task_ids_are_refused(self):
        payload = document()
        payload['tasks'] = payload['tasks'] + [dict(payload['tasks'][0])]
        self.assertIn('DUPLICATE_TASK_ID', self.refuse(payload))

    def test_duplicate_agent_ids_are_refused(self):
        payload = document()
        payload['agents'] = payload['agents'] + [{'id': 'critic'}]
        self.assertIn('DUPLICATE_AGENT_ID', self.refuse(payload))

    def test_duplicate_group_ids_are_refused(self):
        payload = document(groups=[{'id': 'ga'}, {'id': 'ga'}])
        self.assertIn('DUPLICATE_GROUP_ID', self.refuse(payload))

    def test_an_unknown_group_on_a_task_is_refused(self):
        self.assertIn('UNKNOWN_GROUP', self.refuse(with_task(group_id='nowhere')))

    def test_an_unknown_group_on_an_agent_is_refused(self):
        payload = document()
        payload['agents'][0]['group_id'] = 'nowhere'
        self.assertIn('UNKNOWN_GROUP', self.refuse(payload))


class AuthorityRefusalTests(ScenarioCase):
    """A configuration file is not a way around the controller's authority."""

    def test_a_scenario_cannot_author_a_review_task(self):
        for kind in ('criticism', 'validation', 'final_review'):
            with self.subTest(kind=kind):
                self.assertIn('CONTROLLER_OWNED_TASK_KIND', self.refuse(with_task(kind=kind)))

    def test_a_scenario_cannot_author_synthesis_or_repair_work(self):
        for kind in ('synthesis', 'repair', 'reconsideration', 'follow_up'):
            with self.subTest(kind=kind):
                self.assertIn('CONTROLLER_OWNED_TASK_KIND', self.refuse(with_task(kind=kind)))

    def test_the_kinds_a_scenario_may_author_are_worker_kinds_only(self):
        for kind in scenario_module.SCENARIO_TASK_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(self.accept(with_task(kind=kind)).tasks[0]['kind'], kind)

    def test_a_task_cannot_declare_both_numbers_and_a_description(self):
        self.assertIn('CONFLICTING_FIELDS', self.refuse(with_task(description='text')))


class PermissionRefusalTests(ScenarioCase):
    def test_a_tool_the_host_does_not_register_is_refused(self):
        self.assertIn('UNKNOWN_TOOL', self.refuse(document(permissions=['shell'])))

    def test_a_task_requiring_a_tool_outside_the_run_permissions_is_refused(self):
        # The exact pair matters: capacity analysis raises the same code for the same task
        # from a different path, so asserting the code alone would not notice if the
        # task-level permission check stopped refusing.
        self.assertEqual(self.entries(with_task(required_tools=['shell'])),
                         [('IMPOSSIBLE_PERMISSIONS', 'tasks[0].required_tools')])

    def test_an_agent_granted_more_than_the_run_permits_is_refused(self):
        payload = document(permissions=[])
        payload['agents'][0]['permissions'] = ['arithmetic']
        payload['tasks'][0]['required_tools'] = []
        self.assertIn('IMPOSSIBLE_PERMISSIONS', self.refuse(payload))

    def test_work_no_agent_in_its_branch_can_execute_is_refused(self):
        payload = document()
        payload['agents'][0]['permissions'] = []
        self.assertEqual(self.entries(payload),
                         [('IMPOSSIBLE_PERMISSIONS', 'tasks[0]')])

    def test_a_role_allowlist_outside_the_run_permissions_is_refused(self):
        self.assertIn('IMPOSSIBLE_PERMISSIONS',
                      self.refuse(document(roles={'allowed_tools': ['shell']})))

    def test_too_few_unbranched_identities_to_review_anything_is_refused(self):
        payload = document(agents=[{'id': 'worker', 'group_id': 'ga'}, {'id': 'critic'}])
        self.assertIn('NO_REVIEW_CAPACITY', self.refuse(payload))

    def test_reviewers_that_may_not_use_the_verifier_tool_are_refused(self):
        payload = document(roles={'allowed_tools': ['arithmetic'], 'review_tools': []})
        self.assertEqual(self.entries(payload),
                         [('IMPOSSIBLE_PERMISSIONS', 'tasks[0].required_tools')])

    def test_no_agents_at_all_is_refused(self):
        self.assertIn('NO_AGENTS', self.refuse(document(agents=[])))


class LimitRefusalTests(ScenarioCase):
    def test_an_unknown_limit_is_refused(self):
        self.assertIn('UNKNOWN_FIELD', self.refuse(document(limits={'wall_clock': 5})))

    def test_a_zero_provider_request_limit_is_refused(self):
        self.assertIn('INVALID_LIMIT', self.refuse(document(limits={'provider_request_limit': 0})))

    def test_a_zero_cycle_limit_is_refused(self):
        self.assertIn('INVALID_LIMIT', self.refuse(document(limits={'cycle_limit': 0})))

    def test_a_negative_or_zero_timeout_is_refused(self):
        for value in (0, -1.5):
            with self.subTest(value=value):
                self.assertIn('INVALID_LIMIT',
                              self.refuse(document(limits={'execution_timeout': value})))

    def test_a_non_integer_limit_is_refused(self):
        self.assertIn('INVALID_LIMIT', self.refuse(document(limits={'task_limit': '32'})))

    def test_every_declared_integer_limit_reaches_the_run_record(self):
        limits = {name: max(minimum, 3) for name, minimum in
                  scenario_module.INTEGER_LIMITS.items()}
        scenario = self.accept(document(limits=limits))
        run = scenario_module.build_records(scenario, 'r')[0]
        for name, value in limits.items():
            with self.subTest(limit=name):
                self.assertEqual(getattr(run, name), value)

    def test_a_deadline_is_derived_rather_than_stored_as_a_run_limit(self):
        scenario = self.accept(document(limits={'deadline_seconds': 30}))
        run = scenario_module.build_records(scenario, 'r')[0]
        self.assertIsNotNone(run.deadline_at)
        self.assertNotIn('deadline_seconds', {f for f in dir(run)})


class ProviderRefusalTests(ScenarioCase):
    def test_an_unknown_provider_kind_is_refused(self):
        self.assertIn('UNKNOWN_PROVIDER_KIND', self.refuse(document(provider={'kind': 'openai'})))

    def test_a_refused_provider_does_not_cascade_into_every_agent(self):
        # Every agent inherits the provider key, so a refused provider block would
        # otherwise bury its own problem under one complaint per declared identity.
        self.assertEqual(self.refuse(document(provider={'kind': 'openai'})),
                         ['UNKNOWN_PROVIDER_KIND'])

    def test_an_unknown_provider_field_is_refused(self):
        self.assertIn('UNKNOWN_FIELD',
                      self.refuse(document(provider={'kind': 'scripted', 'temperature': 0.7})))

    def test_a_non_integer_scripted_claim_is_refused(self):
        self.assertIn('INVALID_TYPE',
                      self.refuse(document(provider={'kind': 'scripted', 'claims': {'ta': 'six'}})))

    def test_an_invalid_final_review_decision_is_refused(self):
        self.assertIn('INVALID_REVIEW_DECISION', self.refuse(document(
            provider={'kind': 'scripted', 'final_reviews': [{'decision': 'APPROVE'}]})))

    def test_an_invalid_critique_decision_is_refused(self):
        self.assertIn('INVALID_REVIEW_DECISION', self.refuse(document(
            provider={'kind': 'scripted', 'critiques': [{'decision': 'FAIL'}]})))

    def test_the_host_only_reconsideration_outcome_cannot_be_scripted(self):
        self.assertIn('INVALID_RECONSIDERATION_OUTCOME', self.refuse(document(
            provider={'kind': 'scripted', 'reconsideration': {'outcome': 'UNREPORTED'}})))

    def test_a_repair_missing_its_operands_is_refused(self):
        self.assertIn('MISSING_FIELD', self.refuse(document(
            provider={'kind': 'scripted', 'repairs': {'c1': {'total': 6}}})))

    def test_an_agent_naming_a_provider_the_scenario_does_not_configure_is_refused(self):
        payload = document()
        payload['agents'][0]['provider_key'] = 'openai'
        self.assertIn('UNKNOWN_PROVIDER_KEY', self.refuse(payload))


class ProviderBehaviourTests(unittest.TestCase):
    """The demonstration provider is a fixture, but it is shipped code with a contract."""

    @staticmethod
    def context(propagations):
        return {'task': {'id': 'ta', 'description': '[1, 2]'}, 'criteria': [],
                'propagations': propagations}

    def test_it_answers_only_the_deliveries_it_was_asked_to_consume(self):
        # A worker may answer a delivery it received and nothing else: the host refuses an
        # envelope that answers one this assignment does not owe
        # (RECONSIDERATION_TARGET_INELIGIBLE), so a provider that answered every entry in
        # its context would fail the assignment rather than help it.
        provider = ScenarioProvider({'kind': 'scripted'})
        answers = provider._answers(self.context([{'id': 'p1', 'consumable': True},
                                                  {'id': 'p2', 'consumable': False}]))
        self.assertEqual([a['propagation_id'] for a in answers['reconsiderations']], ['p1'])

    def test_it_reports_nothing_when_no_delivery_is_consumable(self):
        provider = ScenarioProvider({'kind': 'scripted'})
        self.assertEqual(provider._answers(self.context([{'id': 'p1', 'consumable': False}])), {})

    def test_the_scripted_outcome_and_reason_reach_every_answer(self):
        provider = ScenarioProvider({'kind': 'scripted',
                                     'reconsideration': {'outcome': 'APPLIED', 'reason': 'why'}})
        answer = provider._answers(
            self.context([{'id': 'p1', 'consumable': True}]))['reconsiderations'][0]
        self.assertEqual((answer['outcome'], answer['reason']), ('APPLIED', 'why'))

    def test_an_unregistered_role_is_refused_rather_than_guessed(self):
        self.assertIsNone(ROLE_BY_INSTRUCTIONS.get('you are a helpful assistant'))
        self.assertEqual(set(ROLE_BY_INSTRUCTIONS.values()), set(RoleName))


class RecordBuildingTests(ScenarioCase):
    """The records a scenario seeds are the canonical ones, and nothing else."""

    def setUp(self):
        self.repo = SQLiteRepository(':memory:')
        self.addCleanup(self.repo.close)

    def records(self, payload=None):
        return scenario_module.build_records(self.accept(payload or MINIMAL), 'r')

    def test_the_seeded_graph_satisfies_every_snapshot_invariant(self):
        validate_records(self.records())

    def test_a_seeded_run_starts_received_with_no_result(self):
        run = self.records()[0]
        self.assertIsInstance(run, Run)
        self.assertEqual(run.state, RunState.RECEIVED)
        self.assertIsNone(run.result_id)

    def test_every_registered_role_is_seeded(self):
        from swarm.domain import RoleName
        roles = {r.name for r in self.records() if isinstance(r, Role)}
        self.assertEqual(roles, set(RoleName))

    def test_group_membership_is_derived_from_the_declared_agents_and_tasks(self):
        group = next(r for r in self.records() if isinstance(r, AgentGroup))
        self.assertEqual(group.agent_ids, ('worker',))
        self.assertEqual(group.task_ids, ('ta',))

    def test_unbranched_agents_belong_to_no_group(self):
        agents = {a.id: a for a in self.records() if isinstance(a, Agent)}
        self.assertIsNone(agents['critic'].group_id)
        self.assertEqual(agents['worker'].group_id, 'ga')

    def test_tasks_carry_their_declared_criteria_tools_and_dependencies(self):
        payload = document(tasks=[
            {'id': 'ta', 'numbers': [1], 'group_id': 'ga', 'acceptance_criterion_ids': ['c1'],
             'required_tools': ['arithmetic'], 'tags': ['sums'], 'priority': 3},
            {'id': 'tb', 'numbers': [2], 'group_id': 'ga', 'acceptance_criterion_ids': ['c1'],
             'dependency_ids': ['ta'], 'required': False}])
        tasks = {t.id: t for t in self.records(payload) if isinstance(t, Task)}
        self.assertEqual(tasks['ta'].required_tools, ('arithmetic',))
        self.assertEqual(tasks['ta'].priority, 3)
        self.assertEqual(tasks['tb'].dependency_ids, ('ta',))
        self.assertFalse(tasks['tb'].required)

    def test_seeding_commits_the_records_and_one_event_each(self):
        records = self.records()
        scenario_module.seed(self.repo, 'r', records)
        stored = self.repo.inspect('r')
        self.assertEqual(len(stored.records), len(records))
        self.assertEqual(len(stored.events), len(records))
        self.assertEqual(stored.status, 'INCOMPLETE')


class LoadingTests(ScenarioCase):
    def test_an_unreadable_file_is_a_configuration_problem_not_a_crash(self):
        with self.assertRaises(scenario_module.ScenarioError) as caught:
            scenario_module.load('/nonexistent/scenario.json', tool_names=TOOL_NAMES)
        self.assertEqual([p.code for p in caught.exception.problems], ['UNREADABLE_SCENARIO'])

    def test_malformed_json_is_a_configuration_problem(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            handle.write('{not json')
            path = handle.name
        with self.assertRaises(scenario_module.ScenarioError) as caught:
            scenario_module.load(path, tool_names=TOOL_NAMES)
        self.assertEqual([p.code for p in caught.exception.problems], ['INVALID_JSON'])

    def test_a_packaged_example_resolves_by_name_bare_name_and_path(self):
        direct = resolve('arithmetic_minimal')
        self.assertIsNotNone(direct)
        self.assertEqual(resolve('arithmetic_minimal.json'), direct)
        self.assertEqual(resolve('examples/arithmetic_minimal.json'), direct)
        self.assertEqual(resolve(str(direct)), direct)

    def test_an_unknown_reference_resolves_to_nothing(self):
        self.assertIsNone(resolve('no_such_scenario'))


if __name__ == '__main__':
    unittest.main()
