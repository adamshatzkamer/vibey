# Made with ❤️ by [Vibey](https://the-vibey-project.github.io/vibey/), Developed by [Adam Matthew Steinberger](https://vibewithadam.matthewsteinberger.com/) ([@adammatthewsteinberger](https://github.com/adammatthewsteinberger/)).
"""Inject per-page SEO and social-link metadata into the built docs site (#848).

The docs site is built by ProperDocs with the vanilla mkdocs base theme, which emits
no Open Graph tags, no Twitter Card tags, no canonical link, no schema.org structured
data and no per-page meta description. Rather than depend on ProperDocs's internal
template-extension surface (undocumented from this checkout and pinned externally), this
script post-processes the tool's own static HTML output -- guaranteed to work regardless
of what ProperDocs exposes as a customization point, and kept in one small, fully
unit-testable module instead of a fragile theme override.

It is a post-build step: it never changes how ``properdocs build`` runs, only what
happens to its ``site/`` output afterward. The script is idempotent -- running it twice
on the same tree produces byte-identical output the second time.

    python scripts/inject_docs_meta.py --site-dir site
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# A page's own <title>...</title>, used as the og:title/twitter:title on every page.
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# The first <p> after the first <h1>, used as the page's meta/OG/Twitter description.
_H1 = re.compile(r"<h1[^>]*>.*?</h1>", re.IGNORECASE | re.DOTALL)
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

DESCRIPTION_LIMIT = 155

# The tags this script owns. A tag is considered present (and therefore left alone,
# making the script idempotent) when its name=/property=/rel= attribute substring is
# already in the document.
_META_TAGS = (
    '<meta name="description" content="{description}">',
    '<link rel="canonical" href="{canonical}">',
    '<meta property="og:title" content="{title}">',
    '<meta property="og:description" content="{description}">',
    '<meta property="og:type" content="website">',
    '<meta property="og:url" content="{canonical}">',
    '<meta property="og:site_name" content="{site_name}">',
    '<meta property="og:image" content="{image_url}">',
    '<meta name="twitter:card" content="summary_large_image">',
    '<meta name="twitter:title" content="{title}">',
    '<meta name="twitter:description" content="{description}">',
    '<meta name="twitter:image" content="{image_url}">',
)
_PRESENCE = (
    'name="description"',
    'rel="canonical"',
    'property="og:title"',
    'property="og:description"',
    'property="og:type"',
    'property="og:url"',
    'property="og:site_name"',
    'property="og:image"',
    'name="twitter:card"',
    'name="twitter:title"',
    'name="twitter:description"',
    'name="twitter:image"',
)
_JSON_LD_PRESENCE = 'type="application/ld+json"'


@dataclass(frozen=True)
class SiteConfig:
    """The three site-level values this script reads from the ProperDocs config."""

    site_name: str
    site_description: str
    site_url: str


def load_site_config(properdocs_yml: Path) -> SiteConfig:
    """Read ``site_name``, ``site_description`` and ``site_url`` from the YAML config."""
    data = yaml.safe_load(properdocs_yml.read_text(encoding="utf-8")) or {}
    return SiteConfig(
        site_name=str(data.get("site_name", "")),
        site_description=str(data.get("site_description", "")),
        site_url=str(data.get("site_url", "")),
    )


def page_description(html: str, fallback: str) -> str:
    """The text of the first ``<p>`` after the first ``<h1>``, or ``fallback``.

    Whitespace is collapsed to single spaces and the result truncated to 155 characters
    at the last word boundary, with a trailing ``…`` when truncated.
    """
    h1 = _H1.search(html)
    if h1 is None:
        return fallback
    paragraph = _P.search(html, h1.end())
    if paragraph is None:
        return fallback
    text = _WHITESPACE.sub(" ", _TAGS.sub("", paragraph.group(1))).strip()
    if not text:
        return fallback
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    cut = text[:DESCRIPTION_LIMIT]
    boundary = cut.rfind(" ")
    if boundary > 0:
        cut = cut[:boundary]
    return f"{cut}…"


def canonical_url(site_url: str, site_relative_path: str) -> str:
    """Join ``site_url`` (exactly one trailing slash) to the page's site-relative path.

    A bare ``index.html`` maps to its directory, mkdocs's own directory-URL convention
    (``reference/cli/index.html`` → ``reference/cli/``; root ``index.html`` → ``""``).
    """
    base = site_url.rstrip("/") + "/"
    if site_relative_path in ("", "index.html"):
        return base
    if site_relative_path.endswith("/index.html"):
        return f"{base}{site_relative_path[: -len('index.html')]}"
    return f"{base}{site_relative_path}"


def inject(
    html: str,
    *,
    title: str,
    description: str,
    canonical: str,
    site_name: str,
    image_url: str,
    json_ld: str | None,
) -> str:
    """Insert the SEO/social tags immediately before ``</head>`` (idempotent).

    Any tag whose ``name=``/``property=``/``rel=`` attribute substring is already
    present in the document is left alone, so re-running the script on the same HTML
    produces byte-identical output.
    """
    head_end = html.lower().rfind("</head>")
    if head_end == -1:
        return html
    values = {
        "title": title,
        "description": description,
        "canonical": canonical,
        "site_name": site_name,
        "image_url": image_url,
    }
    block = []
    for tag, presence in zip(_META_TAGS, _PRESENCE, strict=True):
        if presence in html:
            continue
        block.append(tag.format(**values))
    if json_ld is not None and _JSON_LD_PRESENCE not in html:
        block.append(f'<script type="application/ld+json">{json_ld}</script>')
    if not block:
        return html
    inserted = "".join(f"    {line}\n" for line in block)
    return f"{html[:head_end]}{inserted}{html[head_end:]}"


def homepage_json_ld(site_url: str, description: str) -> str:
    """A ``SoftwareApplication`` JSON-LD block for the site root.

    Deliberately omits ``softwareVersion``: a hardcoded version in a static asset goes
    stale the moment the next release ships (sub-doctrine 10.f).
    """
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "vibey",
            "description": description,
            "url": site_url,
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Linux, macOS",
            "license": "https://github.com/the-vibey-project/vibey/blob/main/LICENSE",
            "codeRepository": "https://github.com/the-vibey-project/vibey",
            "downloadUrl": "https://pypi.org/project/vibey/",
            "programmingLanguage": "Python",
            "author": {
                "@type": "Person",
                "name": "Adam Matthew Steinberger",
                "url": "https://github.com/adammatthewsteinberger",
            },
        },
        ensure_ascii=False,
    )


def paper_json_ld(site_url: str) -> str:
    """A ``ScholarlyArticle`` JSON-LD block for the research-paper page."""
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ScholarlyArticle",
            "headline": (
                "Ledger-Mediated Orchestration: Vendor-Independent Autonomous Software "
                "Delivery over a Pool of Coding Agents"
            ),
            "url": f"{site_url}main/paper/",
            "author": {"@type": "Person", "name": "Adam Matthew Steinberger"},
            "isPartOf": {"@type": "WebSite", "name": "vibey", "url": site_url},
        },
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inject per-page SEO and social-link metadata into the built docs site."
    )
    parser.add_argument(
        "--site-dir",
        default="site",
        help="Directory containing the built static site to post-process (default: site).",
    )
    parser.add_argument(
        "--properdocs-yml",
        default="properdocs.yml",
        help="ProperDocs config file to read site_name/site_description/site_url from "
        "(default: properdocs.yml).",
    )
    args = parser.parse_args(argv)

    site_dir = Path(args.site_dir)
    config = load_site_config(Path(args.properdocs_yml))
    image_url = f"{config.site_url.rstrip('/')}/img/social-preview.png"

    changed = 0
    for html_path in sorted(site_dir.rglob("*.html")):
        html = html_path.read_text(encoding="utf-8")
        relative = html_path.relative_to(site_dir).as_posix()
        title_match = _TITLE.search(html)
        title = title_match.group(1).strip() if title_match else config.site_name
        description = page_description(html, config.site_description)
        canonical = canonical_url(config.site_url, relative)

        if relative == "index.html":
            json_ld = homepage_json_ld(config.site_url, description)
        elif relative in ("main/paper/index.html", "paper/index.html"):
            json_ld = paper_json_ld(config.site_url)
        else:
            json_ld = None

        updated = inject(
            html,
            title=title,
            description=description,
            canonical=canonical,
            site_name=config.site_name,
            image_url=image_url,
            json_ld=json_ld,
        )
        if updated != html:
            html_path.write_text(updated, encoding="utf-8")
            changed += 1

    print(f"inject_docs_meta: updated {changed} page(s) under {site_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
