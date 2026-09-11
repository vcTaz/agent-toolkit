"""Small explicit schema subset for trusted tool definitions; unsupported keywords fail closed."""
import math


def validate_schema(value, schema):
    supported = {'type', 'properties', 'required', 'additionalProperties', 'items',
                 'maxItems', 'maxLength', 'minimum', 'maximum', 'enum'}
    if not isinstance(schema, dict) or set(schema) - supported:
        raise ValueError('unsupported schema keyword')
    kind = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int,
             'number': (float, int), 'boolean': bool, 'null': type(None)}
    if kind not in types or (type(value) not in types[kind] if isinstance(types[kind], tuple)
                             else type(value) is not types[kind]):
        raise ValueError('schema type mismatch')
    if kind in ('number', 'integer'):
        if (type(value) is float and not math.isfinite(value)) or value < schema.get('minimum', -float('inf')) or value > schema.get('maximum', float('inf')):
            raise ValueError('numeric bound exceeded')
    if kind == 'object':
        properties = schema.get('properties', {})
        if set(schema.get('required', ())) - set(value):
            raise ValueError('missing required property')
        if schema.get('additionalProperties', False) is not True and set(value) - set(properties):
            raise ValueError('unknown property')
        for key in value.keys() & properties.keys():
            validate_schema(value[key], properties[key])
    if kind == 'array':
        if len(value) > schema.get('maxItems', 64):
            raise ValueError('too many items')
        for item in value:
            validate_schema(item, schema['items'])
    if kind == 'string' and len(value) > schema.get('maxLength', 4000):
        raise ValueError('string too long')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('unknown enum member')
