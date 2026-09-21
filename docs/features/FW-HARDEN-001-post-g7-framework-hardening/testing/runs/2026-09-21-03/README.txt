FW-HARDEN-001 run 2026-09-21-03 -- the Windows proof.

A worktree created fresh under this machine's normal Git configuration. Not a
simulation: git reports core.autocrlf=true and core.eol=crlf, and the agent
definitions arrive CRLF, verified at the byte level before anything was run.

  head -c 16 .../engineering-orchestrator.md | od -c
  0000000   -   -   -  \r  \n   n   a   m   e   :       e   n   g   i   n

RUN 1 -- at 575acaf, the first implementation commit
  canonical agent/orchestration suite   552 passed (552)
  whole generator suite                 61 files, 2244 tests, 0 failed
  where 7199f85 on the same kind of checkout failed 41.

RUN 2 -- at 939fdd5, after the independent review's remediation
  canonical agent/orchestration suite   557 passed (557)

  This run exists because 939fdd5 changed the parser regex itself -- the
  tempered capture, review finding LOW-8 -- so run 1 no longer covered the
  tree being accepted. Final acceptance made the same observation
  independently and re-ran it too, getting the same result.

RUN 3 -- at the accepted tree, after acceptance's own remediation
  recorded in the final report; the parser is unchanged from run 2 and the
  change is to the classifier globs, which are line-ending independent.

The run-1 generator-suite result also settles the independent review's HIGH-2,
which predicted product-frontend.test.ts and product-shell.test.ts would fail
on CRLF because each carries a two-newline regex over a source-tree file. They
do not: each file defines its own read() that strips carriage returns before
matching, with a comment recording that this defect bit that file once
already.

40 agents registered, 40 valid, zero line-ending failures, in every run.
