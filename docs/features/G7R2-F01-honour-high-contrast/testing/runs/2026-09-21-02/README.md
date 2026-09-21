# Run 2026-09-21-02 — fresh-runtime 40-agent discovery proof

| | |
|---|---|
| **Gate** | `runtime_discovery`, full-catalog check (`agent-registry.yaml` → `full_catalog_check_when: a G7 or equivalent conformance run`) |
| **Commit under test** | `48e762a` (`develop`, clean, level with `origin/develop`) |
| **Environment** | Windows 11, Claude Code 2.1.178, a **fresh** `claude -p` process per probe, cwd = a product generated from `48e762a` at `<scratchpad>/gen/g7r2-proof` |
| **Subject** | The generated product, not the factory. The factory registers no product agents by design (its `.claude/agents/` holds four legacy files with no frontmatter), so a Product-profile runtime is the only place this can be measured. |
| **Result** | **PASS.** REGISTERED=40, DISCOVERABLE=40, exact correspondence, no duplicate, no missing, no legacy substitution. |

## Registry side, on disk

```
$ find .claude/agents -name '*.md' | wc -l
44
$ grep -rl "^name: " --include='*.md' . | wc -l
40
$ ls *.md            # the four legacy, top level, no frontmatter
architect.md  frontend.md  reviewer.md  tester.md
```

44 files, 40 with agent frontmatter, 4 legacy without — exactly what the
factory's own `CLAUDE.md` states, and the reason a generated product has 40
agents rather than 44.

## Probe 1 — free-form transcription (FIRST ATTEMPT, RETAINED)

Command, verbatim:

```
echo "Do not use any tools at all. From the list of available agent types for the Agent tool in your system prompt, output ONLY the agent type names, one per line, no descriptions, no commentary. Then a final line: COUNT=<n>." | claude -p
```

Result: `COUNT=61` over the whole mixed list (Koras agents + plugin agents +
built-ins). Of the 40 Koras agents, **37 were transcribed and three were not**:
`accessibility-qa`, `ai-evaluation`, `ai-specialist` — the three alphabetically
first entries. Full output at `probe-1-output.txt`.

**This first attempt is retained rather than erased by the later green runs.**
It looked exactly like the FW-DEF-001 shortfall (a session listing fewer agents
than exist) and was not one.

## Probe 2 — targeted presence check

```
echo "Do not use any tools at all. Answer from your system prompt only. Are the following agent types available to your Agent tool? ... accessibility-qa, ai-specialist, ai-evaluation, unit-test, code-reviewer. ... COUNT_KORAS=<...>" | claude -p
```

All five `YES`; `COUNT_KORAS=40`. Full output at `probe-2-output.txt`.

## Probe 3 — numbered enumeration (decisive)

```
echo "Do not use any tools at all. ... Output a NUMBERED list (1., 2., 3., ...) of every agent type that is a Koras engineering agent ... Sort alphabetically. Include every one; do not abbreviate or elide. Then a final line TOTAL=<n>." | claude -p
```

`TOTAL=40`, the list numbered 1–40, matching `agent-registry.yaml` entry for
entry. Full output at `probe-3-output.txt`.

## Classification of the probe-1 shortfall

A defect in the measuring instrument, not in the runtime and not
in the repository. A free-form transcription of a 61-item list silently elides
entries; probes 2 and 3 asked questions whose answers cannot be elided without
being visibly wrong, and both agree with the registry.

It is **not** `SESSION_OR_TOOL_HEALTH` (FW-DEF-001): all three probes ran in separate
fresh processes against the same commit, and the two instruments that can be
checked agree. It is **not** contradictory evidence requiring escalation, because
the instruments are not of equal standing — one asks the model to copy 61 lines,
the others ask it 40 answerable questions.

**What this run proves:** the 40 Product-profile agents authored at `48e762a` are
all discoverable to a fresh Claude Code runtime in a project generated from it.
**What it does not prove:** that discovery stays complete across a long-lived
session. FW-DEF-001 remains open and this run says nothing about it — every probe
here was a fresh process, deliberately.
