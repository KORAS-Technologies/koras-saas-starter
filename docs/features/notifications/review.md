# The dispatch seam and the table seam — review

Run 2026-09-20, against commit `8d7ed3b`, the day after both landed. Scope:
`core/dispatch.py`, `core/recipients.py`, the assistant's route onto them, and
the shared table's server-paging and column-arrangement seams.

**Verdict: BLOCK.** Two high, three medium, one low. Neither seam is wrong about
what it decides; both are wrong about what they cost, and one of the table's two
new controls does not visibly work at all.

That is four BLOCKs from four independent reviews in this repository. The rate
is not going down, and the common factor is unchanged: these two seams were
written and reviewed inside one session, and the review below is the first time
anything asked what they do with ten recipients or a narrow column.

## Findings

| ID | Severity | Summary | State |
|----|----------|---------|-------|
| DISP-01 | **High** | The dispatch point makes roughly five database round trips per recipient, on the request path | **Fixed** |
| TBL-01 | **High** | A resized column does not get narrower, because the table's layout is `auto` | **Fixed** |
| DISP-02 | Medium | Mail renders once per person; the feed renders once per language | **Fixed** |
| DISP-03 | Medium | One fail-open direction for two channels whose failures cost different things | **Fixed** |
| TBL-02 | Medium | A served table's first load shows "nothing here yet" before the rows arrive | **Fixed** |
| TBL-03 | Low | A side effect inside a React state updater | **Fixed** |

---

### DISP-01 — Five round trips per recipient, on the request path. **High.**

`_enabled` resolves one preference for one person, and it reads *all three
scopes* to do it:

```python
resolved, _ = resolve_setting(
    definition,
    global_values=await global_values(session),          # the same rows, every call
    organization_values=await tenant_values(session, tenant_id),   # likewise
    member_values=await member_values(session, tenant_id, subject),
)
```

It is called once per person per channel, and `recipients._locale_of` reads the
same member row again. Counted against the test session:

| Approvers | Statements | `global_settings` | `tenant_setting_values` | `member_setting_values` |
|-----------|-----------|-------------------|-------------------------|--------------------------|
| 1 | 9 | 2 | 2 | 2 |
| 3 | 19 | 4 | 4 | 6 |
| 10 | **54** | **11** | **11** | **20** |

The platform's defaults and the organisation's values are two row sets that
cannot change during one dispatch, and they are read eleven times each. Every
member's own row is read twice. This happens inside the assistant's turn, while
somebody waits for an answer.

It would have passed review by behaviour forever: every test asserts what was
decided, and none asks what it cost. Ten approvers is an ordinary organisation.

**Fixed.** `Preferences` reads the two shared scopes once per dispatch and each
member's row once, then answers from memory. The resolution itself still goes
through `koras_settings.resolve`, because that is the property worth keeping —
the send and the settings page produce their answers with the same code. Ten
approvers now cost 2 shared reads, 10 member reads and the inserts, and the
generator's test asserts that the shared reads do not grow with the audience.

### TBL-01 — A resized column does not get narrower. **High.**

The table renders `<table className="w-full border-collapse …">`, which is
`table-layout: auto`. Under automatic layout a `width` on a cell is a *hint*:
the browser satisfies content first and will simply ignore a width narrower than
the widest unbreakable content in the column. So dragging a column wider works
and dragging it narrower does nothing, on exactly the columns anybody would want
to narrow — the ones with long text in them.

That makes `grid.allowColumnResize` a control that half works, offered the same
day it was surfaced, which is the failure `surfaced=False` exists to prevent
appearing in a different form: not a control that does nothing, but one that
does nothing in the direction people reach for.

**Fixed.** The table switches to `table-layout: fixed` as soon as any column
carries a stored width, and cells get `truncate` so content that no longer fits
is clipped with an ellipsis rather than forcing the column open again. Automatic
layout stays the default, because it is the better one for a table nobody has
arranged.

### DISP-02 — Mail renders per person, the feed per language. **Medium.**

`_to_feed` groups recipients by locale and calls the template once per language;
`_to_mail` loops people and calls it once each. The module's own docstring
claims the first behaviour and the generator's test asserts it — but only
against the feed, because the case it uses has no addresses in it. A template
doing real work would be doing it once per recipient in the inbox half and
nobody would learn that from a test.

**Fixed.** Both halves group by language and share one rendering cache, so a
template is called once per language per dispatch whichever channel wants it.

### DISP-03 — One fail-open direction for two different costs. **Medium.**

`_enabled` returns `True` when the settings table cannot be read, for both
channels, on the reasoning that "the alternative is silently telling nobody
anything".

That is right for the feed and wrong for mail, and the asymmetry is the point.
If the settings read fails and the feed is written anyway, the worst case is a
notification somebody did not want in a list they can clear. If mail is sent
anyway, the worst case is mail to somebody who explicitly switched it off —
which cannot be recalled, is the thing people complain to a regulator about, and
is unnecessary because **the feed row exists either way**. The notification is
not lost by holding the mail; only the second copy of it is.

**Fixed.** The feed fails open and mail fails closed, each with the reason at the
point of decision, and a skip reason of its own so a dispatch that held mail
because it could not read a preference is distinguishable from one that held it
because somebody opted out.

### TBL-02 — "Nothing here yet" before the rows arrive. **Medium.**

```tsx
if (data.length === 0) {
  return <p>{empty}</p>   // `loading` is not consulted
}
```

For a client-paged table this is right: an empty array means an empty list. For
a served one, the first render has no rows *because they have not arrived*, so
every server-paged table opens by telling the reader there is nothing there and
then contradicting itself. The sentence is the worst possible one to show
wrongly, which is the same argument this repository already applied to the
Restore page's empty backup catalogue and to the import page's target list.

**Fixed.** An empty *and* loading table renders the frame with a busy pager
rather than the empty sentence. The sentence is for "there is nothing", not for
"we do not know yet".

### TBL-03 — A side effect inside a state updater. **Low.**

```tsx
setArrangement((current) => {
  if (remembers && tableId) writeArrangement(tableId, current)
  return current
})
```

A reducer used to read the latest state. React may call an updater more than
once — Strict Mode does so deliberately — so this can write twice. The write is
idempotent, so nothing breaks today; it is a pattern that breaks the next time
somebody puts something non-idempotent in one.

**Fixed.** The current arrangement is kept in a ref alongside the state, and the
write reads the ref.

## What this review did not cover

- **A browser.** Nothing here was opened in one. TBL-01 was found by reading a
  CSS property, not by dragging a column, and the fix has not been dragged
  either.
- **A real send.** No mail has left a deployed product through this seam.
- **Concurrency.** Two dispatches for one tenant in flight at once share
  nothing, which looks right and has not been exercised.
