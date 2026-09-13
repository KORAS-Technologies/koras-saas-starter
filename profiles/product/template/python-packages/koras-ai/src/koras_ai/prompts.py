"""Prompts: versioned templates with declared variables.

A prompt is an id, a version, a template and the names the template needs.
Rendering is strict in both directions: a missing variable is an error rather
than a blank, and an unknown one is an error rather than silently ignored,
because a prompt that renders with a hole in it produces an answer that reads
as considered and is not.

The template syntax is one thing: `{name}`. No attribute access, no
formatting, no expressions -- the values a product renders into a prompt
include text a customer typed, and a template language that could reach into
an object from a string is one that text could reach into.

Versions are integers and the registry answers the highest unless asked
otherwise, which is what lets a product promote a prompt by adding a version
and demote it by removing one, with the history in the file rather than in
somebody's memory.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .errors import AIError, ErrorCode, not_found

_PROMPT_ID = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


@dataclass(frozen=True)
class PromptDefinition:
    id: str
    version: int
    template: str
    #: Every name the template uses. Declared rather than inferred, so a
    #: typo in the template is an error at definition time.
    variables: frozenset[str]
    description: str = ""

    def __post_init__(self) -> None:
        if not _PROMPT_ID.match(self.id):
            raise ValueError(f"prompt id {self.id!r} must be lower-case, like assistant.system")
        if self.version < 1:
            raise ValueError(f"prompt {self.id} version must be a positive integer")
        used = frozenset(_PLACEHOLDER.findall(self.template))
        if used != self.variables:
            missing = sorted(used - self.variables)
            unused = sorted(self.variables - used)
            raise ValueError(
                f"prompt {self.id} v{self.version}: template uses undeclared {missing} "
                f"and declares unused {unused}"
            )

    def render(self, values: Mapping[str, object]) -> str:
        given = frozenset(values)
        if given != self.variables:
            raise AIError(
                ErrorCode.INVALID_INPUT,
                f"prompt {self.id} needs exactly {sorted(self.variables)}",
                detail=(
                    f"missing {sorted(self.variables - given)}, "
                    f"extra {sorted(given - self.variables)}"
                ),
            )
        return _PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), self.template)


def define_prompt(
    *,
    id: str,
    version: int,
    template: str,
    variables: Iterable[str] = (),
    description: str = "",
) -> PromptDefinition:
    return PromptDefinition(
        id=id,
        version=version,
        template=template,
        variables=frozenset(variables),
        description=description,
    )


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[str, dict[int, PromptDefinition]] = {}

    def add(self, prompt: PromptDefinition) -> PromptDefinition:
        versions = self._prompts.setdefault(prompt.id, {})
        if prompt.version in versions:
            raise ValueError(f"prompt {prompt.id} v{prompt.version} is already registered")
        versions[prompt.version] = prompt
        return prompt

    def get(self, prompt_id: str, version: int | None = None) -> PromptDefinition:
        versions = self._prompts.get(prompt_id)
        if not versions:
            raise not_found("prompt")
        if version is None:
            return versions[max(versions)]
        prompt = versions.get(version)
        if prompt is None:
            raise not_found("prompt version")
        return prompt

    def render(
        self, prompt_id: str, values: Mapping[str, object], *, version: int | None = None
    ) -> str:
        return self.get(prompt_id, version).render(values)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._prompts))
