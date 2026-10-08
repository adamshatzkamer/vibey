# Made with ❤️ by [Vibey](https://the-vibey-project.github.io/vibey/), Developed by [Adam Matthew Steinberger](https://vibewithadam.matthewsteinberger.com/) ([@adammatthewsteinberger](https://github.com/adammatthewsteinberger/)).
"""The docs-meta injection script does exactly what #848 requires.

The docs site is built by ProperDocs with the vanilla mkdocs base theme, which emits no
Open Graph tags, no Twitter Card tags, no canonical link, no schema.org structured data
and no per-page meta description. ``scripts/inject_docs_meta.py`` post-processes that
static output. These tests pin the required behaviour from the issue: idempotent
injection, a complete tag set on a fixture page, valid JSON-LD without a stale
``softwareVersion``, the mkdocs directory-URL canonical convention, and the script's
documented CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.inject_docs_meta import (
    canonical_url,
    homepage_json_ld,
    inject,
    load_site_config,
    page_description,
    paper_json_ld,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "inject_docs_meta.py"

FIXTURE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Reference — CLI</title>
  <style>body { color: #333; }</style>
</head>
<body>
  <h1>CLI reference</h1>
  <p>This is the first paragraph   after the heading. It has   extra whitespace that
     must be collapsed into   single spaces before truncation.</p>
  <p>Second paragraph, ignored.</p>
</body>
</html>
"""


def test_inject_adds_every_required_tag_to_a_fixture_page() -> None:
    result = inject(
        FIXTURE_HTML,
        title="Reference — CLI",
        description="A page description.",
        canonical="https://the-vibey-project.github.io/vibey/reference/cli/",
        site_name="vibey",
        image_url="https://the-vibey-project.github.io/vibey/img/social-preview.png",
        json_ld='{"@type":"SoftwareApplication"}',
    )
    for needle in (
        '<meta name="description" content="A page description.">',
        '<link rel="canonical" href="https://the-vibey-project.github.io/vibey/reference/cli/">',
        '<meta property="og:title" content="Reference — CLI">',
        '<meta property="og:description" content="A page description.">',
        '<meta property="og:type" content="website">',
        '<meta property="og:url" content="https://the-vibey-project.github.io/vibey/reference/cli/">',
        '<meta property="og:site_name" content="vibey">',
        '<meta property="og:image" content="https://the-vibey-project.github.io/vibey/img/social-preview.png">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:title" content="Reference — CLI">',
        '<meta name="twitter:description" content="A page description.">',
        '<meta name="twitter:image" content="https://the-vibey-project.github.io/vibey/img/social-preview.png">',
        '<script type="application/ld+json">{"@type":"SoftwareApplication"}</script>',
    ):
        assert needle in result, f"missing {needle}"
    assert result.index("</head>") > result.index('<meta property="og:title"')


def test_inject_is_idempotent() -> None:
    once = inject(
        FIXTURE_HTML,
        title="T",
        description="D",
        canonical="https://example.org/",
        site_name="vibey",
        image_url="https://example.org/img/social-preview.png",
        json_ld='{"@type":"SoftwareApplication"}',
    )
    twice = inject(
        once,
        title="T",
        description="D",
        canonical="https://example.org/",
        site_name="vibey",
        image_url="https://example.org/img/social-preview.png",
        json_ld='{"@type":"SoftwareApplication"}',
    )
    assert twice == once


def test_inject_leaves_no_head_html_unchanged() -> None:
    html = "<html><body><h1>No head</h1><p>text</p></body></html>"
    assert (
        inject(
            html,
            title="T",
            description="D",
            canonical="https://example.org/",
            site_name="vibey",
            image_url="https://example.org/img.png",
            json_ld=None,
        )
        == html
    )


def test_homepage_json_ld_round_trips_and_has_no_software_version() -> None:
    parsed = json.loads(homepage_json_ld("https://the-vibey-project.github.io/vibey/", "d"))
    assert parsed["@type"] == "SoftwareApplication"
    assert parsed["name"] == "vibey"
    assert "softwareVersion" not in parsed
    assert parsed["author"]["name"] == "Adam Matthew Steinberger"


def test_paper_json_ld_is_a_scholarly_article() -> None:
    parsed = json.loads(paper_json_ld("https://the-vibey-project.github.io/vibey/"))
    assert parsed["@type"] == "ScholarlyArticle"
    assert parsed["url"] == "https://the-vibey-project.github.io/vibey/main/paper/"


def test_page_description_takes_first_p_after_first_h1_collapsed() -> None:
    assert page_description(FIXTURE_HTML, "fallback") == (
        "This is the first paragraph after the heading. It has extra whitespace that "
        "must be collapsed into single spaces before truncation."
    )


def test_page_description_truncates_at_155_chars_on_word_boundary() -> None:
    long = "<html><head><title>t</title></head><body><h1>H</h1><p>word " * 40 + "</p></body></html>"
    result = page_description(long, "fallback")
    assert result.endswith("…")
    assert len(result) <= 156  # 155 chars + the ellipsis


def test_page_description_falls_back_without_paragraph() -> None:
    html = "<html><head><title>t</title></head><body><h1>Only a heading</h1></body></html>"
    assert page_description(html, "fallback") == "fallback"


def test_canonical_url_directory_conventions() -> None:
    site = "https://the-vibey-project.github.io/vibey/"
    assert canonical_url(site, "index.html") == site
    assert canonical_url(site, "reference/cli/index.html") == (
        "https://the-vibey-project.github.io/vibey/reference/cli/"
    )
    assert canonical_url(site, "guides/install/index.html") == (
        "https://the-vibey-project.github.io/vibey/guides/install/"
    )
    assert canonical_url(site, "assets/style.css") == (
        "https://the-vibey-project.github.io/vibey/assets/style.css"
    )


def test_canonical_url_normalises_site_url_trailing_slash() -> None:
    assert canonical_url("https://example.org", "index.html") == "https://example.org/"


def test_load_site_config_reads_three_fields(tmp_path: Path) -> None:
    config = tmp_path / "properdocs.yml"
    config.write_text(
        "site_name: vibey\n"
        "site_description: an orchestrator\n"
        "site_url: https://the-vibey-project.github.io/vibey/\n",
        encoding="utf-8",
    )
    loaded = load_site_config(config)
    assert loaded.site_name == "vibey"
    assert loaded.site_description == "an orchestrator"
    assert loaded.site_url == "https://the-vibey-project.github.io/vibey/"


def test_main_help_exits_zero_and_documents_both_flags() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--site-dir" in result.stdout
    assert "--properdocs-yml" in result.stdout
