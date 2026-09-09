"""Gate 3 of 3 — in-page anchor resolution in the zh-Hans mirror.

Translating a heading changes the anchor Docusaurus generates for it, so an
in-page link like [x](#some-anchor) silently stops resolving. Keeping the link
target byte-identical to English is NECESSARY BUT NOT SUFFICIENT: the translated
heading must ALSO be pinned with an explicit {#english-anchor} id.

The 2026-09-08 sweep found 92 broken this way, most of them PRE-EXISTING rather
than introduced by the sweep. anchor_fix.py repairs them; this reports them.

SCOPE: in-page ](#fragment) links only. Cross-page ](other-page#fragment) links
break the same way and are NOT covered here -- that half is driven off the
Docusaurus build log by xpage_anchor_fix.py, because the build is the authority
on which of those actually fail.

SLUGGER NOTE: github-slugger does NOT collapse whitespace runs once punctuation
between two spaces is removed, so "Doubao / Volcengine" yields
"doubao--volcengine" with a DOUBLE hyphen. A naive slugifier that collapses runs
silently misses every double-hyphen anchor -- 8 of them on the first pass here.
Hence re.sub(r"\s", "-") and not r"\s+".

Usage:
    python anchor_audit.py [--root <repo>] <listfile>
Exit 0 = none unresolved, 1 = unresolved anchors found.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docroot import ZH_REL, bootstrap, require_pages, DocRootError  # noqa: E402


def slug(h):
    h = re.sub(r"\{#[^}]*\}", "", h).strip().lstrip("#").strip()
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = re.sub(r"`([^`]*)`", r"\1", h)
    h = h.lower()
    h = re.sub(r"[^\w一-鿿\s-]", "", h)
    return re.sub(r"\s", "-", h).strip("-")


def main(root, rels):
    total = 0
    for rel in rels:
        rel = rel.strip()
        p = os.path.join(root, ZH_REL, rel)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8").read()
        body = re.sub(r"```.*?```", "", txt, flags=re.S)
        defs = set(re.findall(r"\{#([^}]+)\}", body))
        for line in body.split("\n"):
            if line.startswith("#"):
                defs.add(slug(line))
        refs = set(re.findall(r"\]\(#([^)]+)\)", body))
        un = sorted(r for r in refs if r not in defs)
        if un:
            total += len(un)
            print("%3d unresolved  %s" % (len(un), rel))
            print("      " + ", ".join(un[:6]))
    print("TOTAL unresolved in-page anchors: %d" % total)
    return 1 if total else 0


if __name__ == "__main__":
    root, argv = bootstrap(sys.argv[1:])
    try:
        rels = require_pages(io.open(argv[0], encoding="utf-8").read().split("\n"))
    except (DocRootError, IndexError) as exc:
        sys.stderr.write("ERROR: %s\nusage: anchor_audit.py [--root R] <listfile>\n" % exc)
        raise SystemExit(2)
    print("root: %s" % root)
    raise SystemExit(main(root, rels))
