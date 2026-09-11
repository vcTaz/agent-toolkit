"""Strict versioned JSON serialization; no pickle or dynamically imported types."""
import json
import math
import types
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import get_args, get_origin, get_type_hints, Union
from . import domain
from .domain import SCHEMA_VERSION, DomainError, Record


def encode(value):
    if is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [encode(v) for v in value]
    return value


def decode(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (types.UnionType, Union):
        for choice in args:
            try:
                return decode(choice, value)
            except (ValueError, TypeError):
                pass
        raise DomainError('value does not match union')
    if origin is tuple:
        if not isinstance(value, list):
            raise DomainError('expected array')
        return tuple(decode(args[0], v) for v in value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if is_dataclass(annotation):
        if not isinstance(value, dict):
            raise DomainError('expected object')
        hints = get_type_hints(annotation)
        if set(value) - set(hints):
            raise DomainError('unknown fields')
        return annotation(**{k: decode(hints[k], v) for k, v in value.items()})
    if annotation is float and type(value) in (float, int) and math.isfinite(value):
        return float(value)
    if type(value) is not annotation:
        raise DomainError(f'expected {annotation}')
    return value


def dumps(record: Record) -> str:
    return json.dumps({'type': type(record).__name__, 'data': encode(record)},
                      separators=(',', ':'), allow_nan=False)


def loads(payload: str) -> Record:
    try:
        wrapper = json.loads(payload)
        if set(wrapper) != {'type', 'data'}:
            raise DomainError('invalid record envelope')
        registry = {name: cls for name, cls in vars(domain).items()
                    if isinstance(cls, type) and issubclass(cls, Record)}
        if wrapper['type'] not in registry or wrapper['data'].get('schema_version') != SCHEMA_VERSION:
            raise DomainError('unknown record type or schema version')
        return decode(registry[wrapper['type']], wrapper['data'])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DomainError(f'invalid serialized record: {exc}') from exc
