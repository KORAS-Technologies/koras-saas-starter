"""Reading what has no text layer: pages as images, a vision call per page, metered.

The text layer always wins and costs nothing. Only a file that gave none --
an image, a scanned PDF -- is rendered and read, only up to the page ceiling,
and every call is recorded under the tenant the way a turn's calls are.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_ai import (  # noqa: E402
    AIConfiguration,
    AIError,
    ErrorCode,
    FailingProvider,
    FakeProvider,
    Limits,
    Message,
    ProviderRegistry,
    StaticRouting,
    UsageEvent,
)
from koras_api.ai import registries  # noqa: E402
from koras_api.ai.prompts import OCR_INSTRUCTIONS  # noqa: E402
from koras_api.core import knowledge  # noqa: E402
from koras_api.core.ai import OCR_AGENT, page_reader  # noqa: E402
from test_ai_knowledge import _pdf_with  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_an_image_is_its_own_single_page_and_a_pdf_is_rendered() -> None:
    assert knowledge.page_images(PNG, content_type="image/png") == [(PNG, "image/png")]
    assert knowledge.page_images(PNG, content_type="image/gif") == []
    assert knowledge.page_images(b"text", content_type="text/plain") == []

    (page,) = knowledge.page_images(_pdf_with("Hello"), content_type="application/pdf")
    assert page[1] == "image/png"
    assert page[0].startswith(b"\x89PNG")
    assert knowledge.page_images(b"not a pdf", content_type="application/pdf") == []


def test_a_page_ceiling_bounds_what_a_scan_can_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge, "MAX_OCR_PAGES", 0)
    assert knowledge.page_images(_pdf_with("Hello"), content_type="application/pdf") == []


class _Reader:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.calls: list[Sequence[knowledge.Page]] = []

    async def __call__(self, pages: Sequence[knowledge.Page]) -> list[str]:
        self.calls.append(pages)
        return self.answers


@pytest.mark.asyncio
async def test_the_text_layer_wins_and_the_reader_is_not_asked() -> None:
    reader = _Reader(["should not be used"])
    got = await knowledge.text_for_index(
        _pdf_with("Hello"), content_type="application/pdf", read=reader
    )
    assert got == knowledge.Extracted("Hello", "text")
    assert reader.calls == []


@pytest.mark.asyncio
async def test_a_scan_and_an_image_are_read_page_by_page() -> None:
    reader = _Reader(["Invoice 42\nTotal 10.00"])
    got = await knowledge.text_for_index(_pdf_with(""), content_type="application/pdf", read=reader)
    assert got == knowledge.Extracted("Invoice 42\nTotal 10.00", "ocr", 1)
    assert len(reader.calls) == 1 and reader.calls[0][0][1] == "image/png"

    reader = _Reader(["  a photo of a receipt  "])
    got = await knowledge.text_for_index(PNG, content_type="image/png", read=reader)
    assert got == knowledge.Extracted("a photo of a receipt", "ocr", 1)
    assert reader.calls[0] == [(PNG, "image/png")]


@pytest.mark.asyncio
async def test_no_reader_or_no_text_on_the_page_gives_nothing_to_index() -> None:
    assert await knowledge.text_for_index(
        PNG, content_type="image/png", read=None
    ) == knowledge.Extracted(None, "none")
    assert await knowledge.text_for_index(
        b"\xff\xfe", content_type="text/plain", read=_Reader(["never"])
    ) == knowledge.Extracted(None, "none")
    got = await knowledge.text_for_index(PNG, content_type="image/png", read=_Reader(["  "]))
    assert got == knowledge.Extracted(None, "ocr", 1)


def _reader(
    provider: FakeProvider | FailingProvider, recorded: list[UsageEvent]
) -> knowledge.ReadPages:
    providers = ProviderRegistry()
    for name in registries.PROVIDER_NAMES:
        providers.register(name, provider)

    async def record(event: UsageEvent) -> None:
        recorded.append(event)

    return page_reader(
        AIConfiguration(
            catalogue=registries.catalogue,
            routing=StaticRouting(),
            fail_closed=False,
            limits=Limits(),
        ),
        providers,
        tenant_id="tenant-1",
        user_id="user-1",
        record=record,
    )


@pytest.mark.asyncio
async def test_each_page_is_one_vision_call_with_the_image_and_is_metered() -> None:
    provider = FakeProvider([Message("assistant", "Page one"), Message("assistant", "Page two")])
    recorded: list[UsageEvent] = []
    texts = await _reader(provider, recorded)([(PNG, "image/png"), (PNG, "image/png")])
    assert texts == ["Page one", "Page two"]

    assert len(provider.requests) == 2
    request = provider.requests[0]
    assert request.model == "koras-vision"
    assert request.messages[0] == Message("system", OCR_INSTRUCTIONS)
    (image,) = request.messages[1].images
    assert image.startswith("data:image/png;base64,")
    assert request.temperature == 0.0

    assert [event.agent_id for event in recorded] == [OCR_AGENT, OCR_AGENT]
    assert recorded[0].tenant_id == "tenant-1"
    assert recorded[0].user_id == "user-1"
    assert recorded[0].model_alias == "koras-vision"
    assert recorded[0].status == "ok"
    assert recorded[0].usage.total == 15


@pytest.mark.asyncio
async def test_a_failed_attempt_is_recorded_and_the_refusal_reaches_the_indexer() -> None:
    provider = FailingProvider(AIError(ErrorCode.TOOL_DENIED, "no"))
    recorded: list[UsageEvent] = []
    with pytest.raises(AIError) as raised:
        await _reader(provider, recorded)([(PNG, "image/png")])
    assert raised.value.code == ErrorCode.TOOL_DENIED
    assert [event.status for event in recorded] == ["error"]
    assert recorded[0].error_code == "tool_denied"
