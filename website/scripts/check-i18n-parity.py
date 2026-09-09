#!/usr/bin/env python3
"""Gate the zh-Hans docs locale against ``website/docs`` so it cannot drift silently.

Four independent gates, each catching a failure class the others are blind to.
Run them all; a page can pass three and fail the fourth.

1. PAGE SET      -- every English page has a zh counterpart (and vice versa).
                    A missing zh file is drift, and no per-page gate can see it.
2. STRUCTURE     -- heading / fenced-code / admonition-delimiter counts must
                    match English exactly, and the zh tab count must not EXCEED
                    English's. Catches a half-translated or wholly-stale page.
                    Blind to stale content inside a structurally-parallel page,
                    and blind to fabricated content (an interrupted translation
                    worker can invent a code block that satisfies every count).
3. CONTENT DRIFT -- language-NEUTRAL items only: link targets and inline code
                    spans, neither of which is ever translated. Catches stale
                    prose, table rows and config keys hiding inside a page that
                    gate 2 calls perfect.
4. ANCHORS       -- in-page and cross-page ``#fragment`` resolution against the
                    zh headings. Catches links silently broken by translating
                    the heading they point at.

Deliberately NOT gated on, because both are actively misleading here:

  * commit counts / sha-set difference. A translation lands in its own commit,
    so the English shas never appear in the zh file's history and the metric can
    never reach zero. It reported zh security.md "9 commits behind" immediately
    after that page was verified line-for-line at parity.
  * line-count delta. Chinese renders the same content in fewer lines, so the
    delta grows as pages are corrected -- the "prose drift" bucket ROSE from 44
    to 89 pages during the sweep that took structural drift from 97 to 0.

These static gates are NECESSARY BUT NOT SUFFICIENT. They missed a 115-link
regression that only ``npm run build`` caught, because gate 3 normalises the
``/docs/`` prefix away (routeBasePath is "/") and is therefore blind to that
prefix being wrongly PRESENT. Pair this with check-build-links.py.

Usage:
    python3 website/scripts/check-i18n-parity.py            # gate: exit 1 on findings
    python3 website/scripts/check-i18n-parity.py --report-only
    python3 website/scripts/check-i18n-parity.py --drift-min 4
"""

import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EN_DIR = os.path.join(REPO_ROOT, "website", "docs")
ZH_DIR = os.path.join(
    REPO_ROOT, "website", "i18n", "zh-Hans", "docusaurus-plugin-content-docs", "current"
)

# ---------------------------------------------------------------------------
# content-drift allowlist
#
# Four PERMANENT false positives, each verified against the English source. Each
# is an inline code span HARD-WRAPPED ACROSS A NEWLINE in the English, which
# per-line backtick pairing splits into two bogus half-spans; the zh pages carry
# the complete span on one line. Driving these to zero would mean fabricating a
# bare `is` / `hermes` span in the Chinese, which would be wrong. Keyed by
# (page, span) so the tolerance stays narrow -- a genuinely missing `is` on some
# other page still fails.
# ---------------------------------------------------------------------------
DRIFT_ALLOW = {
    ("user-guide/messaging/slack.md", "is"),            # en 449-450: `is\nrunning ...`
    ("guides/pipe-script-output.md", "hermes"),         # en 23-24:  `hermes\ngateway`
    ("user-guide/profiles.md", "terminal.home_mode:"),  # en 293-294
    ("developer-guide/session-storage.md", "PRAGMA"),   # en 160-161
}

CODEY = re.compile(r"^[\w./@:{}$~*-]+$")

# github-slugger keeps word chars, CJK, whitespace and hyphens; drops the rest.
SLUG_DROP = re.compile("[^\\w一-鿿\\s-]")


