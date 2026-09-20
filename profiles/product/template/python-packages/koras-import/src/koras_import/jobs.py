"""The background work an import run needs, declared once.

**Here rather than in the API or the worker, and that is the whole reason
`TaskDefinition` holds no coroutine.** The API enqueues; the worker runs; and
if the declaration lived in either, the other would have to import it. The
worker's image carries one narrow copy of the API's own package and reaches it
through `importlib` with a graceful failure — which is right for a *catalogue*
read at run time, and wrong for a task name the worker's `functions` list needs
at import: a worker that started with the import task silently unbound would
accept the job and never run it.

So the names, the retry policies and the timeouts are declarations in the
shared package, and each side binds what it needs.
"""

from __future__ import annotations

from koras_queue import RetryPolicy, TaskDefinition

#: Reading the file and checking every row. **Tried once.**
#:
#: A person is waiting on this and a dry run writes nothing, so a silent second
#: attempt buys nothing a visible failure does not: they press validate again.
#: Retrying would also re-read a file that may have been quarantined by a
#: scanner in between, which is a second reason to let a person decide.
VALIDATE_RUN = TaskDefinition(
    name="imports.validate",
    summary="Read an uploaded file and check every row against its target.",
    retry=RetryPolicy(attempts=1),
    # Well above the worker's own 300 seconds. A validation pass over a file at
    # the row ceiling is minutes of work, and the alternative -- raising the
    # worker's timeout for everything -- would let a hung sweep hold a slot for
    # a quarter of an hour. This is the per-task patience PLAT-F1 exists to
    # make declarable.
    timeout_seconds=900,
    tags=("import",),
)

#: Writing the rows. **Also tried once**, and for a stronger reason: a commit
#: is one transaction over a whole run, and an automatic second attempt after a
#: failure nobody has looked at is how a half-understood error becomes two.
#:
#: Declared here with the validation task because the pair is the feature, and
#: because a name added later in a different file is a name that ends up
#: spelled differently. Phase 2 binds it; nothing enqueues it yet.
COMMIT_RUN = TaskDefinition(
    name="imports.commit",
    summary="Write the rows of a validated import run, all or nothing.",
    retry=RetryPolicy(attempts=1),
    timeout_seconds=900,
    tags=("import",),
)
