"""A message with images goes to the gateway as content parts, and one without stays text."""

from __future__ import annotations

from koras_ai import Message
from koras_ai.providers import _message_to_wire


def test_a_plain_message_is_a_string_on_the_wire() -> None:
    assert _message_to_wire(Message("user", "hi")) == {"role": "user", "content": "hi"}


def test_an_image_message_is_text_then_images_on_the_wire() -> None:
    wire = _message_to_wire(
        Message("user", "Transcribe this.", images=("data:image/png;base64,AAAA",))
    )
    assert wire == {
        "role": "user",
        "content": [
            {"type": "text", "text": "Transcribe this."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }
