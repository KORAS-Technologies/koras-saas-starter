"""The provider boundary.

`AIProvider` is what the runtime calls; `GatewayProvider` is the one
implementation a product ships. It speaks the OpenAI-compatible protocol to
the AI gateway -- the LiteLLM proxy that holds the provider keys -- over
httpx, with the gateway's master key as its bearer. Nothing here knows which
vendor is behind a model name, and nothing in a product needs to: the gateway
is where that is decided, and the platform's routing policy is where it is
chosen per customer.

`FakeProvider` is for tests and for a product running without a gateway on
purpose. It answers from a script, so a test can say "the model proposes this
tool call" and prove what the runtime does about it.

Errors are translated at this boundary and nowhere else. A connection failure
is `provider_unavailable`, a timeout is `timeout`, a refusal of the master
key is `configuration_error`, and everything else the gateway answers with a
4xx or 5xx is `upstream_error`. The upstream body goes into `detail` for the
log and never into `message`.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

import httpx
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from .errors import AIError, ErrorCode
from .models import ModelRoute
from .types import (
    EmbedRequest,
    EmbedResult,
    GenerateEvent,
    GenerateRequest,
    GenerateResult,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)

DEFAULT_TIMEOUT_SECONDS = 60.0


class AIProvider(Protocol):
    """What the runtime asks of a provider. Small on purpose.

    Every operation takes the resolved route as well as the request: the
    request names an alias, the route names what the provider should answer
    as, and the provider is told both so the usage record can say which model
    actually answered.
    """

    @property
    def name(self) -> str: ...

    async def generate(self, request: GenerateRequest, *, route: ModelRoute) -> GenerateResult: ...

    def stream(
        self, request: GenerateRequest, *, route: ModelRoute
    ) -> AsyncIterator[GenerateEvent]: ...

    async def embed(self, request: EmbedRequest, *, route: ModelRoute) -> EmbedResult: ...


class ProviderRegistry:
    """Which `AIProvider` serves which provider name in a routing policy.

    The platform's provider names are free text: `openai`, `anthropic`, or a
    name a customer's private model was given. A product registers the
    gateway under the names the gateway can serve, and a route naming
    anything else is skipped by the runtime rather than guessed at.
    """

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider_name: str, provider: AIProvider) -> None:
        if not provider_name.strip():
            raise ValueError("a provider name must not be empty")
        self._providers[provider_name] = provider

    def get(self, provider_name: str) -> AIProvider | None:
        return self._providers.get(provider_name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


# ── The wire shape ────────────────────────────────────────────────────────────


def _wire_name(tool_id: str) -> str:
    """A tool id as a vendor's function name.

    A tool id is `files.list`: a namespace, a dot, a verb. OpenAI's function
    names match `^[a-zA-Z0-9_-]+$` and refuse the dot, and the first real
    conversation on dev ended in a 400 for exactly that. The dot becomes a
    hyphen, which the id grammar never contains, so `_tool_id` reverses it
    without ambiguity; an underscore would not, because an id may hold one.
    """
    return tool_id.replace(".", "-")


def _tool_id(wire_name: str) -> str:
    return wire_name.replace("-", ".")


def _message_to_wire(message: Message) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.images:
        # The OpenAI content-parts shape, which the gateway translates for
        # every vision provider it fronts.
        wire["content"] = [
            {"type": "text", "text": message.content},
            *({"type": "image_url", "image_url": {"url": url}} for url in message.images),
        ]
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": _wire_name(call.name),
                    "arguments": json.dumps(dict(call.arguments)),
                },
            }
            for call in message.tool_calls
        ]
    if message.role == "tool":
        wire["tool_call_id"] = message.tool_call_id
        if message.name:
            wire["name"] = _wire_name(message.name)
    return wire


def _tool_to_wire(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _wire_name(tool.name),
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _parse_arguments(raw: object) -> dict[str, Any]:
    """The arguments a model proposed, as a mapping.

    Providers send them as a JSON string; some send an object. Anything that
    is not an object is an empty mapping rather than an error here -- the
    tool's own schema is what validates the input, and a malformed proposal
    should fail as invalid input for that tool rather than as a broken reply.
    """
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return (
            {str(key): value for key, value in parsed.items()} if isinstance(parsed, dict) else {}
        )
    return {}


def _parse_tool_calls(raw: object) -> tuple[ToolCall, ...]:
    if not isinstance(raw, list):
        return ()
    calls: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        calls.append(
            ToolCall(
                id=str(entry.get("id") or f"call_{len(calls)}"),
                name=_tool_id(name),
                arguments=_parse_arguments(function.get("arguments")),
            )
        )
    return tuple(calls)


def _parse_usage(raw: object) -> Usage:
    if not isinstance(raw, dict):
        return Usage()

    def count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    prompt, completion = count("prompt_tokens"), count("completion_tokens")
    return Usage(
        input=prompt, output=completion, total=count("total_tokens") or prompt + completion
    )


_tracer = trace.get_tracer("koras_ai")


def _span(operation: str, alias: str, route: ModelRoute) -> Span:
    """One span per gateway call, named by the OpenTelemetry GenAI conventions.

    Started rather than made current: `stream` yields while the call is
    open, and a span attached to the context across a generator's suspension
    is the one OpenTelemetry cannot reliably detach. The trace context still
    reaches the gateway, through `_traced_headers`.
    """
    return _tracer.start_span(
        f"ai.{operation}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": operation,
            "gen_ai.system": route.provider,
            "gen_ai.request.model": route.model,
            "koras.ai.alias": alias,
        },
    )


def _traced_headers(span: Span) -> dict[str, str]:
    headers: dict[str, str] = {}
    inject(headers, context=trace.set_span_in_context(span))
    return headers


def _finish(
    span: Span,
    *,
    usage: Usage | None = None,
    model: str | None = None,
    error: AIError | None = None,
) -> None:
    if usage is not None:
        span.set_attribute("gen_ai.usage.input_tokens", usage.input)
        span.set_attribute("gen_ai.usage.output_tokens", usage.output)
    if model:
        span.set_attribute("gen_ai.response.model", model)
    if error is not None:
        span.set_attribute("error.type", error.code.value)
        span.set_status(Status(StatusCode.ERROR, error.code.value))
    span.end()


def _safe_error(status: int, body: str) -> AIError:
    detail = f"gateway answered {status}: {body[:500]}"
    if status == 401:
        return AIError(
            ErrorCode.CONFIGURATION_ERROR,
            "the AI gateway refused this product's credential",
            detail=detail,
        )
    if status == 403:
        # **Not the same answer as 401, and conflating them took an assistant
        # down.** A 401 is about the credential and fails identically on every
        # route, which is why `_RETRY_NEXT_ROUTE` excludes it. A 403 here is
        # about *this route*: the gateway holds a working key and the provider
        # account behind it is not entitled to that particular model. Those are
        # exactly the conditions a second route exists for.
        #
        # Found on 2026-09-22 against a deployed gateway, where every OpenAI
        # route answered 403 -- "Project ... does not have access to model
        # gpt-4o" -- and `claude-sonnet-4-6`, the next route in the catalogue,
        # answered 200. The product refused the whole turn and reported a
        # credential problem, so the remedy it pointed at was rotating a key
        # that was working.
        return AIError(
            ErrorCode.UPSTREAM_ERROR,
            "the model provider will not serve this model",
            detail=detail,
        )
    if status == 404:
        return AIError(
            ErrorCode.CONFIGURATION_ERROR,
            "the AI gateway does not serve the requested model",
            detail=detail,
        )
    if status >= 500 or status == 429:
        return AIError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "the model provider is not available right now",
            detail=detail,
        )
    return AIError(
        ErrorCode.UPSTREAM_ERROR, "the model provider refused the request", detail=detail
    )


class GatewayProvider:
    """The AI gateway, spoken to as an OpenAI-compatible API.

    `transport` is injectable so a test can answer the requests without a
    server; `client` is built once per provider and reused, which is what
    keeps a connection pool rather than opening one per message.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        name: str = "gateway",
    ) -> None:
        if not base_url.strip():
            raise AIError(
                ErrorCode.CONFIGURATION_ERROR,
                "AI is enabled but no gateway address is configured",
                detail="AI_GATEWAY_URL is empty",
            )
        if not api_key.strip():
            raise AIError(
                ErrorCode.CONFIGURATION_ERROR,
                "AI is enabled but the gateway credential is not configured",
                detail="LITELLM_MASTER_KEY is empty",
            )
        self._name = name
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout_seconds,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    @property
    def name(self) -> str:
        return self._name

    async def aclose(self) -> None:
        await self._client.aclose()

    def _body(self, request: GenerateRequest, route: ModelRoute, *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": route.model,
            "messages": [_message_to_wire(message) for message in request.messages],
            "stream": stream,
        }
        if request.tools:
            body["tools"] = [_tool_to_wire(tool) for tool in request.tools]
            body["tool_choice"] = "auto"
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output is not None:
            body["max_tokens"] = request.max_output
        if request.metadata:
            body["metadata"] = dict(request.metadata)
        return body

    async def _post(
        self, path: str, body: Mapping[str, Any], *, headers: Mapping[str, str]
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=dict(body), headers=dict(headers))
        except httpx.TimeoutException as error:
            raise AIError(
                ErrorCode.TIMEOUT,
                "the model did not answer in time",
                detail=f"{type(error).__name__} on {path}",
            ) from error
        except httpx.HTTPError as error:
            raise AIError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "the AI gateway could not be reached",
                detail=f"{type(error).__name__} on {path}",
            ) from error

        if response.status_code >= 400:
            raise _safe_error(response.status_code, response.text)
        try:
            parsed = response.json()
        except ValueError as error:
            raise AIError(
                ErrorCode.UPSTREAM_ERROR,
                "the model provider answered with something that is not JSON",
                detail=f"non-JSON body on {path}",
            ) from error
        if not isinstance(parsed, dict):
            raise AIError(
                ErrorCode.UPSTREAM_ERROR,
                "the model provider answered with an unexpected shape",
                detail=f"non-object body on {path}",
            )
        return parsed

    async def generate(self, request: GenerateRequest, *, route: ModelRoute) -> GenerateResult:
        started = time.monotonic()
        span = _span("chat", request.model, route)
        try:
            parsed = await self._post(
                "/v1/chat/completions",
                self._body(request, route, stream=False),
                headers=_traced_headers(span),
            )
        except AIError as error:
            _finish(span, error=error)
            raise
        latency = int((time.monotonic() - started) * 1000)

        choices = parsed.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else {}
        raw_message = first.get("message") if isinstance(first, dict) else {}
        if not isinstance(raw_message, dict):
            raw_message = {}
        content = raw_message.get("content")
        message = Message(
            role="assistant",
            content=content if isinstance(content, str) else "",
            tool_calls=_parse_tool_calls(raw_message.get("tool_calls")),
        )
        finish = first.get("finish_reason") if isinstance(first, dict) else None
        answered_as = parsed.get("model")
        result = GenerateResult(
            message=message,
            usage=_parse_usage(parsed.get("usage")),
            provider=route.provider,
            model=answered_as if isinstance(answered_as, str) and answered_as else route.model,
            latency_ms=latency,
            finish_reason=finish if isinstance(finish, str) else "stop",
        )
        _finish(span, usage=result.usage, model=result.model)
        return result

    async def stream(
        self, request: GenerateRequest, *, route: ModelRoute
    ) -> AsyncIterator[GenerateEvent]:
        """Server-sent events from the gateway, assembled into one result.

        Text arrives as deltas and is yielded as it comes. A tool call arrives
        in fragments -- the id and name first, the arguments in pieces -- and
        is yielded once, whole, when the stream ends, because a partial call
        is nothing the runtime can validate. The final event carries the
        assembled result, with the usage the gateway reports at the end.
        """
        started = time.monotonic()
        body = self._body(request, route, stream=True)
        body["stream_options"] = {"include_usage": True}
        text: list[str] = []
        pending: dict[int, dict[str, Any]] = {}
        usage = Usage()
        finish = "stop"
        span = _span("chat", request.model, route)
        try:
            async with self._client.stream(
                "POST", "/v1/chat/completions", json=body, headers=_traced_headers(span)
            ) as response:
                if response.status_code >= 400:
                    raise _safe_error(response.status_code, (await response.aread()).decode())
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage = _parse_usage(chunk["usage"])
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    if isinstance(choice.get("finish_reason"), str):
                        finish = choice["finish_reason"]
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        text.append(piece)
                        yield GenerateEvent(kind="delta", text=piece)
                    _merge_tool_fragments(pending, delta.get("tool_calls"))
        except httpx.TimeoutException as error:
            timeout = AIError(
                ErrorCode.TIMEOUT,
                "the model did not answer in time",
                detail=f"{type(error).__name__} while streaming",
            )
            _finish(span, error=timeout)
            raise timeout from error
        except httpx.HTTPError as error:
            unreachable = AIError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "the AI gateway could not be reached",
                detail=f"{type(error).__name__} while streaming",
            )
            _finish(span, error=unreachable)
            raise unreachable from error
        except AIError as error:
            _finish(span, error=error)
            raise
        except BaseException:
            span.end()
            raise

        calls = tuple(
            ToolCall(
                id=str(fragment.get("id") or f"call_{index}"),
                name=_tool_id(str(fragment.get("name") or "")),
                arguments=_parse_arguments("".join(fragment.get("arguments", []))),
            )
            for index, fragment in sorted(pending.items())
            if fragment.get("name")
        )
        for call in calls:
            yield GenerateEvent(kind="tool_call", tool_call=call)

        result = GenerateResult(
            message=Message(role="assistant", content="".join(text), tool_calls=calls),
            usage=usage,
            provider=route.provider,
            model=route.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            finish_reason=finish,
        )
        _finish(span, usage=usage, model=route.model)
        yield GenerateEvent(kind="done", result=result)

    async def embed(self, request: EmbedRequest, *, route: ModelRoute) -> EmbedResult:
        span = _span("embeddings", request.model, route)
        try:
            parsed = await self._post(
                "/v1/embeddings",
                {"model": route.model, "input": list(request.inputs)},
                headers=_traced_headers(span),
            )
        except AIError as error:
            _finish(span, error=error)
            raise
        data = parsed.get("data")
        vectors: list[tuple[float, ...]] = []
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                embedding = entry.get("embedding")
                if isinstance(embedding, list):
                    vectors.append(tuple(float(value) for value in embedding))
        result = EmbedResult(
            vectors=tuple(vectors),
            usage=_parse_usage(parsed.get("usage")),
            provider=route.provider,
            model=route.model,
        )
        _finish(span, usage=result.usage, model=result.model)
        return result