def rel_pages(root):
    out = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".md") or name.endswith(".mdx"):
                full = os.path.join(dirpath, name)
                out.add(os.path.relpath(full, root).replace(os.sep, "/"))
    return out


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def slug(heading):
    """Match github-slugger, which is what Docusaurus generates anchors with.

    NOTE the whitespace handling: the slugger removes punctuation but does NOT
    collapse the whitespace run left behind, so "Doubao / Volcengine" yields
    "doubao--volcengine" with a DOUBLE hyphen. A naive collapse silently misses
    every such anchor.
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


# --------------------------------------------------------------------- gate 2
def structure(text):
    lines = text.split("\n")
    return (
        sum(1 for line in lines if line.startswith("#")),
        sum(1 for line in lines if line.startswith("```")),
        sum(1 for line in lines if line.startswith(":::")),
        sum(1 for line in lines if "\t" in line),
    )


def gate_structure(paired, findings):
    bad = 0
    for rel in paired:
        en = structure(read(os.path.join(EN_DIR, rel)))
        zh = structure(read(os.path.join(ZH_DIR, rel)))
        if en[:3] != zh[:3] or zh[3] > en[3]:
            bad += 1
            findings.append(
                "structure     %s  en(head=%d fence=%d adm=%d tab=%d) "
                "zh(head=%d fence=%d adm=%d tab=%d)" % ((rel,) + en + zh)
            )
    return bad


# --------------------------------------------------------------------- gate 3
def neutral_items(text):
    links = set(re.findall(r"\]\(([^)\s]+)", text))
    # the zh locale deliberately strips the /docs prefix (routeBasePath is "/"),
    # so normalise it away rather than reporting every skill link as missing
    links = {re.sub(r"^/docs/", "/", link) for link in links}
    nofence = re.sub(r"```.*?```", "", text, flags=re.S)
    spans = set()
    for line in nofence.split("\n"):
        # Pair backticks PER LINE by splitting rather than by regex. A `...`
        # regex with a length bound mis-pairs on a line with an odd backtick
        # count and then recovers or not depending on how long the intervening
        # text happens to be -- which made the verdict depend on CJK line
        # density and reported present-and-correct spans as missing.
        for span in line.split("`")[1::2]:
            if 2 <= len(span) <= 60 and CODEY.match(span):
                spans.add(span)
    return links, spans


def gate_drift(paired, minimum, findings):
    bad = 0
    for rel in paired:
        en_links, en_spans = neutral_items(read(os.path.join(EN_DIR, rel)))
        zh_links, zh_spans = neutral_items(read(os.path.join(ZH_DIR, rel)))
        missing_links = sorted(en_links - zh_links)
        missing_spans = sorted(
            s for s in en_spans - zh_spans if (rel, s) not in DRIFT_ALLOW
        )
        # extras on the zh side are fine -- translators legitimately add links
        total = len(missing_links) + len(missing_spans)
        if total >= minimum:
            bad += 1
            findings.append(
                "drift         %s  %d language-neutral item(s) missing" % (rel, total)
            )
            if missing_links:
                findings.append("                links: " + ", ".join(missing_links[:8]))
            if missing_spans:
                findings.append("                code : " + ", ".join(missing_spans[:8]))
    return bad


# --------------------------------------------------------------------- gate 4
def anchor_defs(text):
    body = strip_fences(text)
    defs = set(re.findall(r"\{#([^}]+)\}", body))
    for line in body.split("\n"):
        if line.startswith("#"):
            defs.add(slug(line))
    return defs


def resolve_zh(rel_from, target):
    """Map a doc-relative link target to a zh source file, or None."""
    target = target.split("?")[0].rstrip("/")
    if target.startswith("/"):
        base = target.lstrip("/")
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(rel_from), target))
        base = base.replace(os.sep, "/")
    base = re.sub(r"^docs/", "", base)
    for cand in (base, base + ".md", base + ".mdx",
                 base + "/index.md", base + "/index.mdx"):
        # isfile, not exists: a route like developer-guide/plugins names a real
        # DIRECTORY here, and opening it raises rather than resolving to its
        # index page.
        if cand and os.path.isfile(os.path.join(ZH_DIR, cand)):
            return cand
    return None


def gate_anchors(zh_pages, findings):
    defs_cache = {}

    def defs_for(rel):
        if rel not in defs_cache:
            defs_cache[rel] = anchor_defs(read(os.path.join(ZH_DIR, rel)))
        return defs_cache[rel]

    bad = 0
    for rel in zh_pages:
        body = strip_fences(read(os.path.join(ZH_DIR, rel)))
        unresolved = []
        for target in re.findall(r"\]\(([^)\s]+)\)", body):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            page, sep, frag = target.partition("#")
            if not sep or not frag:
                continue
            if page == "":
                if frag not in defs_for(rel):
                    unresolved.append("#" + frag)
                continue
            other = resolve_zh(rel, page)
            # An unresolvable PAGE target is the Docusaurus build's business,
            # not ours -- only judge the fragment when we know the target file.
            if other and frag not in defs_for(other):
                unresolved.append(page + "#" + frag)
        if unresolved:
            bad += 1
            findings.append(
                "anchor        %s  %d unresolved: %s"
                % (rel, len(unresolved), ", ".join(sorted(set(unresolved))[:8]))
            )
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check zh-Hans docs parity against website/docs."
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print findings but always exit 0 (for an advisory nightly run)",
    )
    parser.add_argument(
        "--allow-untranslated",
        action="store_true",
        help="still REPORT pages with no zh counterpart, but do not fail on them. "
        "For the per-PR lane: generate-skill-docs.py emits English pages only, so "
        "adding a skill would otherwise block that PR on a translation its author "
        "cannot write. Gates 2-4 stay blocking there because they only ever fire "
        "on a page someone already translated. The nightly run drops this flag, so "
        "an untranslated page is still caught within a day.",
    )
    parser.add_argument(
        "--drift-min",
        type=int,
        default=1,
        help="report a page missing at least N language-neutral items (default 1)",
    )
    args = parser.parse_args(argv)

    en_pages, zh_pages = rel_pages(EN_DIR), rel_pages(ZH_DIR)
    paired = sorted(en_pages & zh_pages)
    findings = []

    untranslated = sorted(en_pages - zh_pages)
    orphaned = sorted(zh_pages - en_pages)
    for rel in untranslated:
        findings.append("untranslated  no zh counterpart for website/docs/%s" % rel)
    for rel in orphaned:
        findings.append("orphaned      zh page has no English counterpart: %s" % rel)

    n_struct = gate_structure(paired, findings)
    n_drift = gate_drift(paired, args.drift_min, findings)
    n_anchor = gate_anchors(sorted(zh_pages), findings)

    for line in findings:
        print(line)

    print("")
    print("en pages ................ %d" % len(en_pages))
    print("zh pages ................ %d" % len(zh_pages))
    print("paired .................. %d" % len(paired))
    print("untranslated ............ %d" % len(untranslated))
    print("orphaned zh ............. %d" % len(orphaned))
    print("structurally drifted .... %d" % n_struct)
    print("content-drifted (>=%d) ... %d" % (args.drift_min, n_drift))
    print("pages w/ broken anchors . %d" % n_anchor)

    n_pageset = len(untranslated) + len(orphaned)
    total = n_pageset + n_struct + n_drift + n_anchor
    waived = 0
    if n_pageset and args.allow_untranslated:
        print("")
        print(
            "::warning::%d zh-Hans page-set finding(s) — reported, not failed on "
            "(--allow-untranslated). The nightly run does fail on these." % n_pageset
        )
        waived = n_pageset
        total -= n_pageset
    if total:
        print("")
        print("zh-Hans parity FAILED: %d finding(s)" % total)
        print(
            "These gates are static -- they cannot see a wrongly-present "
            "/docs/ prefix. Run check-build-links.py too."
        )
        return 0 if args.report_only else 1
    print("")
    if waived:
        # Not "OK" -- there ARE findings, this lane just does not fail on them.
        print("zh-Hans parity: no blocking findings (%d waived)" % waived)
    else:
        print("zh-Hans parity OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
