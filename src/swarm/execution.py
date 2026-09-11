"""Bounded execution seam. Returns proposals; never schedules or mutates tasks/findings."""
import asyncio
import json
from dataclasses import replace
from time import monotonic
from uuid import uuid4
from .contracts import (Budget, ChatMessage, ExecutionError, ModelRequest, ModelResponse,
                        ProviderError, ToolResult, ToolCall)
from .events import EventDraft, EventType
from .output import OUTPUT_CONTRACT, parse_output, strict_json
from .schema import validate_schema
from .serialization import encode


async def execute(context, role, provider, tools, *, audit, budget=None,
                  timeout=60.0, repair_limit=1):
    """Host supplies trusted context/role, shared run budget, and durable audit sink.

    Audit is synchronous so an event is durable before dispatch; a storage exception
    propagates and stops work. Providers/tools must cooperate with async cancellation.
    """
    if timeout <= 0 or repair_limit < 0:
        raise ValueError('invalid execution limits')
    budget = budget if budget is not None else Budget()
    allowed = set(context.run_tools) & set(context.agent_tools) & set(role.allowed_tools)
    available = {name: tool for name, tool in tools.items() if name in allowed}
    if any(name != tool.spec.name for name, tool in available.items()):
        raise ValueError('tool registry/spec mismatch')
    def emit(kind, **detail):
        event = EventDraft(type=kind, assignment_id=context.assignment_id,
                           task_id=context.task_id, agent_id=context.agent_id, role_id=role.id,
                           correlation_id=context.assignment_id,
                           detail_json=json.dumps(detail, allow_nan=False))
        audit(event)
    messages = (ChatMessage('system', role.instructions), ChatMessage('user', json.dumps({
        'objective': context.objective, 'context': context.relevant_context,
        'allowed_output_fields': role.output_fields})))
    results = []
    seen_calls = set()
    repairs = 0
    deadline = monotonic() + timeout
    emit(EventType.EXECUTION_STARTED)
    try:
        async with asyncio.timeout(timeout):
            while True:
                if sum(len(m.content) for m in messages) > 24000:
                    raise ExecutionError('execution context limit exceeded')
                budget.reserve_request()
                request = ModelRequest(request_id=str(uuid4()), messages=messages,
                    tools=tuple(tool.spec for tool in available.values()), output_contract_json=OUTPUT_CONTRACT,
                    remaining_seconds=max(0, deadline - monotonic()))
                try:
                    # The host may still refuse; the local mirror must not keep the reservation.
                    emit(EventType.PROVIDER_REQUESTED, request_id=request.request_id, requests=budget.requests)
                except BaseException:
                    budget.release_request()
                    raise
                try:
                    response = await provider.generate(request)
                except asyncio.CancelledError:
                    emit(EventType.PROVIDER_FAILED, request_id=request.request_id, code='CANCELLED_OR_TIMEOUT')
                    raise
                except ProviderError as exc:
                    emit(EventType.PROVIDER_FAILED, request_id=request.request_id, code=str(exc.code))
                    raise ExecutionError(f'provider error: {exc.code}') from exc
                except Exception as exc:
                    emit(EventType.PROVIDER_FAILED, request_id=request.request_id, code='ADAPTER_ERROR')
                    raise ExecutionError('provider adapter failed') from exc
                if (not isinstance(response, ModelResponse)
                        or type(response.tool_calls) is not tuple
                        or any(not isinstance(c, ToolCall) or not all(isinstance(v, str)
                               for v in (c.id, c.name, c.arguments_json)) for c in response.tool_calls)
                        or any(v is not None and (type(v) is not int or v < 0)
                               for v in (response.input_tokens, response.output_tokens))):
                    emit(EventType.PROVIDER_FAILED, request_id=request.request_id, code='INVALID_RESPONSE')
                    raise ExecutionError('provider returned wrong response type')
                emit(EventType.PROVIDER_COMPLETED, request_id=request.request_id,
                     provider_request_id=response.provider_request_id,
                     input_tokens=response.input_tokens, output_tokens=response.output_tokens)
                if response.tool_calls:
                    if response.content is not None or len(response.tool_calls) > 8:
                        raise ExecutionError('ambiguous or oversized tool response')
                    # Preflight the entire batch before executing any call.
                    batch = []
                    for call in response.tool_calls:
                        if not call.id or call.id in seen_calls or call.name not in available:
                            raise ExecutionError('duplicate or forbidden tool call')
                        seen_calls.add(call.id)
                        if len(call.arguments_json) > 8000:
                            raise ExecutionError('tool arguments too large')
                        arguments = strict_json(call.arguments_json)
                        tool = available[call.name]
                        validate_schema(arguments, strict_json(tool.spec.input_schema_json))
                        batch.append((call, tool, arguments))
                    messages += (ChatMessage('assistant', json.dumps({'tool_calls': [encode(c) for c in response.tool_calls]})),)
                    for call, tool, arguments in batch:
                        budget.reserve_tool()
                        try:
                            emit(EventType.TOOL_STARTED, call_id=call.id, name=call.name, arguments=arguments)
                        except BaseException:
                            budget.release_tool()
                            raise
                        try:
                            result = await tool.execute(arguments, context)
                            if (not isinstance(result, ToolResult) or type(result.success) is not bool
                                    or not isinstance(result.value_json, str) or len(result.value_json) > 8000
                                    or (result.error is not None and (not isinstance(result.error, str) or len(result.error) > 1000))):
                                raise ExecutionError('invalid tool result')
                            value = strict_json(result.value_json)
                            if result.success:
                                validate_schema(value, strict_json(tool.spec.output_schema_json))
                        except asyncio.CancelledError:
                            emit(EventType.TOOL_FAILED, call_id=call.id, reason='CANCELLED_OR_TIMEOUT')
                            raise
                        except Exception as exc:
                            emit(EventType.TOOL_FAILED, call_id=call.id, reason=type(exc).__name__)
                            raise ExecutionError('tool failed') from exc
                        # Record what was actually computed: a verifier cannot judge a claim from an outcome alone.
                        result = replace(result, id=str(uuid4()), assignment_id=context.assignment_id,
                                         tool_name=call.name,
                                         arguments_json=json.dumps(arguments, sort_keys=True, separators=(',', ':')))
                        results.append(result)
                        emit(EventType.TOOL_COMPLETED if result.success else EventType.TOOL_FAILED,
                             call_id=call.id, result=encode(result))
                        messages += (ChatMessage('tool', json.dumps({'call_id': call.id, 'id': result.id,
                            'success': result.success, 'value': value, 'error': result.error})),)
                    continue
                try:
                    output = parse_output(response.content, role, tuple(results))
                except (ValueError, TypeError, RecursionError) as exc:
                    emit(EventType.OUTPUT_REJECTED, reason=str(exc)[:300])
                    if repairs >= repair_limit:
                        raise ExecutionError('output repair limit exhausted') from exc
                    repairs += 1
                    # Bounded repair instruction; do not reinject oversized/malicious output.
                    messages += (ChatMessage('user', 'Return a corrected structured result. Error: ' + str(exc)[:300]),)
                    continue
                output = replace(output, assignment_id=context.assignment_id, tool_results=tuple(results))
                emit(EventType.EXECUTION_COMPLETED, result=encode(output))
                return output
    except asyncio.CancelledError:
        emit(EventType.EXECUTION_CANCELLED)
        raise
    except TimeoutError as exc:
        emit(EventType.EXECUTION_FAILED, reason='timeout')
        raise ExecutionError('execution timeout') from exc
    except (ExecutionError, ValueError, TypeError) as exc:
        emit(EventType.EXECUTION_FAILED, reason=str(exc)[:300])
        if isinstance(exc, ExecutionError):
            raise
        raise ExecutionError(str(exc)) from exc
