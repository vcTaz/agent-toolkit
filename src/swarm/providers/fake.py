"""Deterministic scripted responses, errors, tools, and delays for local scenarios."""
import asyncio
from dataclasses import dataclass
from ..contracts import ModelRequest, ModelResponse, ProviderError, ProviderErrorCode


@dataclass(frozen=True)
class Delay:
    seconds: float
    response: ModelResponse


class ScriptedProvider:
    def __init__(self, steps):
        self._steps = iter(steps)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        try:
            step = next(self._steps)
        except StopIteration as exc:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, 'script exhausted') from exc
        if isinstance(step, Exception):
            raise step
        if isinstance(step, Delay):
            await asyncio.sleep(step.seconds)
            return step.response
        return step(request) if callable(step) else step
