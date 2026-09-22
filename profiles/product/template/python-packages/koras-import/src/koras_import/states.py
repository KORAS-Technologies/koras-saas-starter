"""The states an import run moves through, and the ones it may move to.

Written down here rather than implied by a column check, because the states
*are* the feature: `validated` is a terminal state that wrote nothing, which is
what makes a dry run a dry run rather than a promise.

The machine, with the only edges that exist:

    created ──► mapped ──► validating ──► validated ──► commit_requested
                              │              │                │
                              │              ▼                ▼
                              │       validation_failed   committing
                              │              │                │
                              └──────────────┴────────────────┼──► failed
                                             │                │
                                             └──► mapped      ▼
                                          (fix and try again)  committed

    cancelled ◄── any state that is not terminal

Two properties this file exists to keep true. **A run cannot reach `committed`
without having been `validated`**, so nothing is ever written from rows nobody
checked. And **`validation_failed` goes back to `mapped`**, not straight to
validating: a person whose file was wrong changes the mapping or the file, and
re-validating the same mapping over the same file would produce the same
errors.
"""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    #: The source file is uploaded and the target is chosen. Nothing is mapped.
    CREATED = "created"
    #: Columns are mapped to fields. Nothing is read beyond the header.
    MAPPED = "mapped"
    #: A worker is reading the file. Transient; a run left here by a crash is
    #: visible rather than lost, which is why it is a state and not a flag.
    VALIDATING = "validating"
    #: The dry run finished and **wrote nothing**. Terminal until somebody
    #: confirms.
    VALIDATED = "validated"
    #: The dry run found problems. Also wrote nothing.
    VALIDATION_FAILED = "validation_failed"
    #: A person has confirmed. The worker has not started.
    COMMIT_REQUESTED = "commit_requested"
    #: A worker is writing. The one state during which rows appear.
    COMMITTING = "committing"
    COMMITTED = "committed"
    #: Something went wrong that was not the data's fault: storage was
    #: unreachable, the worker died, the plan lapsed mid-run.
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Terminal: nothing moves out of these.
TERMINAL: frozenset[RunState] = frozenset(
    {RunState.COMMITTED, RunState.FAILED, RunState.CANCELLED}
)

#: States in which no row of the target table has been written. Everything
#: except the two that write, and worth naming rather than inferring: a
#: cancellation that is safe in one of these is not safe in `committing`.
WROTE_NOTHING: frozenset[RunState] = frozenset(
    {
        RunState.CREATED,
        RunState.MAPPED,
        RunState.VALIDATING,
        RunState.VALIDATED,
        RunState.VALIDATION_FAILED,
        RunState.COMMIT_REQUESTED,
    }
)

_EDGES: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.MAPPED, RunState.CANCELLED}),
    # Re-mapping before validating is ordinary: a person changes their mind
    # about which column is which.
    RunState.MAPPED: frozenset(
        {RunState.MAPPED, RunState.VALIDATING, RunState.CANCELLED}
    ),
    RunState.VALIDATING: frozenset(
        {
            RunState.VALIDATED,
            RunState.VALIDATION_FAILED,
            RunState.FAILED,
            RunState.CANCELLED,
        }
    ),
    # Back to `mapped` so a different mapping can be tried against the same
    # file without a second upload.
    RunState.VALIDATED: frozenset(
        {RunState.COMMIT_REQUESTED, RunState.MAPPED, RunState.CANCELLED}
    ),
    RunState.VALIDATION_FAILED: frozenset({RunState.MAPPED, RunState.CANCELLED}),
    # **`failed` is here, and it is not symmetry.** A commit can fail before
    # it starts: the queue is unconfigured, the target lost its writer, the
    # product no longer declares it. Without this edge the only way to record
    # any of those raises, uncaught, and the run is stranded in
    # `commit_requested` with nothing able to move it ever again. IMP2-02 in
    # `docs/features/data-import/phase-2-review.md`.
    RunState.COMMIT_REQUESTED: frozenset(
        {RunState.COMMITTING, RunState.FAILED, RunState.CANCELLED}
    ),
    # **No edge to `cancelled`.** A commit is one transaction; a cancellation
    # that arrived half way through would either do nothing or leave the run
    # claiming something untrue about what it wrote.
    RunState.COMMITTING: frozenset({RunState.COMMITTED, RunState.FAILED}),
    RunState.COMMITTED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


def may_move(current: RunState, target: RunState) -> bool:
    """Whether a run in `current` may become `target`."""
    return target in _EDGES[current]


def next_states(current: RunState) -> frozenset[RunState]:
    return _EDGES[current]


def is_terminal(state: RunState) -> bool:
    return state in TERMINAL


def wrote_nothing(state: RunState) -> bool:
    """Whether a run in this state has written no row of the target table.

    What a cancellation route reads before it answers, and what a support
    question is answered with. `committing` is the only non-terminal state this
    is false for, which is exactly why it has no edge to `cancelled`.
    """
    return state in WROTE_NOTHING


class TransitionRefused(ValueError):
    """The move a caller asked for is not an edge of this machine."""


def require_move(current: RunState, target: RunState) -> None:
    """Raise unless the move is allowed.

    Called before the update, so a refusal names both states while the caller
    is still on the stack — rather than an `UPDATE ... WHERE status = ?` that
    matches nothing and reads as "the run disappeared".
    """
    if not may_move(current, target):
        allowed = ", ".join(sorted(state.value for state in _EDGES[current])) or "nothing"
        raise TransitionRefused(
            f"an import run in {current.value} cannot become {target.value}; "
            f"it may become: {allowed}"
        )
