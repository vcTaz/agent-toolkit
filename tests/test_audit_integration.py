import json
import unittest
from swarm.domain import Run
from swarm.events import EventDraft, EventType
from swarm.persistence import SQLiteRepository
from swarm.contracts import ExecutionContext, ModelResponse, Budget, ExecutionError, ToolCall
from swarm.domain import Role, RoleName
from swarm.providers.fake import ScriptedProvider
from swarm.tools.arithmetic import ArithmeticTool
from swarm.execution import execute


class AuditIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_durable_request_counts_and_structured_outputs(self):
        from swarm.audit import RepositoryAudit
        repo = SQLiteRepository(':memory:')
        self.addCleanup(repo.close)
        run = Run(id='r', objective='check arithmetic')
        repo.commit('r', [run], [EventDraft(type=EventType.RUN_CREATED, record_id='r', record_revision=1)])
        context = ExecutionContext(run_id='r', assignment_id='x', agent_id='a', task_id='t',
                                   objective='sum', run_tools=('arithmetic',), agent_tools=('arithmetic',))
        role = Role(id='e', name=RoleName.EXPLORER, allowed_tools=('arithmetic',))
        provider = ScriptedProvider([ModelResponse(tool_calls=(ToolCall(id='c', name='arithmetic',
            arguments_json='{"numbers":[1,2],"expected":3}'),)),
            ModelResponse(content='{"status":"SUCCEEDED","summary":"done"}')])
        await execute(context, role, provider, {'arithmetic': ArithmeticTool()}, audit=RepositoryAudit(repo, 'r'))
        self.assertEqual(repo.get('r', 'r').provider_requests, 2)
        self.assertEqual(repo.get('r', 'r').tool_calls, 1)
        view = repo.inspect('r')
        self.assertEqual(json.loads(view.events[-1].detail_json)['result']['summary'], 'done')
        self.assertEqual([e.sequence for e in view.events], list(range(1, len(view.events) + 1)))
        self.assertEqual(view.status, 'INCOMPLETE')

    async def test_durable_limit_prevents_new_execution_from_resetting_budget(self):
        from swarm.audit import RepositoryAudit
        repo = SQLiteRepository(':memory:')
        self.addCleanup(repo.close)
        run = Run(id='r', objective='work', provider_request_limit=1)
        repo.commit('r', [run], [EventDraft(type=EventType.RUN_CREATED, record_id='r', record_revision=1)])
        context = ExecutionContext(run_id='r', assignment_id='x', agent_id='a', task_id='t', objective='x')
        role = Role(id='e', name=RoleName.EXPLORER)
        audit = RepositoryAudit(repo, 'r')
        await execute(context, role, ScriptedProvider([ModelResponse(content='{"status":"SUCCEEDED","summary":"x"}')]), {}, audit=audit)
        provider = ScriptedProvider([ModelResponse(content='{"status":"SUCCEEDED","summary":"x"}')])
        with self.assertRaises(ExecutionError):
            await execute(context, role, provider, {}, audit=audit, budget=Budget())
        self.assertEqual(provider.requests, [])
