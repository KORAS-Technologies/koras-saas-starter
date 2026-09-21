FW-HARDEN-001 run 2026-09-21-01 -- the reproductions, before any change.

Both findings were reproduced against a worktree of 7199f85 checked out under
this machine's normal Git configuration (core.autocrlf=true, core.eol=crlf),
which is the configuration FW-DEF-002 is about. Nothing was changed first.

FW-DEF-002
  command: vitest run tests/orchestration.test.ts
  result : Tests  41 failed | 458 passed (499)
  note   : identical to the count G7 R2 recorded. 40 of the 41 are the
           `has frontmatter naming itself` family; the 41st is
           `does not ship forty near-identical files`, which is the
           /## X\n\n(...)\n\n## Y/ section regex.

  class boundary, same tree:
    whole generator suite  -> only orchestration.test.ts fails on line endings
                              (one further file failed on an unbuilt dist,
                              which is the worktree and not a defect)
    tests/docs suite       -> 412 passed, CRLF-clean

  the silent third site, found by probe rather than by failure:
    body.slice(4, body.indexOf('\n---', 4))
      LF   tree -> frontmatter begins "name: "
      CRLF tree -> frontmatter begins "\nname:"
    i.e. one byte late, passing on both trees while measuring the wrong bytes.

  a site suspected and cleared by measurement:
    /^description: (.+)$/m is safe. In JavaScript a carriage return is a line
    terminator, so `.` already excludes it and `$` already matches before it.

FW-GAP-006
  method : a matcher implementing the semantics gate-invalidation.yaml
           declares -- ordered classes, first match wins, ** spans segments.
  result : every profiles/product/template/** path returns no class.
           packages/ui/src/data-table.tsx             -> frontend_code
           profiles/product/template/packages/...tsx  -> (none)
           profiles/product/template/e2e/...spec.ts   -> (none)
           services/api/static/mail.css               -> backend_code

  consequence, computed from the gates' own inputs rather than asserted:
    from G7 R2's real diff only automated_test_node is derivable
    -> 21 gates reusable, including all four that feature most needed:
       accessibility_pass, e2e_pass, screenshot_evidence_complete,
       independent_code_review
