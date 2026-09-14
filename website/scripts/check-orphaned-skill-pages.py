#!/usr/bin/env python3
"""Fail if a generated per-skill docs page outlived the skill it was generated from.

``generate-skill-docs.py`` writes one page per skill under
``website/docs/user-guide/skills/<source>/<category>/<slug>.md`` and never
prunes. Delete or move a skill and its page stays behind forever -- in BOTH
locales -- still building, still counted by the i18n parity gate, and still
reachable by direct URL after it drops out of ``sidebars.ts`` and the catalogs.

Nothing else catches this. ``docs-site-checks`` REGENERATES the pages before
building, so a stale page committed to the tree is simply carried along by the
build and never surfaces as a failure. This gate therefore has to run against
the tree AS COMMITTED, before any regeneration step -- exactly like
``check-i18n-parity.py``.

THE CHECK, which found both known orphans (``apple/macos-computer-use``, moved
to a top-level ``computer-use`` skill, and ``autonomous-ai-agents/kanban-codex-
lane``, whose source was removed in 38d3c49aaf) with zero false positives:
every generated page carries its own source path in the metadata table, as a
row whose value is a backticked ``skills/...`` or ``optional-skills/...``
path. Parse that path out and assert the skill still exists.

The row is matched on its VALUE, not its label: the zh-Hans twin translates
the label (``| Path |`` becomes ``| 路径 |``) but leaves the path itself
byte-identical, so one matcher covers both locales.

A page is treated as generated -- and therefore checked -- if it carries the
generator's ``auto-generated from the skill's SKILL.md`` marker. Hand-written
pages under the same tree (``google-workspace.md``) have no marker and are
skipped. A marked page whose Path row cannot be parsed is REPORTED, not
skipped: silently passing an unparseable page would make this gate fail
toward clean, which is the one direction a guard must never fail in.

Usage:
    python3 website/scripts/check-orphaned-skill-pages.py            # exit 1 on findings
    python3 website/scripts/check-orphaned-skill-pages.py --report-only
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SKILLS_PAGE_SUBPATH = Path("user-guide") / "skills"
LOCALE_DOC_ROOTS = [
    ("en", REPO_ROOT / "website" / "docs"),
    (
        "zh-Hans",
        REPO_ROOT
        / "website"
        / "i18n"
        / "zh-Hans"
        / "docusaurus-plugin-content-docs"
        / "current",
    ),
]

# Emitted verbatim by generate-skill-docs.py into every page it writes.
GENERATED_MARKER = "auto-generated from the skill's SKILL.md"

# `| <any label> | `skills/foo/bar` |` -- label is translated per locale, the
# backticked source path is not.
PATH_ROW_RE = re.compile(
    r"^\|[^|]+\|\s*`((?:skills|optional-skills)/[^`]+)`\s*\|\s*$",
    re.MULTILINE,
)


def find_orphans(doc_roots=None, repo_root: Path | None = None):
    """Return (findings, checked) where findings is a list of (page, reason).

    ``page`` is repo-relative and posix-formatted so the output reads the same
    on Windows and Linux.

    Both roots resolve at CALL time rather than as argument defaults, so a test
    can point the whole check at a scratch tree.
    """
    if doc_roots is None:
        doc_roots = LOCALE_DOC_ROOTS
    if repo_root is None:
        repo_root = REPO_ROOT
    findings: list[tuple[str, str]] = []
    checked = 0
    for _locale, doc_root in doc_roots:
        pages_dir = doc_root / SKILLS_PAGE_SUBPATH
        if not pages_dir.is_dir():
            continue
        for page in sorted(pages_dir.rglob("*.md")):
            text = page.read_text(encoding="utf-8")
            if GENERATED_MARKER not in text:
                continue  # hand-written page, not ours to gate
            checked += 1
            rel_page = page.relative_to(repo_root).as_posix()
            match = PATH_ROW_RE.search(text)
            if match is None:
                findings.append(
                    (
                        rel_page,
                        "generated page has no parseable source-path row "
                        "(expected a row whose value is `skills/...` or "
                        "`optional-skills/...`)",
                    )
                )
                continue
            source_rel = match.group(1)
            skill_md = repo_root / source_rel / "SKILL.md"
            if not skill_md.is_file():
                findings.append(
                    (rel_page, "source skill %s/SKILL.md no longer exists" % source_rel)
                )
    return findings, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print findings but exit 0 (for local inspection)",
    )
    args = parser.parse_args()

    findings, checked = find_orphans()

    print("generated skill pages checked ... %d" % checked)
    print("orphaned pages ................. %d" % len(findings))

    if findings:
        print("")
        for page, reason in findings:
            print("  %s" % page)
            print("      %s" % reason)
        print("")
        print("orphaned skill pages FAILED: %d finding(s)" % len(findings))
        print(
            "Fix by regenerating: python3 website/scripts/generate-skill-docs.py "
            "prunes pages whose skill is gone, in both locales."
        )
        return 0 if args.report_only else 1

    print("")
    print("no orphaned skill pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
