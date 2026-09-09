"""Gate 1 of 3 — STRUCTURAL parity between website/docs and its zh-Hans mirror.

Asserts, per page, that the Chinese file matches English on:
  - heading count
  - fenced-code-block count
  - admonition-delimiter count (:::)
and that its TAB count does not EXCEED English's.

WHAT THIS CATCHES: a half-translated page, or one left wholly stale. During the
2026-09-08 sweep an API rate limit killed four translation workers mid-edit; of
86 touched files this gate flagged exactly the 2 that were partial and passed the
84 that were genuinely complete. A half-translated page is invisible to eye and
to diff review, and trivial to catch by counts.

WHAT IT IS BLIND TO, by construction -- run the other two gates as well:
  - stale CONTENT inside a structurally-perfect page  -> content_drift.py
  - links broken by translating their target heading  -> anchor_audit.py
  - FABRICATED content. Invented text satisfies heading counts perfectly. An
    interrupted worker once left a code block in docker.md with no English
    counterpart at all; this gate failed that page only on its missing half.

THE TAB RULE IS "NOT MORE THAN ENGLISH", NOT "ZERO". It originally demanded zero,
on the theory that a tab in a zh file is always heredoc corruption. It is not:
productivity-notion.md legitimately carries 4 tabs because its English source
does. The corruption case (tabs the English lacks) is still caught.

Usage:
    python verify_parity.py [--root <repo>] <rel> [<rel> ...]
    python verify_parity.py [--root <repo>] --file <listfile>
Exit 0 = all pass, 1 = at least one FAIL, 2 = could not resolve the repo root
or was given an empty page list.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docroot import EN_REL, ZH_REL, bootstrap, require_pages, DocRootError  # noqa: E402


def stats(path):
    L = io.open(path, encoding="utf-8").read().split("\n")
    return (
        len([l for l in L if l.startswith("#")]),
        sum(1 for l in L if l.startswith("```")),
        sum(1 for l in L if l.startswith(":::")),
        sum(1 for l in L if "\t" in l),
        len(L),
    )


def main(root, rels):
    fails = []
    for rel in rels:
        rel = rel.strip()
        ep = os.path.join(root, EN_REL, rel)
        zp = os.path.join(root, ZH_REL, rel)
        if not os.path.exists(ep):
            print("MISSING en  " + rel)
            fails.append(rel)
            continue
        if not os.path.exists(zp):
            print("MISSING zh  " + rel)
            fails.append(rel)
            continue
        e, z = stats(ep), stats(zp)
        ok = e[:3] == z[:3] and z[3] <= e[3]
        ratio = z[4] / e[4] if e[4] else 0
        # Line-ratio is ADVISORY ONLY and never fails the gate: Chinese renders
        # the same content in fewer lines, so a correct page routinely differs.
        flag = "" if 0.70 < ratio < 1.40 else "  <-- LINE RATIO %.2f (advisory)" % ratio
        if not ok:
            fails.append(rel)
        print("%s %-70s en%s zh%s%s"
              % ("OK  " if ok else "FAIL", rel, e[:4], z[:4], flag))
    print("\n%d checked, %d FAIL" % (len(rels), len(fails)))
    for f in fails:
        print("  FAIL: " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    root, argv = bootstrap(sys.argv[1:])
    try:
        if argv and argv[0] == "--file":
            rels = io.open(argv[1], encoding="utf-8").read().split("\n")
        else:
            rels = argv
        rels = require_pages(rels)
    except DocRootError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        raise SystemExit(2)
    print("root: %s" % root)
    raise SystemExit(main(root, rels))
