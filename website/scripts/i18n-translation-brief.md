# Translating a zh-Hans page — worker brief

How to bring a `website/i18n/zh-Hans/...` page up to its English counterpart.
The **checking** side is `check-i18n-parity.py` / `fix-i18n-anchors.py` /
`check-build-links.py` and their CI wiring; this file is the other half, the
method for actually doing a sweep. Distilled from the 2026-09-08 sweep that took
the locale from 97 structurally-drifted pages, 42 untranslated pages and 92
broken anchors to zero of each.

Paths: English `website/docs/<rel>`, Chinese
`website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/<rel>`.

## Method: diff English against ITSELF, then subtract

Do **not** diff English against Chinese — the output is dominated by the
translation and tells you nothing. Diff the English file against its own past:

```bash
git log --oneline <bulk-translation-sha>..HEAD -- website/docs/<rel>
git diff        <bulk-translation-sha>..HEAD -- website/docs/<rel>
```

That is exactly the set of English changes the zh page may be missing, in patch
order, with zero noise. Then **subtract the commits the zh page already
received**:

```bash
git show <sha> --stat -- website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/<rel>
```

If the zh file appears there, that change is probably already translated —
re-translating it would revert a colleague's correct work. This subtraction is
the step an en-vs-zh diff cannot give you.

### But presence is not proof — check the `--stat` magnitude

A commit can touch the zh file *trivially* (a link fix, a renamed identifier)
while rewriting the English page wholesale. Measured: `f2e37549c6` touched zh
`computer-use.md` with **1 insertion / 2 deletions** against a full-page English
rewrite; the zh page was still the 144-line macOS-only version against a 470-line
English page. By bare presence you would have skipped it and left 326 lines
stale. Read the numbers, and sanity-check the two files' line counts against each
other.

## Conventions

- **Convention is PER FILE, not per repo.** Some pages leave YAML/bash
  code-block comments in English; others translate them. In one task,
  `creating-skills.md` left them English while `security.md` translated them.
  Read the file you are editing.
- Translate: prose, headings, table headers and cells, admonition titles
  (`:::tip 标题`), list items, image alt text.
- Never translate: code identifiers, CLI commands, flags, env var names, file
  paths, URLs, config keys, frontmatter keys, anchor ids, link-reference labels.
- **Never translate literal syntax** — tokens a user types. `@mention`,
  `@username`, `**bold**`, `*italic*`, `~strike~`. Rendering `*bold*` as
  `*粗体*` makes the documented syntax simply wrong. A Chinese gloss alongside is
  fine. This was a recurring real defect, found on six pages.
- Use `——` for the em-dash, matching existing pages.
- **Skill-page links drop the `/docs/` prefix.** `routeBasePath` is `/`, so the
  prefixed form resolves nowhere. This is the one place the sweep deliberately
  does not keep a link target byte-identical.

## In-page anchors — mandatory

Translating a heading changes the anchor Docusaurus generates, so
`[x](#some-anchor)` silently stops resolving. Keeping the link target
byte-identical is **necessary but not sufficient**. Pin the translated heading:

```markdown
## Token 冲突防护 {#token-conflict-safety}
```

Much of the tree once kept English anchors without pinning, so those were simply
broken. Do not copy that.

## Writing the file

**Never use a Bash heredoc for text containing a backslash.** It mangles
backslash literals and this **survives a quoted delimiter** — `<<'EOF'` does not
protect it. A literal TAB shipped into a code span this way, invisibly, while an
adjacent `..\..\.ssh\id_rsa` survived by luck because `\.` and `\i` are not
recognised escapes. One correct example sat beside a corrupted one in the same
sentence. Use the Write/Edit tool, then verify the written bytes.

Verify with a Python `repr` of the line and an explicit backslash count, **not**
`cat -A`: on a CJK-heavy line `cat -A` renders as an unreadable wall of `M-`
escapes where a `^I` hides easily.

## Resuming interrupted work

**An interrupted worker can leave FABRICATED content, not merely missing
content.** When a rate limit killed four workers mid-edit, the partial
`docker.md` contained a code block with **no English counterpart** — invented,
not copied. The structural gate cannot catch that class: fabrication satisfies
heading counts perfectly, and here it failed only on the *missing* half.

So when resuming, never treat the partial file as a trustworthy base to top up.
Re-derive it against the English.

## Before you report done

```bash
python website/scripts/check-i18n-parity.py     # all four gates
cd website && npm run build                     # then READ THE LOG
```

The build **exits 0 with broken references** (`onBrokenLinks` is `warn`), so its
exit code proves nothing — that is what `check-build-links.py` is for. And the
static gates are necessary but *not sufficient*: they once all passed while 115
links were broken, because the content gate normalises the `/docs/` prefix away
and so cannot see it wrongly present. Build the site.
