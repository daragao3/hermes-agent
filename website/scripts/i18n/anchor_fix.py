"""Repair in-page anchors reported by anchor_audit.py.

Pins the translated zh heading with an explicit {#english-anchor} id so the
English link target keeps resolving.

SOUNDNESS CONDITION -- the whole reason this is safe to run in bulk: the pin is
placed by ORDINAL. For each unresolved ref it finds the ENGLISH heading whose
slug matches, takes that heading's position among English headings, and pins the
zh heading at the SAME position. That only holds when the page is at heading
parity, so pages that are not are SKIPPED and reported rather than guessed at.
Run verify_parity.py first; during the 2026-09-08 sweep zero pages were skipped.

Usage: python anchor_fix.py [--root <repo>] <listfile> [--apply]
Default is a dry run.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docroot import EN_REL, ZH_REL, bootstrap, require_pages, DocRootError  # noqa: E402
from anchor_audit import slug  # noqa: E402


def strip_fences(text):
    out, inf = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            inf = not inf
            out.append("")
            continue
        out.append("" if inf else line)
    return "\n".join(out)


def headings(text):
    """(line_index, line) for each heading outside fenced code."""
    return [(i, l) for i, l in enumerate(strip_fences(text).split("\n"))
            if l.startswith("#")]


def main(root, rels, apply):
    fixed = skipped = 0
    for rel in rels:
        rel = rel.strip()
        ep = os.path.join(root, EN_REL, rel)
        zp = os.path.join(root, ZH_REL, rel)
        if not (os.path.exists(ep) and os.path.exists(zp)):
            continue
        etxt = io.open(ep, encoding="utf-8").read()
        ztxt = io.open(zp, encoding="utf-8").read()
        eh, zh_ = headings(etxt), headings(ztxt)

        zbody = strip_fences(ztxt)
        refs = set(re.findall(r"\]\(#([^)]+)\)", zbody))
        defs = set(re.findall(r"\{#([^}]+)\}", zbody))
        for _, l in zh_:
            defs.add(slug(l))
        unresolved = sorted(r for r in refs if r not in defs)
        if not unresolved:
            continue

        if len(eh) != len(zh_):
            print("SKIP (heading count %d vs %d, not at parity)  %s"
                  % (len(eh), len(zh_), rel))
            skipped += len(unresolved)
            continue

        zlines = ztxt.split("\n")
        done = []
        for ref in unresolved:
            idx = next((k for k, (_, l) in enumerate(eh) if slug(l) == ref), None)
            if idx is None:
                print("   NO EN HEADING for #%s in %s (broken in English too)"
                      % (ref, rel))
                continue
            lineno, zline = zh_[idx]
            if "{#" in zline:
                continue
            zlines[lineno] = zline.rstrip() + " {#%s}" % ref
            done.append(ref)
        if done:
            print("%s %-58s %s"
                  % ("FIX " if apply else "WOULD", rel, ", ".join(done)))
            fixed += len(done)
            if apply:
                io.open(zp, "w", encoding="utf-8", newline="\n").write("\n".join(zlines))

    print("\n%s %d anchors; %d skipped (page not at heading parity)"
          % ("FIXED" if apply else "WOULD FIX", fixed, skipped))
    return 0


if __name__ == "__main__":
    root, argv = bootstrap(sys.argv[1:])
    apply = "--apply" in argv
    argv = [a for a in argv if a != "--apply"]
    try:
        rels = require_pages(io.open(argv[0], encoding="utf-8").read().split("\n"))
    except (DocRootError, IndexError) as exc:
        sys.stderr.write("ERROR: %s\nusage: anchor_fix.py [--root R] <listfile> [--apply]\n" % exc)
        raise SystemExit(2)
    print("root: %s" % root)
    raise SystemExit(main(root, rels, apply))
