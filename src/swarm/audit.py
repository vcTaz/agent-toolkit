"""Durable execution event sink with atomic run-level accounting."""
from dataclasses import replace
from .contracts import ExecutionError
from .domain import Run, now
from .events import EventType


class RepositoryAudit:
    def __init__(self, repository, run_id: str):
        self.repository = repository
        self.run_id = run_id

    def __call__(self, event):
        records = []
        if event.type in (EventType.PROVIDER_REQUESTED, EventType.TOOL_STARTED):
            run = self.repository.get(self.run_id, self.run_id)
            if not isinstance(run, Run):
                raise ExecutionError('missing run for accounting')
            if event.type == EventType.PROVIDER_REQUESTED:
                if run.provider_requests >= run.provider_request_limit:
                    raise ExecutionError('durable provider request budget exhausted')
                run = replace(run, provider_requests=run.provider_requests + 1,
                              revision=run.revision + 1, updated_at=now())
            else:
                if run.tool_calls >= run.tool_call_limit:
                    raise ExecutionError('durable tool budget exhausted')
                run = replace(run, tool_calls=run.tool_calls + 1,
                              revision=run.revision + 1, updated_at=now())
            records.append(run)
            event = replace(event, record_id=run.id, record_revision=run.revision)
        self.repository.commit(self.run_id, records, [event])