def _merge_tool_fragments(pending: dict[int, dict[str, Any]], raw: object) -> None:
    if not isinstance(raw, list):
        return
    for fragment in raw:
        if not isinstance(fragment, dict):
            continue
        index = fragment.get("index")
        if not isinstance(index, int):
            index = len(pending)
        slot = pending.setdefault(index, {"arguments": []})
        if isinstance(fragment.get("id"), str):
            slot["id"] = fragment["id"]
        function = fragment.get("function")
        if isinstance(function, dict):
            if isinstance(function.get("name"), str):
                slot["name"] = function["name"]
            if isinstance(function.get("arguments"), str):
                slot["arguments"].append(function["arguments"])


# ── A provider for tests ─────────────────────────────────────────────────────

Scripted = Message | Callable[[GenerateRequest], Message]


class FakeProvider:
    """Answers from a script, in order, and records what it was asked.

    Each entry is the assistant message to return, or a function of the
    request that produces one. Running past the end of the script answers
    with an empty message, so a runtime loop that asks once too often is
    visible in the test rather than hidden by a repeat.
    """

    def __init__(
        self,
        script: Iterable[Scripted] = (),
        *,
        name: str = "fake",
        usage: Usage | None = None,
        vectors: Sequence[Sequence[float]] = ((0.1, 0.2, 0.3),),
    ) -> None:
        self._name = name
        self._script = list(script)
        self._usage = usage or Usage(input=10, output=5, total=15)
        self._vectors = tuple(tuple(float(v) for v in vector) for vector in vectors)
        self.requests: list[GenerateRequest] = []
        self.embed_requests: list[EmbedRequest] = []

    @property
    def name(self) -> str:
        return self._name

    def _next(self, request: GenerateRequest) -> Message:
        self.requests.append(request)
        if not self._script:
            return Message(role="assistant", content="")
        entry = self._script.pop(0)
        return entry(request) if callable(entry) else entry

    async def generate(self, request: GenerateRequest, *, route: ModelRoute) -> GenerateResult:
        return GenerateResult(
            message=self._next(request),
            usage=self._usage,
            provider=route.provider,
            model=route.model,
            latency_ms=1,
        )

    async def stream(
        self, request: GenerateRequest, *, route: ModelRoute
    ) -> AsyncIterator[GenerateEvent]:
        result = await self.generate(request, route=route)
        if result.message.content:
            yield GenerateEvent(kind="delta", text=result.message.content)
        for call in result.message.tool_calls:
            yield GenerateEvent(kind="tool_call", tool_call=call)
        yield GenerateEvent(kind="done", result=result)

    async def embed(self, request: EmbedRequest, *, route: ModelRoute) -> EmbedResult:
        self.embed_requests.append(request)
        vectors = tuple(
            self._vectors[index % len(self._vectors)] for index in range(len(request.inputs))
        )
        return EmbedResult(
            vectors=vectors, usage=self._usage, provider=route.provider, model=route.model
        )


class FailingProvider:
    """Raises the given error on every call. For fallback tests."""

    def __init__(self, error: AIError, *, name: str = "failing") -> None:
        self._error = error
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerateRequest, *, route: ModelRoute) -> GenerateResult:
        self.calls += 1
        raise self._error

    async def stream(
        self, request: GenerateRequest, *, route: ModelRoute
    ) -> AsyncIterator[GenerateEvent]:
        self.calls += 1
        raise self._error
        yield GenerateEvent(kind="done")  # pragma: no cover - makes this an async generator

    async def embed(self, request: EmbedRequest, *, route: ModelRoute) -> EmbedResult:
        self.calls += 1
        raise self._error
