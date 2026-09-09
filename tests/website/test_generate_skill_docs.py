"""Tests for website/scripts/generate-skill-docs.py.

The generator turns every `skills/**/SKILL.md` into a Docusaurus page before
the `docs-site-checks` CI workflow runs `ascii-guard lint` on the result. If
a SKILL.md contains ASCII diagrams (box-drawing chars in a fenced code block)
without its own `<!-- ascii-guard-ignore -->` markers, the generator must
add them defensively — otherwise every PR touching `website/**` fails lint
on unrelated skill content.

Regression for issue #15305.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "website" / "scripts" / "generate-skill-docs.py"


@pytest.fixture(scope="module")
def gen_module():
    """Load generate-skill-docs.py as a module (hyphenated filename, not importable via normal import)."""
    spec = importlib.util.spec_from_file_location("generate_skill_docs", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_code_block_without_box_chars_is_not_wrapped(gen_module):
    """Plain bash/python code blocks should stay uncluttered."""
    body = "Intro.\n\n```bash\npip install foo\nfoo --run\n```\n\nOutro."
    result = gen_module.mdx_escape_body(body)
    assert "ascii-guard-ignore" not in result
    assert "pip install foo" in result


def test_code_block_with_box_chars_gets_wrapped(gen_module):
    """A code fence containing Unicode box-drawing chars must be wrapped in
    ascii-guard-ignore comments so the docs-site-checks lint can't fail on
    a skill's own diagram (issue #15305)."""
    body = (
        "Some text.\n\n"
        "```\n"
        "┌─────────┐\n"
        "│ diagram │\n"
        "└─────────┘\n"
        "```\n\n"
        "More text."
    )
    result = gen_module.mdx_escape_body(body)
    assert "<!-- ascii-guard-ignore -->" in result
    assert "<!-- ascii-guard-ignore-end -->" in result
    # The wrapper must sit OUTSIDE the fence, not inside.
    wrap_open = result.index("<!-- ascii-guard-ignore -->")
    fence_open = result.index("```\n┌")
    assert wrap_open < fence_open


def test_multiple_code_blocks_only_box_ones_wrapped(gen_module):
    """Mixed body: plain code stays plain, box code gets wrapped."""
    body = (
        "```bash\necho hi\n```\n\n"
        "```\n┌──┐\n│  │\n└──┘\n```\n\n"
        "```python\nprint('ok')\n```"
    )
    result = gen_module.mdx_escape_body(body)
    # exactly one wrap pair
    assert result.count("<!-- ascii-guard-ignore -->") == 1
    assert result.count("<!-- ascii-guard-ignore-end -->") == 1
    # plain blocks untouched
    assert "echo hi" in result
    assert "print('ok')" in result


def test_tilde_fenced_box_is_wrapped(gen_module):
    """The generator supports both ``` and ~~~ fences — both must be covered."""
    body = "~~~\n│ box │\n~~~"
    result = gen_module.mdx_escape_body(body)
    assert "<!-- ascii-guard-ignore -->" in result


def test_already_wrapped_source_double_wraps_harmlessly(gen_module):
    """If the SKILL.md already has ascii-guard-ignore markers, the generator's
    extra wrap is harmless (ascii-guard tolerates adjacent duplicate markers).
    The test just verifies we don't crash and the content survives."""
    body = (
        "<!-- ascii-guard-ignore -->\n"
        "```\n┌─┐\n└─┘\n```\n"
        "<!-- ascii-guard-ignore-end -->"
    )
    result = gen_module.mdx_escape_body(body)
    assert "┌─┐" in result
    # At least one marker pair survives
    assert "<!-- ascii-guard-ignore -->" in result
    assert "<!-- ascii-guard-ignore-end -->" in result


def test_box_drawing_detection_covers_common_chars(gen_module):
    """Smoke-test that the char set covers box-drawing ranges actually used
    in skill diagrams."""
    # Sample from real SKILL.md diagrams (segment-anything, research-paper-writing, etc.)
    for ch in "┌┐└┘─│├┤┬┴┼═║╔╗╚╝╭╮╯╰▶◀▲▼":
        assert ch in gen_module._BOX_DRAWING_CHARS, f"missing: {ch!r}"


