# zh-Hans docs parity gates

Three checks that keep `website/i18n/zh-Hans/...` in step with `website/docs/`,
plus two repair tools. Written during the 2026-09-08 sweep that took the locale
from 97 structurally-drifted pages, 42 untranslated pages and 92 broken anchors
to zero of each.

## Run them

```bash
# the page list every tool takes
git ls-files website/i18n/zh-Hans/docusaurus-plugin-content-docs/current \
  | grep -E '[.]mdx?$' \
  | sed 's|^website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/||' > zh.txt

python website/scripts/i18n/verify_parity.py --file zh.txt   # structure
python website/scripts/i18n/content_drift.py zh.txt --min 1  # content
python website/scripts/i18n/anchor_audit.py  zh.txt          # anchors
```

Each resolves the repo root itself (see below), and each **prints the root it
used** — check that line before believing the result.

## They catch disjoint things. Run all three, and build the site too.

| Gate | Catches | Blind to |
|---|---|---|
| `verify_parity.py` | half-translated or wholly stale pages | stale content inside a structurally-perfect page; fabricated content |
| `content_drift.py` | stale prose, table rows, config keys — via link targets and inline code, which are never translated | anything it normalises away (notably the `/docs/` prefix) |
| `anchor_audit.py` | in-page links broken by translating their target heading | cross-page `page#fragment` links |

**The static gates are necessary and not sufficient.** On 2026-09-08 they all
passed while 115 links were broken, because `content_drift.py` deliberately
normalises the `/docs/` prefix away and so cannot see it being wrongly *present*.
Only `npm run build` caught it. **A gate that normalises a difference away can
never detect that difference.**

And when you do build: `onBrokenLinks` and `onBrokenMarkdownLinks` are both
`warn`, so the build **exits 0 with broken references**. Parse the log for
`Docusaurus found broken links` / `broken anchors`; the exit code proves nothing.

## Root resolution — and why there is no fallback

`--root <repo>` → `$HERMES_DOCS_ROOT` → `git rev-parse --show-toplevel` from the
cwd. If none yields a directory containing both docs trees, the tools **exit 2**
rather than guess.

That refusal is the point. The originals hardcoded `ROOT` to the one worktree
that authored them, so running them from any other worktree silently checked the
author's files and printed `0 FAIL` for work the caller never made — a false
green with no symptom. Every agent here runs from its own worktree, so that was
not an edge case. An empty page list is rejected for the same reason: `0 checked,
0 FAIL` is indistinguishable from a pass.

## Repair tools

```bash
python website/scripts/i18n/anchor_fix.py zh.txt            # dry run
python website/scripts/i18n/anchor_fix.py zh.txt --apply

cd website && npm run build > build.log 2>&1
python scripts/i18n/xpage_anchor_fix.py build.log --apply   # cross-page
```

Both pin the translated heading with an explicit `{#english-anchor}` id, placed
**by ordinal**: they find the English heading whose slug matches and pin the zh
heading at the same position. That is sound only at heading parity, so pages that
are not are skipped and reported — run `verify_parity.py` first.

## Known permanent false positives — do not "fix" these

`content_drift.py` pairs backticks per line, so a code span **hard-wrapped across
a newline in the English source** splits into two bogus half-spans. English wraps
prose at ~80 cols and Chinese does not. Four are known:

| item | English source |
|---|---|
| `is` | `slack.md` 449-450 |
| `hermes` | `pipe-script-output.md` 23-24 |
| `terminal.home_mode:` | `profiles.md` 293-294 |
| `PRAGMA` | `session-storage.md` 160-161 |

The zh pages carry the complete spans on one line. Driving the count to zero
would mean fabricating a bare fragment in the Chinese. A gate wired into CI must
tolerate exactly these or it is red forever.

## Metrics that do NOT work here

- **Commit counts.** A translation lands in its own commit, so sha-set difference
  never reaches zero. Right after `security.md` was verified line-for-line
  current, that metric still called it nine commits behind.
- **Line-count delta.** Chinese renders the same content in fewer lines, so a
  correct page routinely differs by dozens. The naive "prose drift" bucket *rose*
  from 44 to 89 pages while the tree was getting strictly better. `verify_parity`
  reports a line ratio as **advisory only**; it never fails on it.

## Translating

`ZH_SWEEP_BRIEF.md` beside this file is the worker brief: the en-self-diff method
(diff the English file against *itself* across the lag window, then subtract the
commits the zh page already received — checking `--stat` magnitude, since a
commit can touch the zh file trivially while rewriting the English wholesale),
the per-file convention rule, and the anchor rule.
