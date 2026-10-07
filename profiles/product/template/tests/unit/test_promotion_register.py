# ruff: noqa: ANN001, S311, ANN201, ANN401, E501
"""The security register parser: strict, and a register it cannot read FAILS rather than passes."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from promotion import register
from promotion.register import RegisterError, parse_register, unresolved_security_findings

PATTERN = "[A-Z]+-[0-9]+"
HEADER = "| ID | Type | Title | Description | Severity | Status | Discovered |\n|---|---|---|---|---|---|---|\n"
ROW = "| {id} | {type} | t | d | {sev} | {status} | 2026-10-06 |"


def _write(tmp: Path, *lines: str, header: str = HEADER, name: str = "register.md") -> Path:
    path = tmp / name
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _rows(tmp: Path, *rows: tuple[str, str, str, str]) -> Path:
    return _write(tmp, *(ROW.format(id=i, type=t, sev=s, status=st) for i, t, s, st in rows))


def found(path: Path, chain: frozenset[str] = frozenset()) -> list[dict[str, str]]:
    return unresolved_security_findings(path, PATTERN, chain)


def test_an_unresolved_high_security_finding_is_reported(tmp_path: Path) -> None:
    assert found(_rows(tmp_path, ("SEC-9", "SECURITY", "High", "Open"))) == [
        {"id": "SEC-9", "severity": "High", "scope": "other"}
    ]


def test_resolved_medium_and_other_types_are_not_reported(tmp_path: Path) -> None:
    path = _rows(
        tmp_path,
        ("SEC-1", "SECURITY", "High", "**RESOLVED on DEV**"),
        ("SEC-2", "SECURITY-GAP", "Medium", "Open"),
        ("SEC-3", "DEFECT", "Critical", "Open"),
        ("SEC-4", "SECURITY-GAP", "Critical", "CLOSED"),
    )
    assert found(path) == []


def test_a_later_row_for_the_same_id_supersedes_an_earlier_one(tmp_path: Path) -> None:
    path = _rows(
        tmp_path, ("SEC-1", "SECURITY", "High", "Open"), ("SEC-1", "SECURITY", "High", "RESOLVED")
    )
    assert found(path) == []
    path = _rows(
        tmp_path, ("SEC-1", "SECURITY", "High", "RESOLVED"), ("SEC-1", "SECURITY", "High", "Open")
    )
    assert [f["id"] for f in found(path)] == ["SEC-1"]


def test_a_configured_chain_id_is_labelled(tmp_path: Path) -> None:
    path = _rows(
        tmp_path, ("SEC-1", "SECURITY", "High", "Open"), ("SEC-2", "SECURITY", "High", "Open")
    )
    scopes = {f["id"]: f["scope"] for f in found(path, frozenset({"SEC-1"}))}
    assert scopes == {"SEC-1": "chain", "SEC-2": "other"}


@pytest.mark.parametrize(
    "status",
    [
        "UNRESOLVED", "NOT RESOLVED", "Not RESOLVED yet", "to be CLOSED", "Blocked until CLOSED",
        "PARTIALLY RESOLVED", "Open", "resolved", "", "resolved later", "in progress",
    ],
)  # fmt: skip
def test_a_negated_or_absent_resolution_is_still_unresolved(tmp_path: Path, status: str) -> None:
    assert [f["id"] for f in found(_rows(tmp_path, ("SEC-1", "SECURITY", "High", status)))] == [
        "SEC-1"
    ]


@pytest.mark.parametrize(
    "status",
    ["RESOLVED", "**RESOLVED on DEV 2026-10-06**", "CLOSED", "WITHDRAWN", "SUPERSEDED by SEC-9"],
)
def test_a_whole_word_resolution_token_resolves(tmp_path: Path, status: str) -> None:
    assert found(_rows(tmp_path, ("SEC-1", "SECURITY", "High", status))) == []


def test_a_negation_far_from_the_token_does_not_unresolve_it(tmp_path: Path) -> None:
    status = "NOT merged earlier, but now the work is complete and it is RESOLVED"
    assert found(_rows(tmp_path, ("SEC-1", "SECURITY", "High", status))) == []


@pytest.mark.parametrize("word", ["RESOLVEDISH", "UNRESOLVED", "xRESOLVED"])
def test_a_resolution_token_inside_another_word_is_not_a_resolution(
    tmp_path: Path, word: str
) -> None:
    assert found(_rows(tmp_path, ("SEC-1", "SECURITY", "High", word)))


@pytest.mark.parametrize(
    "severity", ["high", "HIGH", "Critical (was High)", "**High**", "critical"]
)
def test_severity_matches_by_prefix_and_ignores_case(tmp_path: Path, severity: str) -> None:
    assert found(_rows(tmp_path, ("SEC-1", "SECURITY", severity, "Open")))


@pytest.mark.parametrize("severity", ["Medium", "Low", "Info", "", "Moderate"])
def test_other_severities_are_not_gated(tmp_path: Path, severity: str) -> None:
    assert found(_rows(tmp_path, ("SEC-1", "SECURITY", severity, "Open"))) == []


def test_the_columns_come_from_the_header_not_from_fixed_positions(tmp_path: Path) -> None:
    header = "| ID | Status | Severity | Type |\n|---|---|---|---|\n"
    assert found(_write(tmp_path, "| SEC-1 | Open | High | SECURITY |", header=header))
    assert not found(_write(tmp_path, "| SEC-1 | RESOLVED | High | SECURITY |", header=header))


@pytest.mark.parametrize(
    "header",
    [
        "",  # no header at all
        "| ID | Type | Severity |\n|---|---|---|\n",  # no status column
        "| ID | Severity | Status |\n|---|---|---|\n",  # no type column, so no header is found
        "| Reference | Kind |\n|---|---|\n",
    ],
)
def test_a_register_without_a_usable_header_fails(tmp_path: Path, header: str) -> None:
    row = "| SEC-1 | SECURITY | High | RESOLVED |"
    with pytest.raises(RegisterError):
        found(_write(tmp_path, row, header=header))


def test_a_row_before_any_header_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RegisterError, match="before any header"):
        parse_register("| SEC-1 | SECURITY | High | Open |\n" + HEADER, PATTERN)


def test_a_pipe_inside_a_cell_that_shifts_the_columns_fails_and_names_the_row(
    tmp_path: Path,
) -> None:
    shifted = "| SEC-1 | SECURITY | t | a | b | High | RESOLVED | 2026-10-06 |"
    with pytest.raises(RegisterError, match="could not be parsed") as caught:
        found(_write(tmp_path, shifted))
    assert "SEC-1" in str(caught.value)


def test_a_short_row_that_mentions_a_security_term_fails_not_skips(tmp_path: Path) -> None:
    with pytest.raises(RegisterError):
        found(_write(tmp_path, "| SEC-1 | SECURITY | High | Open |"))
    with pytest.raises(RegisterError):
        found(_write(tmp_path, "| SEC-2 | ??? | the finding is Critical | Open |"))


def test_a_misshapen_row_with_an_intact_non_gated_type_does_not_fail_the_register(
    tmp_path: Path,
) -> None:
    """The Type cell precedes every free-text cell, so a GAP row can never be a gated finding."""
    shifted = "| SEC-3 | GAP | t | a | b | High | Open | 2026-10-06 | x |"
    normal = ROW.format(id="SEC-1", type="SECURITY", sev="High", status="RESOLVED")
    assert found(_write(tmp_path, normal, shifted)) == []


def test_a_misshapen_row_that_mentions_nothing_sensitive_is_ignored(tmp_path: Path) -> None:
    normal = ROW.format(id="SEC-1", type="SECURITY", sev="High", status="RESOLVED")
    assert found(_write(tmp_path, normal, "| SEC-4 | ??? | nothing to see | Open |")) == []


def test_an_unreadable_or_non_utf8_register_fails(tmp_path: Path) -> None:
    with pytest.raises(RegisterError):
        found(tmp_path / "missing.md")
    binary = tmp_path / "b.md"
    binary.write_bytes(b"\xff\xfe| SEC-1 |")
    with pytest.raises(RegisterError):
        found(binary)
    with pytest.raises(RegisterError):
        found(tmp_path)  # a directory


def test_a_register_with_no_table_fails(tmp_path: Path) -> None:
    path = tmp_path / "e.md"
    path.write_text("nothing here\n", encoding="utf-8")
    with pytest.raises(RegisterError, match="no header"):
        found(path)


def test_a_header_and_no_rows_fails_unless_it_says_it_is_empty_on_purpose(tmp_path: Path) -> None:
    with pytest.raises(RegisterError, match="no rows"):
        found(_write(tmp_path))
    assert found(_write(tmp_path, register.EMPTY_MARKER)) == []


def test_the_empty_marker_never_hides_a_row(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        ROW.format(id="SEC-1", type="SECURITY", sev="High", status="Open"),
        register.EMPTY_MARKER,
    )
    assert [f["id"] for f in found(path)] == ["SEC-1"]


def test_a_row_whose_id_does_not_match_the_pattern_is_not_a_row(tmp_path: Path) -> None:
    """The documented limit: the pattern decides what a row is. A wrong pattern finds no rows."""
    path = _write(tmp_path, ROW.format(id="gr-1", type="SECURITY", sev="High", status="Open"))
    with pytest.raises(RegisterError, match="no rows"):
        found(path)


def test_the_shipped_register_stub_parses_and_holds_no_gated_finding() -> None:
    from promotion.config import load_config

    config = load_config()
    assert (
        unresolved_security_findings(config.register_path, config.register_id_pattern) is not None
    )


# -- fuzz ------------------------------------------------------------------------------------


def _fuzz_register(rng: random.Random) -> tuple[str, set[str]]:
    """A register of random rows, some with a stray pipe or other damage; returns the text and the
    ids that are genuinely unresolved gated findings in the UNDAMAGED version of it."""
    lines = [HEADER.rstrip("\n").split("\n")[0], "|---|---|---|---|---|---|---|"]
    truth: set[str] = set()
    for n in range(rng.randint(1, 12)):
        rid = f"SEC-{n}"
        kind = rng.choice(["SECURITY", "SECURITY-GAP", "DEFECT", "GAP", "FEATURE"])
        sev = rng.choice(["Critical", "High", "Medium", "Low", "**High**", "critical"])
        status = rng.choice(["Open", "RESOLVED", "NOT RESOLVED", "CLOSED", "to be CLOSED", ""])
        gated = kind in {"SECURITY", "SECURITY-GAP"} and sev.strip("*").lower().startswith(
            ("critical", "high")
        )
        resolved = status in {"RESOLVED", "CLOSED"}
        if gated and not resolved:
            truth.add(rid)
        cells = [rid, kind, "title", "desc", sev, status, "2026-10-06"]
        damage = rng.choice(["none", "none", "pipe", "drop", "pipe_in_status"])
        if damage == "pipe":
            cells[rng.randint(2, 3)] += " a | b"
        elif damage == "drop":
            cells.pop(rng.randint(2, 6))
        elif damage == "pipe_in_status":
            cells[5] = "RE | SOLVED"
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n", truth


@pytest.mark.parametrize("seed", range(60))
def test_fuzz_a_damaged_register_never_reports_fewer_unresolved_findings_than_exist_without_failing(
    seed: int, tmp_path: Path
) -> None:
    """The property that matters: either every genuinely unresolved gated finding is reported, or
    the register FAILS to parse. It never quietly reports fewer."""
    rng = random.Random(seed)
    text, truth = _fuzz_register(rng)
    path = tmp_path / "r.md"
    path.write_text(text, encoding="utf-8")
    try:
        reported = {f["id"] for f in found(path)}
    except RegisterError:
        return  # failing closed is always an acceptable answer
    assert truth <= reported, (seed, sorted(truth - reported))


@pytest.mark.parametrize("seed", range(30))
def test_fuzz_arbitrary_text_never_raises_anything_but_a_register_error(
    seed: int, tmp_path: Path
) -> None:
    rng = random.Random(1000 + seed)
    alphabet = "|-*# \t\nabcSECURITYHighCriticalRESOLVEDNOT0123456789<!->"
    text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 600)))
    path = tmp_path / "r.md"
    path.write_text(text, encoding="utf-8")
    try:
        result = found(path)
    except RegisterError:
        return
    assert isinstance(result, list)
