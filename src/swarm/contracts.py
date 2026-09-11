"""Provider-neutral immutable request/response contracts and host budgets."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProviderErrorCode(StrEnum):
    TIMEOUT = 'TIMEOUT'
    TRANSIENT = 'TRANSIENT'
    AUTHENTICATION = 'AUTHENTICATION'
    UNSUPPORTED = 'UNSUPPORTED'
    INVALID_RESPONSE = 'INVALID_RESPONSE'


class ProviderError(Exception):
    def __init__(self, code: ProviderErrorCode, message: str):
        super().__init__(message)
        self.code = code


class ExecutionError(RuntimeError):
    """The assignment could not produce a usable proposal within its limits."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, kw_only=True)
class ToolSpec:
    name: str
    description: str
    input_schema_json: str
    output_schema_json: str


@dataclass(frozen=True, kw_only=True)
class ModelRequest:
    request_id: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...]
    output_contract_json: str
    remaining_seconds: float
    output_limit: int = 16000


@dataclass(frozen=True, kw_only=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, kw_only=True)
class ModelResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str = 'stop'
    provider_request_id: str | None = None


class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...


@dataclass(frozen=True, kw_only=True)
class ExecutionContext:
    run_id: str
    assignment_id: str
    agent_id: str
    task_id: str
    objective: str
    run_tools: tuple[str, ...] = ()
    agent_tools: tuple[str, ...] = ()
    relevant_context: str = ''


@dataclass(frozen=True, kw_only=True)
class ToolResult:
    success: bool
    value_json: str = '{}'
    error: str | None = None
    id: str = ''
    assignment_id: str = ''
    tool_name: str = ''
    arguments_json: str = ''
    """Host-canonicalized arguments actually executed, never the model's restatement."""


class Tool(Protocol):
    spec: ToolSpec
    async def execute(self, arguments: dict, execution_context: ExecutionContext) -> ToolResult: ...


@dataclass
class Budget:
    """Share one host-owned instance per run; reservations do not await."""
    request_limit: int = 80
    tool_limit: int = 120
    requests: int = 0
    tool_calls: int = 0

    def reserve_request(self):
        if self.requests >= self.request_limit:
            raise ExecutionError('provider request budget exhausted')
        self.requests += 1

    def reserve_tool(self):
        if self.tool_calls >= self.tool_limit:
            raise ExecutionError('tool call budget exhausted')
        self.tool_calls += 1

    def release_request(self):
        """Undo a reservation the host refused; a dispatch that never happened costs nothing."""
        self.requests -= 1

    def release_tool(self):
        self.tool_calls -= 1
