#!/usr/bin/env python3
"""Repair zh-Hans anchors that translating a heading silently broke.

The companion to gate 4 of check-i18n-parity.py. Translating "## Setup" to
"## 安装" changes the anchor Docusaurus generates, so every ``](#setup)`` in the
locale stops resolving — with no error anywhere, because ``onBrokenAnchors`` is
a warning. The fix is to pin the translated heading with the English anchor as
an explicit ``{#setup}`` id, which is already the convention on the pages that
were translated carefully.

SOUNDNESS CONDITION, and it is why this is safe to run in bulk: the pin is
placed by ORDINAL. For each unresolved fragment we find the English heading
whose slug matches, take its position among the English headings, and pin the zh
heading at the SAME position. That mapping is only valid while the page is at
heading-for-heading parity with English, so pages that are not are SKIPPED and
reported rather than guessed at. Run check-i18n-parity.py first; if gate 2 is
clean, nothing gets skipped.

Two modes, because the two halves have different authorities:

  in-page (default)   ``](#fragment)`` — resolvable statically against the zh
                      page's own headings, so no build is needed.
  cross-page          ``](other-page#fragment)`` — the Docusaurus build log is
                      the authority on which of these are broken, so this mode
                      consumes a log rather than re-deriving link resolution.

Usage:
    python3 website/scripts/fix-i18n-anchors.py                     # dry run
    python3 website/scripts/fix-i18n-anchors.py --apply
    python3 website/scripts/fix-i18n-anchors.py --from-build-log build.log --apply
"""

import argparse
import io
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EN_DIR = os.path.join(REPO_ROOT, "website", "docs")
ZH_DIR = os.path.join(
    REPO_ROOT, "website", "i18n", "zh-Hans", "docusaurus-plugin-content-docs", "current"
)

SLUG_DROP = re.compile("[^\\w一-鿿\\s-]")


def slug(heading):
    """github-slugger, including its NON-collapse of whitespace runs.

    "Doubao / Volcengine" slugs to "doubao--volcengine" with a double hyphen.
    A slugifier that collapses the run misses every such anchor, which is how
    the first repair pass left eight of them broken.
    """
    h = re.sub(r"\{#[^}]*\}", "", heading).strip().lstrip("#").strip()
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = re.sub(r"`([^`]*)`", r"\1", h)
    h = h.lower()
    h = SLUG_DROP.sub("", h)
    return re.sub(r"\s", "-", h).strip("-")


def strip_fences(text):
    out, in_fence = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def headings(text):
    """(line index, line) per heading, ignoring headings inside code fences."""
    return [
        (i, line)
        for i, line in enumerate(strip_fences(text).split("\n"))
        if line.startswith("#")
    ]


def read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, lines):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


def zh_pages():
    out = []
    for dirpath, _dirs, files in os.walk(ZH_DIR):
        for name in sorted(files):
            if name.endswith(".md") or name.endswith(".mdx"):
                full = os.path.join(dirpath, name)
                out.append(os.path.relpath(full, ZH_DIR).replace(os.sep, "/"))
    return sorted(out)


def pin(rel, fragments, apply_changes, report):
    """Pin ``fragments`` onto the zh page ``rel`` by English heading ordinal."""
    en_path, zh_path = os.path.join(EN_DIR, rel), os.path.join(ZH_DIR, rel)
    if not (os.path.isfile(en_path) and os.path.isfile(zh_path)):
        report.append("NO PAIR      %s" % rel)
        return 0, len(fragments)
    en_text, zh_text = read(en_path), read(zh_path)
    en_heads, zh_heads = headings(en_text), headings(zh_text)
    if len(en_heads) != len(zh_heads):
        report.append(
            "SKIP         %s (headings %d vs %d — not at parity, ordinal mapping "
            "would be a guess)" % (rel, len(en_heads), len(zh_heads))
        )
        return 0, len(fragments)

    lines = zh_text.split("\n")
    pinned = []
    unfixable = 0
    for frag in sorted(fragments):
        idx = next(
            (k for k, (_, line) in enumerate(en_heads) if slug(line) == frag), None
        )
        if idx is None:
            # No English heading matches either — the reference is broken in
            # English too, so pinning would invent a target.
            report.append("NO EN HEAD   %s  #%s" % (rel, frag))
            unfixable += 1
            continue
        lineno, zh_line = zh_heads[idx]
        if "{#" in zh_line:
            continue
        lines[lineno] = zh_line.rstrip() + " {#%s}" % frag
        pinned.append(frag)

    if pinned:
        report.append(
            "%s  %-58s  %s" % ("PIN  " if apply_changes else "WOULD", rel, ", ".join(pinned))
        )
        if apply_changes:
            write(zh_path, lines)
    return len(pinned), unfixable


def collect_in_page():
    """{rel: {fragment, ...}} for in-page refs that resolve against nothing."""
    wanted = {}
    for rel in zh_pages():
        body = strip_fences(read(os.path.join(ZH_DIR, rel)))
        defs = set(re.findall(r"\{#([^}]+)\}", body))
        for line in body.split("\n"):
            if line.startswith("#"):
                defs.add(slug(line))
        refs = set(re.findall(r"\]\(#([^)]+)\)", body))
        unresolved = refs - defs
        if unresolved:
            wanted[rel] = unresolved
    return wanted


def resolve_route(docpath):
    """Map a built route to its zh source file.

    A route like ``developer-guide/plugins`` can come from ``plugins.md`` OR
    from ``plugins/index.md``. Missing the index form silently skips every
    anchor into a directory-index page, which is how the first pass left 11
    broken anchors behind.
    """
    docpath = docpath.rstrip("/")
    for cand in (
        docpath + ".md",
        docpath + ".mdx",
        docpath + "/index.md",
        docpath + "/index.mdx",
    ):
        if os.path.isfile(os.path.join(ZH_DIR, cand)):
            return cand
    return None


def collect_cross_page(logpath):
    """{rel: {fragment, ...}} from the zh-Hans broken-anchor block of a build log."""
    log = io.open(logpath, encoding="utf-8", errors="replace").read()
    wanted = {}
    for match in re.finditer(r"-> linking to /docs/zh-Hans/([^\s#]+)#(\S+)", log):
        route, frag = match.group(1), match.group(2).rstrip(").,")
        rel = resolve_route(route)
        if rel is None:
            print("NO SOURCE    %s" % route)
            continue
        wanted.setdefault(rel, set()).add(frag)
    return wanted


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Pin {#english-anchor} ids on translated zh-Hans headings."
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the changes (default is a dry run)"
    )
    parser.add_argument(
        "--from-build-log",
        metavar="LOG",
        help="repair CROSS-PAGE anchors named in a Docusaurus build log instead "
        "of in-page ones",
    )
    args = parser.parse_args(argv)

    if args.from_build_log:
        wanted = collect_cross_page(args.from_build_log)
    else:
        wanted = collect_in_page()

    report = []
    pinned = unfixable = 0
    for rel in sorted(wanted):
        got, bad = pin(rel, wanted[rel], args.apply, report)
        pinned += got
        unfixable += bad

    for line in report:
        print(line)
    print("")
    print(
        "%s %d anchor(s) across %d page(s); %d had no matching English heading "
        "(broken in English too — fix the English page, not the translation)"
        % ("PINNED" if args.apply else "WOULD PIN", pinned, len(wanted), unfixable)
    )
    if not args.apply and pinned:
        print("Dry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
