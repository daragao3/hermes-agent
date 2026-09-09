"""Gate 2 of 3 — CONTENT drift inside structurally-perfect zh-Hans pages.

Line-count delta is useless for this. Chinese renders the same content in fewer
lines, so a correctly-translated page routinely differs by dozens; during the
2026-09-08 sweep the naive "prose drift" bucket ROSE from 44 to 89 pages while
the tree was getting strictly better.

What IS comparable is the language-neutral material, which is never translated:
  - link targets            ](target)
  - inline code spans       `like_this`

A zh page missing those is missing actual CONTENT. This gate found 27 pages
carrying materially stale text inside pages that passed the structural gate both
before and after -- including inverted meaning, not just staleness: zh
msgraph-webhook.md said an unset client_state accepts all POSTs where English now
refuses to start.

Reports items present in English and absent from zh. Extras on the zh side are
ignored: translators legitimately add clarifying links.

Usage:
    python content_drift.py [--root <repo>] <listfile> [--min N]
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docroot import EN_REL, ZH_REL, bootstrap, require_pages, DocRootError  # noqa: E402

# Keep spans that look like code rather than prose.
CODEY = re.compile(r"^[\w./@:{}$~*-]+$")


def items(path):
    t = io.open(path, encoding="utf-8").read()
    links = set(re.findall(r"\]\(([^)\s]+)", t))
    # The zh locale deliberately strips the /docs prefix (routeBasePath is "/"),
    # so normalise it away rather than reporting every skill link as missing.
    #
    # ⚠ THIS NORMALISATION IS ALSO A BLIND SPOT, and it cost 115 broken links on
    # 2026-09-08. Because the prefix is erased on both sides, this gate cannot
    # see it being wrongly PRESENT in a zh page -- which is exactly the bug that
    # shipped, and which only `npm run build` caught. A gate that normalises a
    # difference away can never detect that difference. Run the build too.
    links = {re.sub(r"^/docs/", "/", l) for l in links}

    # Inline code, excluding fenced blocks.
    #
    # Pair backticks PER LINE by splitting, not by regex. A `...` regex with a
    # length bound silently mis-pairs on a line with an odd backtick count, and
    # whether it recovers depends on how long the intervening text happens to
    # be -- which made the verdict depend on CJK line density. Four spans that
    # were present and correct got reported missing purely because the Chinese
    # sentence fitted inside the bound where the English did not.
    #
    # KNOWN LIMITATION of per-line pairing, and the right trade: a code span
    # HARD-WRAPPED ACROSS A NEWLINE in the source splits into two bogus
    # half-spans. English wraps prose at ~80 cols and Chinese does not, so this
    # surfaces as a bare fragment reported missing -- e.g. `is` from
    # slack.md:449-450 and `hermes` from pipe-script-output.md:23-24. Both are
    # false positives; the zh pages carry the complete spans on one line.
    # Driving them to zero would mean FABRICATING a bare fragment in the
    # Chinese. Treat a suspiciously generic one-word miss as this artefact and
    # check the English for a wrap before acting on it.
    nofence = re.sub(r"```.*?```", "", t, flags=re.S)
    spans = set()
    for line in nofence.split("\n"):
        parts = line.split("`")
        for s in parts[1::2]:            # odd indices sit inside a backtick pair
            if 2 <= len(s) <= 60 and CODEY.match(s):
                spans.add(s)
    return links, spans


def main(root, rels, minmiss):
    rows = []
    for rel in rels:
        rel = rel.strip()
        ep = os.path.join(root, EN_REL, rel)
        zp = os.path.join(root, ZH_REL, rel)
        if not (os.path.exists(ep) and os.path.exists(zp)):
            continue
        el, es = items(ep)
        zl, zs = items(zp)
        ml, ms = el - zl, es - zs
        if len(ml) + len(ms) >= minmiss:
            rows.append((len(ml) + len(ms), rel, sorted(ml)[:6], sorted(ms)[:6]))
    rows.sort(reverse=True)
    for n, rel, ml, ms in rows:
        print("%3d missing  %s" % (n, rel))
        if ml:
            print("      links: " + ", ".join(ml))
        if ms:
            print("      code : " + ", ".join(ms))
    print("\n%d pages with >= %d language-neutral items missing from zh"
          % (len(rows), minmiss))
    return 0


if __name__ == "__main__":
    root, argv = bootstrap(sys.argv[1:])
    m = 4
    if "--min" in argv:
        i = argv.index("--min")
        m = int(argv[i + 1])
        del argv[i:i + 2]
    try:
        rels = require_pages(io.open(argv[0], encoding="utf-8").read().split("\n"))
    except (DocRootError, IndexError) as exc:
        sys.stderr.write("ERROR: %s\nusage: content_drift.py [--root R] <listfile> [--min N]\n" % exc)
        raise SystemExit(2)
    print("root: %s" % root)
    raise SystemExit(main(root, rels, m))
