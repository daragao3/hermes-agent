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


# Every real page in website/docs carries frontmatter, and since gate 6 a page
# without a title and description is itself a finding. So the fixture writes a
# COMPLETE page by default: a test about drift or anchors should not have to
# restate metadata it is not exercising, and should not trip a gate it is not
# about. Pass ``bare=True`` for the handful of tests whose subject IS a page
# with absent or partial frontmatter -- there the omission is the fixture.
STUB_FRONTMATTER = '---\ntitle: "T"\ndescription: "D"\n---\n\n'


@pytest.fixture
def tree(parity, tmp_path, monkeypatch):
    """Point the gate at a synthetic en/zh pair and return a writer for it.

    Text that does not already open a frontmatter block is given
    STUB_FRONTMATTER, identically in both locales, so gates 2-3 stay balanced.
    """
    en, zh = tmp_path / "en", tmp_path / "zh"
    en.mkdir()
    zh.mkdir()
    monkeypatch.setattr(parity, "EN_DIR", str(en))
    monkeypatch.setattr(parity, "ZH_DIR", str(zh))

    def write(rel, en_text, zh_text=None, bare=False):
        for root, text in ((en, en_text), (zh, zh_text)):
            if text is None:
                continue
            if not bare and not text.startswith("---"):
                text = STUB_FRONTMATTER + text
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


# --------------------------------------------------------------------------
# gate 5 — zh descriptions must not carry an ellipsis they did not earn
#
# generate-skill-docs.py clips an English description at 160 chars and marks
# the cut with an ellipsis. A translator working from that clipped string
# carries the ellipsis into Chinese, which needs far fewer characters and
# usually fits whole. Two of the first five translated skill pages had it, and
# gates 1-4 are all blind to it because none of them reads frontmatter text.
# --------------------------------------------------------------------------
def _page(desc, body="# T\n\ntext\n"):
    return '---\ntitle: "T"\ndescription: "%s"\n---\n\n%s' % (desc, body)


def test_description_flags_an_ellipsis_the_english_never_had(parity, tree):
    """The English was never clipped, so there is nothing for the zh to elide."""
    tree("a.md", _page("Complete English sentence"), _page("完整的中文句子……"))
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 1
    assert "nothing is elided" in findings[0]


def test_description_flags_an_elision_far_under_budget(parity, tree):
    """Both sides elided, but 20 of 160 chars means the whole sentence fitted."""
    tree("a.md", _page("English clipped at the cap..."), _page("中文很短……"))
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 1
    assert "under budget" in findings[0]


def test_description_accepts_a_genuine_elision_near_the_budget(parity, tree):
    """A translator actually up against the 160-char cap keeps their ellipsis."""
    long_zh = "中" * (parity.DESC_MIN_ELIDED + 5) + "..."
    tree("a.md", _page("English clipped at the cap..."), _page(long_zh))
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 0
    assert findings == []


def test_description_ignores_pages_with_no_ellipsis(parity, tree):
    tree("a.md", _page("English"), _page("中文"))
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 0


@pytest.mark.parametrize("mark", ["...", "…", "……"])
def test_description_detects_ascii_and_cjk_ellipses(parity, tree, mark):
    """The zh locale uses BOTH. An ASCII-only grep missed the `……` on
    devops-hermes-s6-container-supervision.md, which is exactly how that page
    survived a hand sweep of this same defect."""
    tree("a.md", _page("Complete English sentence"), _page("中文" + mark))
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 1


def test_description_tolerates_a_page_with_no_frontmatter(parity, tree):
    """Several hand-written pages have none; the gate must not crash on them."""
    tree("a.md", "# Just a heading\n", "# 只是一个标题\n", bare=True)
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 0


def test_description_reads_single_quoted_frontmatter(parity, tree):
    tree(
        "a.md",
        "---\ndescription: 'Complete English sentence'\n---\n\n# T\n",
        "---\ndescription: '完整的中文句子……'\n---\n\n# T\n",
    )
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 1


def test_description_does_not_read_a_body_line_as_frontmatter(parity, tree):
    """`description:` in the BODY is prose, not metadata -- reading it would
    invent findings on pages that have no frontmatter at all."""
    tree(
        "a.md",
        "# T\n\ndescription: English...\n",
        "# T\n\ndescription: 中文……\n",
        bare=True,
    )
    findings = []
    assert parity.gate_descriptions(["a.md"], findings) == 0


def test_description_failure_counts_toward_the_exit_code(parity, tree, capsys):
    """A gate nobody fails on is theatre -- pin it to the process exit code."""
    tree("a.md", _page("Complete English sentence"), _page("完整的中文句子……"))
    assert parity.main([]) == 1
    out = capsys.readouterr().out
    assert "bad zh descriptions ..... 1" in out


def test_allow_untranslated_does_not_waive_a_bad_description(parity, tree, capsys):
    """--allow-untranslated exists for pages nobody has translated yet. This
    fires only on a page someone DID translate, so the PR lane must still
    fail on it."""
    tree("a.md", _page("Complete English sentence"), _page("完整的中文句子……"))
    assert parity.main(["--allow-untranslated"]) == 1


