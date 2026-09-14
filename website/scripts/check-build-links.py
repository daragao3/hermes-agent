#!/usr/bin/env python3
"""Fail a build whose log reports broken links, anchors or Markdown links.

WHY THIS EXISTS AND WHY IT PARSES A LOG INSTEAD OF CHECKING AN EXIT CODE:
``website/docusaurus.config.ts`` sets both ``onBrokenLinks`` and
``onBrokenMarkdownLinks`` to ``'warn'``. ``npm run build`` therefore EXITS 0
with hundreds of broken references in the output. Flipping those to ``'throw'``
would be the tidier fix, but it changes site-build behaviour for every
contributor; parsing the log gates the same defect without that blast radius.

This is the necessary complement to check-i18n-parity.py, not a duplicate of it.
The static gates deliberately normalise the ``/docs/`` prefix away (the site's
``routeBasePath`` is ``/``), so they are blind by construction to that prefix
being wrongly PRESENT -- which is exactly how a 115-link regression reached
``main`` past three green static gates and was caught only by the build.

Usage:
    npm run build 2>&1 | tee build.log     # in website/
    python3 website/scripts/check-build-links.py build.log
    ... | python3 website/scripts/check-build-links.py -
"""

import re
import sys

# Docusaurus banner lines. Matched case-insensitively against the whole log;
# each one is followed by an indented block naming the offending pages.
PATTERNS = [
    re.compile(r"Docusaurus found broken links", re.I),
    re.compile(r"Docusaurus found broken anchors", re.I),
    re.compile(r"Docusaurus found broken Markdown links", re.I),
    # Fallback for older/leaner phrasings that skip the banner.
    re.compile(r"Broken link on source page path", re.I),
]

CONTEXT_LINES = 40


def scan(text):
    lines = text.split("\n")
    hits = []
    for i, line in enumerate(lines):
        for pattern in PATTERNS:
            if pattern.search(line):
                hits.append((i, line, lines[i + 1: i + 1 + CONTEXT_LINES]))
                break
    return hits


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    if argv[1] == "-":
        text = sys.stdin.read()
    else:
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            text = fh.read()

    if not text.strip():
        # An empty log means the build never ran or its output was not
        # captured. Reporting "clean" here would be a false green of exactly
        # the kind this gate exists to prevent.
        print("check-build-links: the build log is EMPTY -- nothing was checked.")
        return 2

    hits = scan(text)
    if not hits:
        print("check-build-links: no broken links or anchors in the build log.")
        return 0

    print("check-build-links: the Docusaurus build reported broken references.")
    print("The build still EXITED 0 -- onBrokenLinks and onBrokenMarkdownLinks")
    print("are both 'warn', so its exit code proves nothing.")
    for lineno, line, context in hits:
        print("")
        print("--- log line %d ---" % (lineno + 1))
        print(line.rstrip())
        started = False
        for extra in context:
            if not extra.strip():
                # Docusaurus puts a blank line between the banner and the
                # detail block, so skip leading blanks and stop at the first
                # blank AFTER the detail has started.
                if started:
                    break
                continue
            started = True
            print(extra.rstrip())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
