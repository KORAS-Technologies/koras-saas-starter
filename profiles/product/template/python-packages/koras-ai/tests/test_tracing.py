"""A span per gateway call, and the trace context on the wire.

The SDK is a test dependency here and a service dependency in the API; the
package itself depends on the API only, so without an SDK every span below
is a no-op and the gateway still works.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from koras_ai import AIError, GenerateRequest, Message, ModelRoute
from koras_ai import providers as providers_module
from koras_ai.providers import GatewayProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

ROUTE = ModelRoute(provider="openai", model="gpt-4o-mini")


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """A provider of this test's own, handed to the module's tracer.

    Not the global one: that can be set once per process, and the API's own
    startup sets it first when the suites run together.
    """
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    monkeypatch.setattr(providers_module, "_tracer", provider.get_tracer("koras_ai"))
    return memory


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> GatewayProvider:
    return GatewayProvider(
        base_url="http://gateway.invalid",
        api_key="k",
        transport=httpx.MockTransport(handler),
    )


def _request() -> GenerateRequest:
    return GenerateRequest(model="koras-fast", messages=(Message("user", "hi"),))


@pytest.mark.asyncio
async def test_a_completion_leaves_a_span_with_the_route_and_the_usage(
    exporter: InMemorySpanExporter,
) -> None:
    seen: dict[str, str] = {}

    def handle(req: httpx.Request) -> httpx.Response:
        seen.update({k: v for k, v in req.headers.items() if k.startswith("traceparent")})
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini-2024",
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    await _provider(handle).generate(_request(), route=ROUTE)

    (span,) = exporter.get_finished_spans()
    assert span.name == "ai.chat"
    assert span.attributes is not None
    assert span.attributes["gen_ai.system"] == "openai"
    assert span.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert span.attributes["koras.ai.alias"] == "koras-fast"
    assert span.attributes["gen_ai.response.model"] == "gpt-4o-mini-2024"
    assert span.attributes["gen_ai.usage.input_tokens"] == 3
    assert span.attributes["gen_ai.usage.output_tokens"] == 2
    assert span.status.status_code == StatusCode.UNSET
    # The gateway received the trace context, so its own spans can join.
    assert "traceparent" in seen


@pytest.mark.asyncio
async def test_a_refusal_marks_the_span_as_an_error_with_the_code(
    exporter: InMemorySpanExporter,
) -> None:

    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    with pytest.raises(AIError) as raised:
        await _provider(handle).generate(_request(), route=ROUTE)

    (span,) = exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == raised.value.code.value


@pytest.mark.asyncio
async def test_a_stream_ends_its_span_when_the_stream_ends(exporter: InMemorySpanExporter) -> None:
    chunks = [
        {"choices": [{"delta": {"content": "Hi"}}]},
        {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = [e async for e in _provider(handle).stream(_request(), route=ROUTE)]
    assert events[-1].kind == "done"

    (span,) = exporter.get_finished_spans()
    assert span.name == "ai.chat"
    assert span.attributes is not None
    assert span.attributes["gen_ai.usage.output_tokens"] == 1


@pytest.mark.asyncio
async def test_an_embedding_call_has_its_own_span(exporter: InMemorySpanExporter) -> None:

    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 2}},
        )

    from koras_ai import EmbedRequest

    await _provider(handle).embed(
        EmbedRequest(model="koras-embedding", inputs=("a",)),
        route=ModelRoute(provider="openai", model="text-embedding-3-small"),
    )
    (span,) = exporter.get_finished_spans()
    assert span.name == "ai.embeddings"
    assert span.attributes is not None
    assert span.attributes["koras.ai.alias"] == "koras-embedding"