# --------------------------------------------------------------------------
# gate 6 — frontmatter completeness
#
# A PARTIAL frontmatter block passes gates 1-5: gate 1 tests existence, 2-4 test
# the body, and gate 5 only inspects a description it has already found. Six
# pages in user-guide/messaging carried exactly that defect until 2026-09-09 and
# were found by hand, not by any gate.
# --------------------------------------------------------------------------
FULL = '---\ntitle: "T"\ndescription: "D"\n---\n\n# T\n\ntext\n'


def test_frontmatter_flags_a_missing_description(parity, tree):
    tree("a.md", '---\ntitle: "T"\n---\n\n# T\n\ntext\n', FULL)
    findings = []
    assert parity.gate_frontmatter({"a.md"}, {"a.md"}, findings) == 1
    assert "no description:" in findings[0]


def test_frontmatter_flags_a_missing_title(parity, tree):
    tree("a.md", '---\ndescription: "D"\n---\n\n# T\n\ntext\n', FULL)
    findings = []
    assert parity.gate_frontmatter({"a.md"}, {"a.md"}, findings) == 1
    assert "no title:" in findings[0]


def test_frontmatter_flags_a_page_with_no_frontmatter_at_all(parity, tree):
    """The four-pages-with-no-block case, which is the same defect maximally."""
    tree("a.md", "# T\n\ntext\n", FULL, bare=True)
    findings = []
    assert parity.gate_frontmatter({"a.md"}, {"a.md"}, findings) == 2


def test_frontmatter_rejects_a_present_but_empty_value(parity, tree):
    """`title:` with nothing after it satisfies a mere key-presence check and
    still renders an empty sidebar label."""
    tree("a.md", '---\ntitle: ""\ndescription: "D"\n---\n\n# T\n', FULL)
    findings = []
    assert parity.gate_frontmatter({"a.md"}, {"a.md"}, findings) == 1
    assert "no title:" in findings[0]


def test_frontmatter_checks_the_zh_locale_too(parity, tree):
    """A zh `title:` is the zh sidebar label. An English-only check would let
    the Chinese sidebar silently fall back to the filename."""
    tree("a.md", FULL, '---\ndescription: "D"\n---\n\n# T\n')
    findings = []
    assert parity.gate_frontmatter({"a.md"}, {"a.md"}, findings) == 1
    assert "[zh]" in findings[0]


def test_frontmatter_does_not_require_sidebar_position(parity, tree):
    """MEASURED, not lenient. website/sidebars.ts is an explicit hand-written
    sidebar with zero `autogenerated` entries, and Docusaurus only consults
    sidebar_position for autogenerated items -- so the key is inert here and 184
    of 361 English pages omit it. Requiring it would be 184 findings of noise.
    Pinned so nobody 'completes' the gate by adding it back."""
    assert "sidebar_position" not in parity.FRONTMATTER_REQUIRED
    tree("a.md", FULL, FULL)
    findings = []
    assert parity.gate_frontmatter({"a.md"}, {"a.md"}, findings) == 0


def test_frontmatter_allowlist_is_keyed_per_page_locale_and_key(parity, tree):
    """The waivers are debt for specific (page, locale, key) triples. The same
    key missing anywhere else is a real finding."""
    tree("other.md", "# O\n\ntext\n", "# O\n\ntext\n", bare=True)
    findings = []
    assert parity.gate_frontmatter({"other.md"}, {"other.md"}, findings) == 4


def test_frontmatter_allowlist_entries_point_at_real_pages(parity):
    """A waiver whose path no longer exists is dead weight covering nothing --
    the exact failure that made three of the four DRIFT_ALLOW entries inert."""
    roots = {"en": Path(parity.EN_DIR), "zh": Path(parity.ZH_DIR)}
    for rel, locale, key in parity.FRONTMATTER_ALLOW:
        assert locale in roots, (rel, locale)
        assert key in parity.FRONTMATTER_REQUIRED, (rel, key)
        assert (roots[locale] / rel).is_file(), (rel, locale)


def test_frontmatter_allowlist_entries_are_all_still_needed(parity):
    """THE RATCHET. Filling in a waived page must fail this test until its entry
    is deleted, so the list can only ever shrink. Without this a waiver outlives
    the debt it was written for and silently re-permits the defect."""
    roots = {"en": Path(parity.EN_DIR), "zh": Path(parity.ZH_DIR)}
    stale = [
        (rel, locale, key)
        for rel, locale, key in sorted(parity.FRONTMATTER_ALLOW)
        if parity.frontmatter_value(
            (roots[locale] / rel).read_text(encoding="utf-8"), key
        )
    ]
    assert not stale, (
        "these pages now HAVE the key their waiver excuses -- delete the "
        "matching FRONTMATTER_ALLOW entries: %s" % stale
    )


def test_frontmatter_failure_counts_toward_the_exit_code(parity, tree, capsys):
    """A gate nobody fails on is theatre -- pin it to the process exit code."""
    tree("a.md", "# T\n\ntext\n", FULL, bare=True)
    assert parity.main([]) == 1
    assert "incomplete frontmatter .. 2" in capsys.readouterr().out


def test_allow_untranslated_does_not_waive_incomplete_frontmatter(parity, tree):
    """--allow-untranslated exists for pages nobody has translated yet. It does
    not excuse a page that exists in a locale from declaring its own title and
    description, and generate-skill-docs.py emits both unconditionally, so the
    PR lane can block on this without stranding a skill author."""
    tree("a.md", "# T\n\ntext\n", FULL, bare=True)
    assert parity.main(["--allow-untranslated"]) == 1
