# Website

This website is built using [Docusaurus](https://docusaurus.io/), a modern static website generator.

## Installation

```bash
yarn
```

## Local Development

```bash
yarn start
```

This command starts a local development server and opens up a browser window. Most changes are reflected live without having to restart the server.

## Build

```bash
yarn build
```

This command generates static content into the `build` directory and can be served using any static contents hosting service.

## Deployment

Using SSH:

```bash
USE_SSH=true yarn deploy
```

Not using SSH:

```bash
GIT_USER=<Your GitHub username> yarn deploy
```

If you are using GitHub pages for hosting, this command is a convenient way to build the website and push to the `gh-pages` branch.

## Diagram Linting

CI runs `ascii-guard` to lint docs for ASCII box diagrams. Use Mermaid (````mermaid`) or plain lists/tables instead of ASCII boxes to avoid CI failures.

## Chinese (zh-Hans) Docs Parity

`website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/` mirrors
`website/docs/` page for page. It drifted for months without anyone noticing —
42 untranslated pages, 97 structurally-drifted ones, 92 broken anchors — because
nothing measured it. Three checks now do, and CI runs all of them:

```bash
python3 website/scripts/check-i18n-parity.py       # page set, structure, content, anchors
python3 website/scripts/fix-i18n-anchors.py        # dry run; --apply to repair anchors

cd website && npm run build 2>&1 | tee build.log
python3 scripts/check-build-links.py build.log
```

`check-i18n-parity.py` runs per PR (`docs-site-checks.yml`) and blocks, except on
pages that have no translation at all — `generate-skill-docs.py` emits English
pages only, so adding a skill would otherwise block its own PR on a translation
its author cannot write. Those are printed as warnings there
(`--allow-untranslated`) and *do* fail the nightly. The build-log check runs in
the same workflow. `i18n-parity-nightly.yml` re-derives everything against `main`
daily as a backstop.

Two things worth knowing before you trust or change these:

- **The build's exit code proves nothing about links.** `onBrokenLinks` and
  `onBrokenMarkdownLinks` are both `'warn'`, so `npm run build` exits 0 with
  broken references. That is why `check-build-links.py` parses the log.
- **Do not add a commit-count or line-count check.** A translation lands in its
  own commit, so sha-set difference never reaches zero; and Chinese renders the
  same content in fewer lines, so the line delta grows as pages are *corrected*.
  Both metrics were tried and both are noise. The gates compare structure and
  language-neutral content instead.
