"""Runtime checks for immutable dataclass values, including nested containers."""
import math
import types
from dataclasses import fields, is_dataclass
from typing import get_args, get_origin, get_type_hints


def check_value(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        return any(check_value(t, value) for t in args)
    if origin is tuple:
        return type(value) is tuple and all(check_value(args[0], v) for v in value)
    if annotation is float:
        return type(value) in (float, int) and (type(value) is int or math.isfinite(value))
    if type(value) is not annotation:
        return False
    if is_dataclass(value):
        return all(check_value(t, getattr(value, name)) for name, t in get_type_hints(type(value)).items())
    return True


def check_record(record):
    from .domain import DomainError
    hints = get_type_hints(type(record))
    for field in fields(record):
        if not check_value(hints[field.name], getattr(record, field.name)):
            raise DomainError(f'invalid type or mutable value: {field.name}')
    for name in ('id', 'run_id', 'objective', 'claim', 'task_id', 'assignment_id', 'agent_id', 'role_id'):
        if hasattr(record, name):
            value = getattr(record, name)
            if value is not None and not value.strip():
                raise DomainError(f'empty {name}')
    confidence = getattr(record, 'confidence', None)
    if confidence is not None and not 0 <= confidence <= 1:
        raise DomainError('confidence out of range')
    for name in ('provider_requests', 'tool_calls', 'cycle'):
        if getattr(record, name, 0) < 0:
            raise DomainError(f'negative {name}')
    for name in ('version', 'attempt', 'target_revision', 'role_version'):
        if getattr(record, name, 1) < 1:
            raise DomainError(f'invalid {name}')
    for name in ('created_at', 'updated_at', 'started_at', 'ended_at', 'deadline_at', 'resolved_at'):
        value = getattr(record, name, None)
        if value is not None:
            from datetime import datetime, timedelta
            try:
                if datetime.fromisoformat(value).utcoffset() != timedelta(0):
                    raise ValueError('not UTC')
            except ValueError as exc:
                raise DomainError(f'invalid UTC timestamp: {name}') from exc

    for name in ('concurrency_limit', 'task_limit', 'assignment_attempt_limit', 'execution_timeout'):
        value = getattr(record, name, 1)
        if value <= 0 or (isinstance(value, float) and not math.isfinite(value)):
            raise DomainError(f'invalid {name}')
