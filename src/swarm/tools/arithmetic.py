"""Integer sum verification without eval, external I/O, or implicit truth promotion."""
import json
from ..contracts import ToolSpec, ToolResult
from ..schema import validate_schema

_INPUT = {'type': 'object', 'properties': {
    'numbers': {'type': 'array', 'items': {'type': 'integer', 'minimum': -10**12, 'maximum': 10**12}, 'maxItems': 64},
    'expected': {'type': 'integer', 'minimum': -10**15, 'maximum': 10**15}},
    'required': ['numbers', 'expected'], 'additionalProperties': False}
_OUTPUT = {'type': 'object', 'properties': {'actual': {'type': 'integer'}, 'matches': {'type': 'boolean'}},
           'required': ['actual', 'matches'], 'additionalProperties': False}


class ArithmeticTool:
    spec = ToolSpec(name='arithmetic', description='Check an integer sum against an expected value',
                    input_schema_json=json.dumps(_INPUT), output_schema_json=json.dumps(_OUTPUT))

    async def execute(self, arguments, execution_context) -> ToolResult:
        validate_schema(arguments, _INPUT)
        actual = sum(arguments['numbers'])
        return ToolResult(success=True, value_json=json.dumps(
            {'actual': actual, 'matches': actual == arguments['expected']}))
