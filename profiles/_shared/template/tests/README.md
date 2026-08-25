# tests

Cross-cutting test suites. Tests belonging to a single service or package live
next to that code; this tree holds suites that span components or assert
project-wide invariants.

`pyproject.toml` lists `tests` first in `testpaths`, so `uv run pytest` picks
these up with no further configuration.

Note that `pytest` exits non-zero when it collects nothing, so an empty tree
fails `make test` and CI. `tests/unit/test_scaffold.py` keeps the suite
non-empty and asserts a few things worth asserting; delete it once there are
real tests.