def test_bundled_catalog_explains_missing_local_skills(gen_module):
    """The bundled catalog should explain how to restore a listed skill that
    was removed from the local profile's skills tree."""
    result = gen_module.build_catalog_md_bundled([])
    assert "respects local deletions and user edits" in result
    assert "hermes skills reset <name> --restore" in result


# ---------------------------------------------------------------------------
# _truncate_on_word_boundary
#
# Frontmatter descriptions are capped at 160 chars for the meta description and
# catalog table cells at 240. The old cap sliced at the byte index, which cut
# mid-word and rendered as a typo on 16 pages and 30 catalog rows.
# ---------------------------------------------------------------------------


def test_short_text_is_returned_untouched(gen_module):
    assert gen_module._truncate_on_word_boundary("already short", 160) == "already short"


def test_text_exactly_at_the_limit_is_untouched(gen_module):
    text = "x" * 160
    assert gen_module._truncate_on_word_boundary(text, 160) == text


def test_cut_backs_up_to_a_word_boundary(gen_module):
    # "streaming" would be sliced to "strea" by a naive text[:limit - 3].
    text = "alpha beta gamma delta streaming"
    out = gen_module._truncate_on_word_boundary(text, 31)
    assert out == "alpha beta gamma delta..."
    assert not out.removesuffix("...").endswith(" ")


def test_result_never_exceeds_the_limit(gen_module):
    text = "word " * 200
    for limit in (20, 160, 240):
        assert len(gen_module._truncate_on_word_boundary(text, limit)) <= limit


def test_boundary_cut_keeps_the_whole_last_word(gen_module):
    # The slice lands exactly on the space after "gamma", so there is no
    # partial word and backing up another word would shorten it for nothing.
    text = "alpha beta gamma delta"
    assert gen_module._truncate_on_word_boundary(text, 19) == "alpha beta gamma..."


def test_dangling_punctuation_is_stripped_before_the_ellipsis(gen_module):
    # The slice ends "...gamma, " — a whole word plus punctuation, so nothing is
    # backed up and only the trailing comma is dropped.
    text = "alpha beta gamma, delta epsilon"
    assert gen_module._truncate_on_word_boundary(text, 21) == "alpha beta gamma..."


def test_trailing_space_in_the_slice_is_not_treated_as_mid_word(gen_module):
    # Regression: keying only off the character AFTER the cut treated this as a
    # mid-word break and dropped "gamma" even though the slice ended cleanly.
    text = "alpha beta gamma delta epsilon"
    assert gen_module._truncate_on_word_boundary(text, 20) == "alpha beta gamma..."


def test_single_unbroken_token_still_truncates(gen_module):
    # No space to back up to: fall back to a hard slice rather than returning "...".
    out = gen_module._truncate_on_word_boundary("x" * 300, 160)
    assert len(out) == 160
    assert out.endswith("...")


def test_dash_strip_does_not_strand_a_space_before_the_ellipsis(gen_module):
    # Regression: stripping the dangling dash exposed the space in front of it,
    # and a single ordered pass left it stranded -- the generated page read
    # "...(catalog entry: unreal-engine) ..." with a space before the ellipsis.
    text = "alpha beta gamma — delta epsilon"
    out = gen_module._truncate_on_word_boundary(text, 22)
    assert out == "alpha beta gamma..."
    assert " ..." not in out


# ---------------------------------------------------------------------------
# Orphaned-page pruning.
#
# The generator only ever wrote: a deleted or moved skill left its page behind
# in BOTH locales, still building and still counted by the i18n parity gate.
# CI regenerates before it builds, so a stale committed page never surfaced as
# a build failure either.
# ---------------------------------------------------------------------------


