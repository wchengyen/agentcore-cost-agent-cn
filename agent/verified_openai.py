"""OpenAIModel variant that records and enforces the provider-returned model ID."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import openai
from strands.models.openai import OpenAIModel


class _VerifiedStream:
    def __init__(self, stream: Any, owner: "VerifiedOpenAIModel") -> None:
        self._iterator = stream.__aiter__()
        self._owner = owner
        self._saw_model = False

    def __aiter__(self) -> "_VerifiedStream":
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._iterator.__anext__()
        except StopAsyncIteration:
            if not self._saw_model:
                raise RuntimeError("LLM response did not include a model field")
            raise
        returned = getattr(chunk, "model", None)
        if returned:
            self._saw_model = True
            self._owner.verify_returned_model(str(returned))
        return chunk


class _CompletionsProxy:
    def __init__(self, completions: Any, owner: "VerifiedOpenAIModel") -> None:
        self._completions = completions
        self._owner = owner

    async def create(self, **kwargs: Any) -> Any:
        response = await self._completions.create(**kwargs)
        if kwargs.get("stream", False):
            return _VerifiedStream(response, self._owner)
        returned = getattr(response, "model", None)
        if not returned:
            raise RuntimeError("LLM response did not include a model field")
        self._owner.verify_returned_model(str(returned))
        return response


class _ChatProxy:
    def __init__(self, chat: Any, owner: "VerifiedOpenAIModel") -> None:
        self.completions = _CompletionsProxy(chat.completions, owner)


class _ClientProxy:
    def __init__(self, client: Any, owner: "VerifiedOpenAIModel") -> None:
        self.chat = _ChatProxy(client.chat, owner)


class VerifiedOpenAIModel(OpenAIModel):
    """Log the response model field and reject silent provider fallback."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.returned_models: list[str] = []

    @property
    def requested_model(self) -> str:
        return str(self.config["model_id"])

    def verify_returned_model(self, returned: str) -> None:
        if returned not in self.returned_models:
            self.returned_models.append(returned)
            matched = returned == self.requested_model
            print(json.dumps({
                "event": "llm_response_model",
                "requested_model": self.requested_model,
                "returned_model": returned,
                "model_match": matched,
            }, separators=(",", ":")))
            if not matched:
                raise RuntimeError(
                    f"LLM model mismatch: requested {self.requested_model}, provider returned {returned}"
                )

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator[Any]:
        async with openai.AsyncOpenAI(**self._resolve_client_args()) as client:
            yield _ClientProxy(client, self)
