"""Tests for the zh-Hans docs parity gates.

``website/scripts/check-i18n-parity.py`` and ``check-build-links.py`` exist to
stop the Chinese locale drifting away from ``website/docs`` unnoticed, the way
it did over several months until the 2026-09-08 sweep. Each test below pins a
property that a plausible "simplification" of those scripts would break, and
that a green gate would then hide.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY = REPO_ROOT / "website" / "scripts" / "check-i18n-parity.py"
BUILD_LINKS = REPO_ROOT / "website" / "scripts" / "check-build-links.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def parity():
    return _load("check_i18n_parity", PARITY)


@pytest.fixture(scope="module")
def build_links():
    return _load("check_build_links", BUILD_LINKS)


@pytest.fixture
def tree(parity, tmp_path, monkeypatch):
    """Point the gate at a synthetic en/zh pair and return a writer for it."""
    en, zh = tmp_path / "en", tmp_path / "zh"
    en.mkdir()
    zh.mkdir()
    monkeypatch.setattr(parity, "EN_DIR", str(en))
    monkeypatch.setattr(parity, "ZH_DIR", str(zh))

    def write(rel, en_text, zh_text=None):
        for root, text in ((en, en_text), (zh, zh_text)):
            if text is None:
                continue
            target = Path(root) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    return write


# --------------------------------------------------------------------------
# slug — must match github-slugger, which Docusaurus generates anchors with
# --------------------------------------------------------------------------
def test_slug_does_not_collapse_whitespace_runs(parity):
    """Removing punctuation leaves the surrounding spaces, so the anchor for
    "Doubao / Volcengine" carries a DOUBLE hyphen. A slugifier that collapses
    the run produces ``doubao-volcengine``, which resolves against nothing —
    and the first anchor-repair pass silently missed all eight such anchors
    for exactly this reason."""
    assert parity.slug("## Doubao / Volcengine") == "doubao--volcengine"


def test_slug_strips_inline_code_and_links_but_keeps_cjk(parity):
    assert parity.slug("### The `hermes` command") == "the-hermes-command"
    assert parity.slug("## [Docs](https://x.example)") == "docs"
    assert parity.slug("## 配置文件") == "配置文件"


def test_slug_honours_an_explicit_id(parity):
    assert parity.slug("## 会话存储 {#session-storage}") == "会话存储"


# --------------------------------------------------------------------------
# gate 1 — page sets
# --------------------------------------------------------------------------
def test_missing_zh_page_is_a_finding(parity, tree, capsys):
    """A page-by-page gate cannot see an absent file, so the set comparison is
    the only thing standing between an untranslated page and a green run."""
    tree("a.md", "# A\n", "# A\n")
    tree("b.md", "# B\n", None)
    assert parity.main([]) == 1
    assert "untranslated" in capsys.readouterr().out


def test_orphan_zh_page_is_a_finding(parity, tree, capsys):
    tree("a.md", "# A\n", "# A\n")
    tree("gone.md", None, "# Gone\n")
    assert parity.main([]) == 1
    assert "orphaned" in capsys.readouterr().out


# --------------------------------------------------------------------------
# gate 2 — structure
# --------------------------------------------------------------------------
def test_structure_catches_a_half_translated_page(parity, tree):
    tree("a.md", "# A\n\n## One\n\n## Two\n", "# A\n\n## 一\n")
    assert parity.main([]) == 1


def test_structure_catches_an_unbalanced_admonition(parity, tree):
    tree("a.md", "# A\n\n:::tip\nx\n:::\n", "# A\n\n:::tip\nx\n")
    assert parity.main([]) == 1


def test_zh_tabs_are_allowed_only_up_to_the_english_count(parity, tree):
    """Tabs in a zh page usually mean heredoc corruption — but not when the
    English source has them too. Failing on any tab at all reported a clean
    page as broken, so the rule is 'must not EXCEED English'."""
    tree("a.md", "# A\n\tindented\n", "# A\n\tindented\n")
    assert parity.main([]) == 0
    tree("b.md", "# B\n", "# B\n\tsneaky\n")
    assert parity.main([]) == 1


# --------------------------------------------------------------------------
# gate 3 — language-neutral content drift
# --------------------------------------------------------------------------
def test_drift_catches_a_stale_page_that_structure_calls_perfect(parity, tree):
    """The whole point of this gate: identical heading/fence/admonition counts,
    yet the zh page has lost a config key the English documents."""
    tree(
        "a.md",
        "# A\n\nSet `gateway.timeout` and `gateway.retries`.\n",
        "# A\n\n设置 `gateway.timeout`。\n",
    )
    assert parity.main([]) == 1


def test_drift_ignores_the_docs_prefix(parity, tree):
    """``routeBasePath`` is "/", so the zh locale deliberately strips ``/docs/``
    from link targets. Comparing them raw reports every skill cross-link as
    missing."""
    tree("a.md", "# A\n\n[x](/docs/user-guide/foo)\n", "# A\n\n[x](/user-guide/foo)\n")
    assert parity.main([]) == 0


def test_drift_ignores_extra_links_on_the_zh_side(parity, tree):
    tree("a.md", "# A\n\n[x](/a)\n", "# A\n\n[x](/a) [y](/b)\n")
    assert parity.main([]) == 0


def test_drift_pairs_backticks_per_line(parity, tree):
    """A regex with a length bound mis-pairs on a line carrying an odd number
    of backticks, and whether it recovers depends on how long the intervening
    text is — which made the verdict depend on CJK line density and reported
    present-and-correct spans as missing. Splitting per line is pairing-exact."""
    en = "# A\n\nA line with `alpha` and a stray ` tick\nthen `beta` here.\n"
    zh = "# A\n\n一行 `alpha`\n然后 `beta`。\n"
    tree("a.md", en, zh)
    assert parity.main([]) == 0


def test_drift_allowlist_is_keyed_per_page(parity, tree):
    """The four tolerated spans are hard-wrapped in ONE specific English page
    each. The same span missing from a different page is real drift."""
    tree("other.md", "# O\n\nRun `PRAGMA` now.\n", "# O\n\n现在运行。\n")
    assert parity.main([]) == 1


def test_drift_allowlist_entries_point_at_real_pages(parity):
    """A tolerance whose path no longer exists is dead weight that silently
    stops covering anything — and three of the four paths were mis-recorded
    when this list was first written."""
    for rel, _span in parity.DRIFT_ALLOW:
        assert (Path(parity.EN_DIR) / rel).is_file(), rel
        assert (Path(parity.ZH_DIR) / rel).is_file(), rel


# --------------------------------------------------------------------------
# gate 4 — anchors
# --------------------------------------------------------------------------
def test_anchor_catches_a_link_broken_by_translating_its_heading(parity, tree):
    tree("a.md", "# A\n\n## Setup\n\n[go](#setup)\n", "# A\n\n## 安装\n\n[go](#setup)\n")
    assert parity.main([]) == 1


def test_an_explicit_id_keeps_a_translated_heading_addressable(parity, tree):
    tree(
        "a.md",
        "# A\n\n## Setup\n\n[go](#setup)\n",
        "# A\n\n## 安装 {#setup}\n\n[go](#setup)\n",
    )
    assert parity.main([]) == 0


def test_anchor_resolves_cross_page_targets_including_directory_indexes(parity, tree):
    tree("guide/index.md", "# G\n\n## Setup\n", "# G\n\n## 安装 {#setup}\n")
    tree("a.md", "# A\n\n[go](/guide#setup)\n", "# A\n\n[go](/guide#setup)\n")
    assert parity.main([]) == 0
    tree("guide/index.md", "# G\n\n## Setup\n", "# G\n\n## 安装\n")
    assert parity.main([]) == 1


def test_anchor_ignores_fragments_inside_fenced_code(parity, tree):
    body = "# A\n\n```\n[x](#not-a-real-heading)\n```\n"
    tree("a.md", body, body)
    assert parity.main([]) == 0


def test_anchor_stays_silent_on_an_unresolvable_page_target(parity, tree):
    """Whether the PAGE exists is the Docusaurus build's verdict, not this
    gate's. Guessing here would double-report every route the static resolver
    does not understand."""
    tree("a.md", "# A\n\n[go](/nowhere#frag)\n", "# A\n\n[go](/nowhere#frag)\n")
    assert parity.main([]) == 0


# --------------------------------------------------------------------------
# --allow-untranslated (the per-PR lane)
# --------------------------------------------------------------------------
def test_allow_untranslated_waives_only_the_page_set_gate(parity, tree, capsys):
    """generate-skill-docs.py emits English pages only, so a new skill would
    otherwise block its own PR on a translation its author cannot write."""
    tree("a.md", "# A\n", "# A\n")
    tree("new-skill.md", "# New\n", None)
    assert parity.main(["--allow-untranslated"]) == 0
    out = capsys.readouterr().out
    assert "untranslated" in out          # still reported
    assert "::warning::" in out           # and surfaced in the CI log
    assert "parity OK" not in out         # never claimed clean


def test_allow_untranslated_does_not_waive_a_translated_page_going_stale(
    parity, tree
):
    """The waiver is narrow on purpose: once a page HAS a translation, drift in
    it is the failure this gate exists for, flag or no flag."""
    tree("a.md", "# A\n\n## One\n\n## Two\n", "# A\n\n## 一\n")
    assert parity.main(["--allow-untranslated"]) == 1


# --------------------------------------------------------------------------
# report-only
# --------------------------------------------------------------------------
def test_report_only_still_prints_findings_but_exits_zero(parity, tree, capsys):
    tree("a.md", "# A\n\n## One\n", "# A\n")
    assert parity.main(["--report-only"]) == 0
    assert "FAILED" in capsys.readouterr().out


# --------------------------------------------------------------------------
# check-build-links — the complement the static gates cannot replace
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "banner",
    [
        "[WARNING] Docusaurus found broken links!",
        "[WARNING] Docusaurus found broken anchors!",
        "[WARNING] Docusaurus found broken Markdown links:",
        "Broken link on source page path = /zh-Hans/foo:",
    ],
)
def test_build_log_banners_are_all_detected(build_links, tmp_path, banner):
    log = tmp_path / "build.log"
    log.write_text("compiling\n%s\n\n   -> linking to /docs/x\n" % banner, encoding="utf-8")
    assert build_links.main(["prog", str(log)]) == 1


def test_a_clean_build_log_passes(build_links, tmp_path):
    log = tmp_path / "build.log"
    log.write_text("[SUCCESS] Generated static files in build.\n", encoding="utf-8")
    assert build_links.main(["prog", str(log)]) == 0


def test_an_empty_build_log_is_not_a_pass(build_links, tmp_path):
    """An empty log means the build never ran or its output was not captured.
    Calling that clean is the false green this gate exists to prevent."""
    log = tmp_path / "build.log"
    log.write_text("", encoding="utf-8")
    assert build_links.main(["prog", str(log)]) == 2


def test_the_detail_block_is_echoed_for_diagnosis(build_links, tmp_path, capsys):
    log = tmp_path / "build.log"
    log.write_text(
        "[WARNING] Docusaurus found broken links!\n"
        "\n"
        "- Broken link on source page path = /zh-Hans/user-guide/foo:\n"
        "   -> linking to /docs/user-guide/bar\n"
        "\n"
        "unrelated tail\n",
        encoding="utf-8",
    )
    assert build_links.main(["prog", str(log)]) == 1
    out = capsys.readouterr().out
    assert "/docs/user-guide/bar" in out
    assert "unrelated tail" not in out


# --------------------------------------------------------------------------
# fix-i18n-anchors — the repair companion to gate 4
# --------------------------------------------------------------------------
FIX_ANCHORS = REPO_ROOT / "website" / "scripts" / "fix-i18n-anchors.py"


@pytest.fixture(scope="module")
def fixer():
    return _load("fix_i18n_anchors", FIX_ANCHORS)


@pytest.fixture
def anchor_tree(fixer, tmp_path, monkeypatch):
    en, zh = tmp_path / "en", tmp_path / "zh"
    en.mkdir()
    zh.mkdir()
    monkeypatch.setattr(fixer, "EN_DIR", str(en))
    monkeypatch.setattr(fixer, "ZH_DIR", str(zh))

    def write(rel, en_text, zh_text):
        for root, text in ((en, en_text), (zh, zh_text)):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    return write, zh


def test_pin_places_the_english_anchor_by_ordinal(fixer, anchor_tree):
    write, zh = anchor_tree
    write(
        "a.md",
        "# A\n\n## Setup\n\n## Usage\n",
        "# A\n\n## 安装\n\n## 用法\n\n[go](#usage)\n",
    )
    assert fixer.main(["--apply"]) == 0
    body = (zh / "a.md").read_text(encoding="utf-8")
    # the SECOND heading is the one that gets pinned, not the first
    assert "## 用法 {#usage}" in body
    assert "{#usage}" not in body.split("## 用法")[0]


def test_pin_skips_a_page_that_is_not_at_heading_parity(fixer, anchor_tree, capsys):
    """Ordinal mapping is only sound under parity — on a drifted page the Nth
    zh heading is not the Nth English one, so pinning there would attach the
    anchor to the wrong section and look fixed."""
    write, zh = anchor_tree
    write("a.md", "# A\n\n## Setup\n\n## Usage\n", "# A\n\n## 安装\n\n[go](#usage)\n")
    before = (zh / "a.md").read_text(encoding="utf-8")
    assert fixer.main(["--apply"]) == 0
    assert (zh / "a.md").read_text(encoding="utf-8") == before
    assert "SKIP" in capsys.readouterr().out


def test_pin_refuses_a_fragment_with_no_english_heading(fixer, anchor_tree, capsys):
    """Broken in English too — inventing a target in the translation would
    hide the English bug behind a green gate."""
    write, zh = anchor_tree
    write("a.md", "# A\n\n## Setup\n", "# A\n\n## 安装\n\n[go](#nope)\n")
    assert fixer.main(["--apply"]) == 0
    assert "{#" not in (zh / "a.md").read_text(encoding="utf-8")
    assert "NO EN HEAD" in capsys.readouterr().out


def test_dry_run_writes_nothing(fixer, anchor_tree):
    write, zh = anchor_tree
    write("a.md", "# A\n\n## Setup\n", "# A\n\n## 安装\n\n[go](#setup)\n")
    before = (zh / "a.md").read_text(encoding="utf-8")
    assert fixer.main([]) == 0
    assert (zh / "a.md").read_text(encoding="utf-8") == before


def test_cross_page_mode_resolves_a_directory_index_route(fixer, anchor_tree, tmp_path):
    """A route like /guide comes from guide/index.md. Missing that form
    silently skipped every anchor into a directory-index page."""
    write, zh = anchor_tree
    write("guide/index.md", "# G\n\n## Setup\n", "# G\n\n## 安装\n")
    log = tmp_path / "build.log"
    log.write_text(
        "[WARNING] Docusaurus found broken anchors!\n"
        "   -> linking to /docs/zh-Hans/guide#setup\n",
        encoding="utf-8",
    )
    assert fixer.main(["--from-build-log", str(log), "--apply"]) == 0
    assert "## 安装 {#setup}" in (zh / "guide" / "index.md").read_text(encoding="utf-8")


def test_an_already_pinned_heading_is_left_alone(fixer, anchor_tree):
    write, zh = anchor_tree
    write("a.md", "# A\n\n## Setup\n", "# A\n\n## 安装 {#setup}\n\n[go](#setup)\n")
    assert fixer.main(["--apply"]) == 0
    body = (zh / "a.md").read_text(encoding="utf-8")
    assert body.count("{#setup}") == 1
