"""Repair CROSS-PAGE anchors, driven by the Docusaurus build log.

anchor_fix.py handles in-page links (](#x)). This handles the other half:
](other-page#fragment), where the fragment breaks because the TARGET page's
heading was translated. Docusaurus's own build output is the authority on which
of those actually fail, so this consumes the log rather than re-deriving it.

Produce the log first:
    cd website && npm ci && npm run build > build.log 2>&1

⚠ THE BUILD'S EXIT CODE MEANS NOTHING HERE. docusaurus.config.ts sets
onBrokenLinks: 'warn' AND onBrokenMarkdownLinks: 'warn', so the build exits 0
while reporting broken references -- the first build of the 2026-09-08 sweep
exited 0 with 228 of them. Read the log.

Same soundness condition as anchor_fix.py: the pin is placed by ORDINAL, valid
only at heading parity; pages that are not are skipped and reported.

Usage: python xpage_anchor_fix.py [--root <repo>] <build.log> [--apply]
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docroot import EN_REL, ZH_REL, bootstrap  # noqa: E402
from anchor_audit import slug  # noqa: E402
from anchor_fix import headings  # noqa: E402


def resolve(root, docpath):
    """Map a built doc route to its source file.

    A route like /developer-guide/plugins can come from plugins.md OR from
    plugins/index.md. Missing the index form silently skipped every anchor into
    a directory-index page on the first pass here, leaving 11 broken -- which
    reads as "mostly worked" rather than as an incomplete resolver. Trailing
    slashes appear in the log too.
    """
    docpath = docpath.rstrip("/")
    for cand in (docpath + ".md", docpath + ".mdx",
                 docpath + "/index.md", docpath + "/index.mdx"):
        if os.path.exists(os.path.join(root, ZH_REL, cand)):
            return cand
    return None


def main(root, logpath, apply):
    log = io.open(logpath, encoding="utf-8", errors="replace").read()
    blocks = log.split("[WARNING] Docusaurus found broken anchors!")
    if len(blocks) < 3:
        print("no zh-Hans broken-anchor block in that log "
              "(expected the SECOND such block; is this a both-locales build?)")
        return 0
    want = {}
    for m in re.finditer(r"-> linking to /docs/zh-Hans/([^\s#]+)#(\S+)", blocks[2]):
        want.setdefault(m.group(1), set()).add(m.group(2))

    fixed = skipped = nomatch = 0
    for docpath, frags in sorted(want.items()):
        rel = resolve(root, docpath)
        if not rel:
            print("NO SOURCE  %s" % docpath)
            continue
        zp, ep = os.path.join(root, ZH_REL, rel), os.path.join(root, EN_REL, rel)
        if not os.path.exists(ep):
            print("NO EN      %s" % rel)
            continue
        ztxt = io.open(zp, encoding="utf-8").read()
        etxt = io.open(ep, encoding="utf-8").read()
        eh, zh_ = headings(etxt), headings(ztxt)
        if len(eh) != len(zh_):
            print("SKIP parity %d vs %d  %s" % (len(eh), len(zh_), rel))
            skipped += len(frags)
            continue
        zlines = ztxt.split("\n")
        done = []
        for frag in sorted(frags):
            idx = next((k for k, (_, l) in enumerate(eh) if slug(l) == frag), None)
            if idx is None:
                print("   NO EN HEADING for #%s in %s (broken in English too)" % (frag, rel))
                nomatch += 1
                continue
            lineno, zline = zh_[idx]
            if "{#" in zline:
                continue
            zlines[lineno] = zline.rstrip() + " {#%s}" % frag
            done.append(frag)
        if done:
            print("%s %-58s %s" % ("FIX " if apply else "WOULD", rel, ", ".join(done)))
            fixed += len(done)
            if apply:
                io.open(zp, "w", encoding="utf-8", newline="\n").write("\n".join(zlines))
    print("\n%s %d cross-page anchors; %d skipped (no heading parity); "
          "%d had no matching English heading (broken in English too)"
          % ("FIXED" if apply else "WOULD FIX", fixed, skipped, nomatch))
    return 0


if __name__ == "__main__":
    root, argv = bootstrap(sys.argv[1:])
    apply = "--apply" in argv
    argv = [a for a in argv if a != "--apply"]
    if not argv:
        sys.stderr.write("usage: xpage_anchor_fix.py [--root R] <build.log> [--apply]\n")
        raise SystemExit(2)
    print("root: %s" % root)
    raise SystemExit(main(root, argv[0], apply))