def _make_page(root, source_kind, category, page_name, source_rel):
    """Write a minimal generated-looking page and return its path."""
    path = root / source_kind / category / (page_name + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntitle: \"x\"\n---\n\n"
        "{/* This page is auto-generated from the skill's SKILL.md by "
        "website/scripts/generate-skill-docs.py. */}\n\n"
        "| | |\n|---|---|\n| Path | `" + source_rel + "` |\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def page_trees(tmp_path):
    """An English and a zh-Hans skills-pages tree, both empty."""
    en = tmp_path / "docs" / "user-guide" / "skills"
    zh = tmp_path / "i18n" / "current" / "user-guide" / "skills"
    en.mkdir(parents=True)
    zh.mkdir(parents=True)
    return en, zh


def _entry(gen_module, source_kind, category, slug, sub=None):
    return (
        {
            "source_kind": source_kind,
            "category": category,
            "sub": sub,
            "slug": slug,
            "rel_path": category + "/" + slug,
        },
        {"frontmatter": {"name": slug}, "body": ""},
    )


def test_prune_removes_a_page_whose_skill_is_gone(gen_module, page_trees):
    en, zh = page_trees
    keep = _entry(gen_module, "bundled", "apple", "apple-notes")
    keep_rel = gen_module.page_output_path(keep[0]).relative_to(gen_module.SKILLS_PAGES)
    _make_page(en, "bundled", "apple", keep_rel.stem, "skills/apple/apple-notes")
    orphan_en = _make_page(
        en, "bundled", "apple", "apple-macos-computer-use", "skills/apple/macos-computer-use"
    )
    orphan_zh = _make_page(
        zh, "bundled", "apple", "apple-macos-computer-use", "skills/apple/macos-computer-use"
    )

    removed = gen_module.prune_orphaned_pages([keep], skills_pages=en, zh_skills_pages=zh)

    assert not orphan_en.exists()
    # The zh twin has to go too: leaving it makes check-i18n-parity.py report
    # an `orphaned zh` finding, which is BLOCKING even under
    # --allow-untranslated.
    assert not orphan_zh.exists()
    assert set(removed) == {orphan_en, orphan_zh}
    assert (en / "bundled" / "apple" / (keep_rel.stem + ".md")).exists()


def test_prune_is_a_noop_when_every_page_has_a_skill(gen_module, page_trees):
    en, zh = page_trees
    entries = [
        _entry(gen_module, "bundled", "apple", "apple-notes"),
        _entry(gen_module, "optional", "finance", "ledger"),
    ]
    for meta, _ in entries:
        rel = gen_module.page_output_path(meta).relative_to(gen_module.SKILLS_PAGES)
        _make_page(en, meta["source_kind"], meta["category"], rel.stem, "skills/x")
        _make_page(zh, meta["source_kind"], meta["category"], rel.stem, "skills/x")

    assert gen_module.prune_orphaned_pages(entries, skills_pages=en, zh_skills_pages=zh) == []
    assert len(list(en.rglob("*.md"))) == 2
    assert len(list(zh.rglob("*.md"))) == 2


def test_prune_leaves_hand_written_top_level_pages_alone(gen_module, page_trees):
    en, zh = page_trees
    hand = en / "google-workspace.md"
    hand.write_text("# hand written\n", encoding="utf-8")

    assert gen_module.prune_orphaned_pages([], skills_pages=en, zh_skills_pages=zh) == []
    assert hand.exists()


def test_prune_drops_a_category_directory_left_empty(gen_module, page_trees):
    en, zh = page_trees
    _make_page(en, "bundled", "autonomous-ai-agents", "aaa-kanban-codex-lane", "skills/a/b")
    _make_page(zh, "bundled", "autonomous-ai-agents", "aaa-kanban-codex-lane", "skills/a/b")

    gen_module.prune_orphaned_pages([], skills_pages=en, zh_skills_pages=zh)

    assert not (en / "bundled" / "autonomous-ai-agents").exists()
    assert not (zh / "bundled" / "autonomous-ai-agents").exists()


def test_prune_tolerates_a_missing_zh_twin(gen_module, page_trees):
    """An English page added but never translated has no twin to remove."""
    en, zh = page_trees
    orphan = _make_page(en, "optional", "gaming", "gaming-gone", "skills/gaming/gone")

    removed = gen_module.prune_orphaned_pages([], skills_pages=en, zh_skills_pages=zh)

    assert removed == [orphan]


# ---------------------------------------------------------------------------
# check-orphaned-skill-pages.py -- the gate that FAILS on a committed orphan.
# The prune above repairs the tree; nothing in CI would fail on it, because
# docs-site-checks regenerates before it builds.
# ---------------------------------------------------------------------------

CHECKER = REPO_ROOT / "website" / "scripts" / "check-orphaned-skill-pages.py"


@pytest.fixture(scope="module")
def checker_module():
    spec = importlib.util.spec_from_file_location("check_orphaned_skill_pages", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_repo(tmp_path):
    """A repo-shaped tree with one live skill and one page per locale."""
    (tmp_path / "skills" / "apple" / "apple-notes").mkdir(parents=True)
    (tmp_path / "skills" / "apple" / "apple-notes" / "SKILL.md").write_text(
        "x", encoding="utf-8"
    )
    en = tmp_path / "website" / "docs"
    zh = (
        tmp_path
        / "website"
        / "i18n"
        / "zh-Hans"
        / "docusaurus-plugin-content-docs"
        / "current"
    )
    roots = [("en", en), ("zh-Hans", zh)]
    for _locale, root in roots:
        _make_page(
            root / "user-guide" / "skills",
            "bundled",
            "apple",
            "apple-apple-notes",
            "skills/apple/apple-notes",
        )
    return tmp_path, roots


def test_checker_passes_when_every_page_has_a_skill(checker_module, fake_repo):
    repo, roots = fake_repo
    findings, checked = checker_module.find_orphans(doc_roots=roots, repo_root=repo)
    assert findings == []
    assert checked == 2


def test_checker_reports_an_orphan_in_both_locales(checker_module, fake_repo):
    repo, roots = fake_repo
    for _locale, root in roots:
        _make_page(
            root / "user-guide" / "skills",
            "bundled",
            "apple",
            "apple-macos-computer-use",
            "skills/apple/macos-computer-use",
        )

    findings, checked = checker_module.find_orphans(doc_roots=roots, repo_root=repo)

    assert checked == 4
    assert len(findings) == 2
    assert {f[0] for f in findings} == {
        "website/docs/user-guide/skills/bundled/apple/apple-macos-computer-use.md",
        "website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/user-guide/"
        "skills/bundled/apple/apple-macos-computer-use.md",
    }
    assert all("no longer exists" in f[1] for f in findings)


def test_checker_matches_the_translated_path_label(checker_module, fake_repo):
    """The zh twin translates the row LABEL but not the path, so the matcher
    keys off the backticked value. A label-keyed matcher would skip every zh
    page -- i.e. fail toward clean on half the tree."""
    repo, roots = fake_repo
    zh_page = (
        roots[1][1]
        / "user-guide"
        / "skills"
        / "bundled"
        / "apple"
        / "apple-apple-notes.md"
    )
    zh_page.write_text(
        zh_page.read_text(encoding="utf-8").replace("| Path |", "| \u8def\u5f84 |"),
        encoding="utf-8",
    )

    findings, checked = checker_module.find_orphans(doc_roots=roots, repo_root=repo)
    assert checked == 2  # the zh page was still recognised and checked
    assert findings == []


def test_checker_skips_hand_written_pages(checker_module, fake_repo):
    repo, roots = fake_repo
    hand = roots[0][1] / "user-guide" / "skills" / "google-workspace.md"
    hand.write_text("# hand written, no generator marker\n", encoding="utf-8")

    findings, checked = checker_module.find_orphans(doc_roots=roots, repo_root=repo)
    assert findings == []
    assert checked == 2


def test_checker_reports_a_generated_page_with_no_path_row(checker_module, fake_repo):
    """Fail toward NOISY, not toward clean: an unparseable generated page is a
    finding, not a silent skip."""
    repo, roots = fake_repo
    bad = roots[0][1] / "user-guide" / "skills" / "bundled" / "apple" / "broken.md"
    bad.write_text(
        "{/* This page is auto-generated from the skill's SKILL.md by "
        "website/scripts/generate-skill-docs.py. */}\n\nno table here\n",
        encoding="utf-8",
    )

    findings, _checked = checker_module.find_orphans(doc_roots=roots, repo_root=repo)
    assert len(findings) == 1
    assert "no parseable source-path row" in findings[0][1]


def test_checker_finds_no_orphans_in_the_real_tree(checker_module):
    """Live guard: the two known orphans were removed in 7792ec407c."""
    findings, checked = checker_module.find_orphans()
    assert findings == [], findings
    assert checked > 300  # both locales, ~177 pages each


def test_checker_exits_non_zero_on_a_finding(checker_module, fake_repo, monkeypatch):
    repo, roots = fake_repo
    _make_page(
        roots[0][1] / "user-guide" / "skills",
        "bundled",
        "apple",
        "apple-gone",
        "skills/apple/gone",
    )
    monkeypatch.setattr(checker_module, "LOCALE_DOC_ROOTS", roots)
    monkeypatch.setattr(checker_module, "REPO_ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["check-orphaned-skill-pages.py"])
    assert checker_module.main() == 1
