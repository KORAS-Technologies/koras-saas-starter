"""The gateway adapter, against a fake transport.

What matters here is the translation: the OpenAI-compatible wire shape into
messages and tool calls, and every failure into a code with a safe message.
"""

from __future__ import annotations

import json

import httpx
import pytest
from koras_ai import (
    AIError,
    EmbedRequest,
    ErrorCode,
    GatewayProvider,
    GenerateRequest,
    Message,
    ModelRoute,
    ToolSpec,
)

ROUTE = ModelRoute("openai", "gpt-4o")


def provider(handler: httpx.MockTransport) -> GatewayProvider:
    return GatewayProvider(base_url="http://gateway.test", api_key="sk-test", transport=handler)


def request() -> GenerateRequest:
    return GenerateRequest(
        model="koras-balanced",
        messages=(Message("system", "be brief"), Message("user", "list my files")),
        tools=(ToolSpec("files.list", "List files", {"type": "object", "properties": {}}),),
    )


def test_the_gateway_needs_an_address_and_a_credential() -> None:
    with pytest.raises(AIError) as refused:
        GatewayProvider(base_url="", api_key="x")
    assert refused.value.code is ErrorCode.CONFIGURATION_ERROR
    with pytest.raises(AIError):
        GatewayProvider(base_url="http://g", api_key=" ")


async def test_a_completion_is_translated_with_its_usage() -> None:
    seen: dict[str, object] = {}

    def handle(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-2024",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Two files."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            },
        )

    result = await provider(httpx.MockTransport(handle)).generate(request(), route=ROUTE)
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o"  # the route's model, never the alias
    # The dot is not a legal function name at the vendor; the wire form is
    # the hyphen and the runtime never sees it.
    assert body["tools"][0]["function"]["name"] == "files-list"
    assert result.message.content == "Two files."
    assert (result.usage.input, result.usage.output, result.usage.total) == (12, 3, 15)
    assert result.model == "gpt-4o-2024" and result.provider == "openai"


async def test_tool_calls_are_parsed_from_json_strings_and_objects() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "files-list", "arguments": '{"limit": 2}'},
                                },
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {"name": "files-list", "arguments": {"limit": 3}},
                                },
                                {
                                    "id": "c3",
                                    "type": "function",
                                    "function": {"name": "files.list", "arguments": "not json"},
                                },
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {},
            },
        )

    result = await provider(httpx.MockTransport(handle)).generate(request(), route=ROUTE)
    calls = result.message.tool_calls
    assert [c.arguments for c in calls] == [{"limit": 2}, {"limit": 3}, {}]
    assert result.message.content == ""
    assert result.finish_reason == "tool_calls"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.CONFIGURATION_ERROR),
        (404, ErrorCode.CONFIGURATION_ERROR),
        (429, ErrorCode.PROVIDER_UNAVAILABLE),
        (500, ErrorCode.PROVIDER_UNAVAILABLE),
        (400, ErrorCode.UPSTREAM_ERROR),
    ],
)
async def test_a_refusal_becomes_a_code_and_the_body_stays_out_of_the_message(
    status: int, code: ErrorCode
) -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="secret-upstream-detail sk-live-123")

    with pytest.raises(AIError) as refused:
        await provider(httpx.MockTransport(handle)).generate(request(), route=ROUTE)
    assert refused.value.code is code
    assert "sk-live" not in refused.value.message
    assert refused.value.detail is not None and "sk-live" in refused.value.detail


async def test_a_timeout_and_a_connection_failure_are_named() -> None:
    def timeout(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(AIError) as slow:
        await provider(httpx.MockTransport(timeout)).generate(request(), route=ROUTE)
    assert slow.value.code is ErrorCode.TIMEOUT
    with pytest.raises(AIError) as gone:
        await provider(httpx.MockTransport(down)).generate(request(), route=ROUTE)
    assert gone.value.code is ErrorCode.PROVIDER_UNAVAILABLE


async def test_a_stream_yields_text_then_whole_tool_calls_then_the_result() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "files-list", "arguments": '{"li'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'mit": 1}'}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    def handle(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["stream"] is True
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = [
        event
        async for event in provider(httpx.MockTransport(handle)).stream(request(), route=ROUTE)
    ]
    assert [e.kind for e in events] == ["delta", "delta", "tool_call", "done"]
    assert events[2].tool_call is not None and events[2].tool_call.arguments == {"limit": 1}
    done = events[3].result
    assert done is not None
    assert done.message.content == "Hello"
    assert done.usage.total == 7


async def test_embeddings_are_read_from_the_data_array() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/embeddings"
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}],
                "usage": {"prompt_tokens": 4},
            },
        )

    result = await provider(httpx.MockTransport(handle)).embed(
        EmbedRequest(model="koras-embedding", inputs=("a", "b")),
        route=ModelRoute("openai", "embed"),
    )
    assert result.vectors == ((0.1, 0.2), (0.3, 0.4))
    assert result.usage.input == 4
