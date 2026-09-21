FW-HARDEN-001 run 2026-09-21-03 -- the Windows proof.

A worktree created fresh from the fix commit under this machine's normal Git
configuration. Not a simulation: git reports core.autocrlf=true, core.eol=crlf,
and the agent definitions arrive CRLF, verified at the byte level before
anything was run.

  head -c 16 .../engineering-orchestrator.md | od -c
  0000000   -   -   -  \r  \n   n   a   m   e   :       e   n   g   i   n

canonical agent/orchestration suite
  Test Files  1 passed (1)
  Tests       552 passed (552)
  where 7199f85 on the same kind of checkout failed 41.

whole generator suite, same tree
  Test Files  61 passed (61)
  Tests       2244 passed (2244)

That second run also settles the independent review's HIGH-2, which predicted
product-frontend.test.ts and product-shell.test.ts would fail on CRLF because
each carries a /...\n\n/ regex over a source-tree file. They do not: each file
defines its own read() that strips carriage returns before matching, with a
comment recording that this defect bit that file once already.

40 agents registered, 40 valid, zero line-ending failures.
