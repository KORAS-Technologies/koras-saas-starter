"""`python -m promotion <gate|activation|f1|provider> ...` - dispatches to each module's own CLI."""

from __future__ import annotations

import sys

from . import activation, f1, gate, provider_qualification

_COMMANDS = {
    "gate": gate.main,
    "activation": activation.cli,
    "f1": f1.main,
    "provider": provider_qualification.main,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in _COMMANDS:
        print(f"usage: python -m promotion {{{'|'.join(_COMMANDS)}}} ...", file=sys.stderr)  # noqa: T201
        return 2
    return int(_COMMANDS[args[0]](args[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
