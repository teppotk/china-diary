#!/usr/bin/env python3
"""
Scrape the Practical Chinese (language dictionary) page from the Wayback Machine.
Source: kumiankka.org/china/practical.html (2003 snapshot)

Saves content/practical.md — section headers, category headings, phrase entries.

Usage:
    python3 scraper/scrape_practical.py
"""

import re
import sys
import html as htmllib
import requests
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag, Comment

SOURCE_URL = (
    "https://web.archive.org/web/20030904030309/"
    "http://www.kumiankka.org/china/practical.html"
)
OUTPUT_FILE = Path(__file__).parent.parent / "content" / "practical.md"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "china-diary-rescue/1.0 (archival research)"})

SECTION_TITLES = {
    "practical_chisense_title.gif": "Practical Chinese for Practical People",
    "practical_italianos.gif":      "Practical Italiano",
    "practical_tampere.gif":        "Practical Tampere",
}


def strip_wayback(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(id=re.compile(r"^wm-")):
        tag.decompose()
    for s in soup.find_all("script"):
        src = s.get("src") or ""
        if "archive.org" in src or "/_static/" in src:
            s.decompose()
    # Remove HTML comments entirely
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()


def norm(text: str) -> str:
    """Collapse all whitespace (incl. newlines) to single spaces, strip."""
    return re.sub(r"\s+", " ", text).strip()


def section_from_img(img_tag: Tag) -> str | None:
    src = img_tag.get("src", "")
    for fn, title in SECTION_TITLES.items():
        if fn in src:
            return title
    return None


def parse_content_td(td: Tag) -> list[dict]:
    """
    Walk all <p> elements in the content td.
    Returns a flat list of dicts:
      {"type": "section",   "text": "..."}
      {"type": "note",      "text": "..."}
      {"type": "heading",   "text": "..."}
      {"type": "entry",     "text": "..."}
    """
    items = []

    for p in td.find_all("p", recursive=True):
        # --- collect children linearly ---
        # Segment the <p> by spans (which are headings) and <br>-delimited text
        segments = []   # list of ("section"|"heading"|"text", text_value)

        buf: list[str] = []

        def flush(kind: str = "text") -> None:
            t = norm(" ".join(buf))
            buf.clear()
            if t:
                segments.append((kind, t))

        for child in p.children:
            if isinstance(child, Comment):
                buf.clear()   # don't accumulate comment text
                continue
            elif isinstance(child, NavigableString):
                t = norm(str(child))
                if t:
                    buf.append(t)
            elif isinstance(child, Tag):
                if child.name == "br":
                    flush()
                elif child.name == "img":
                    section_title = section_from_img(child)
                    if section_title:
                        flush()
                        segments.append(("section", section_title))
                    # else: bullet image — skip
                elif child.name == "span" and any(
                    "teksti_pieni_bold" in (c or "")
                    for c in (child.get("class") or [])
                ):
                    # Heading span — first flush any accumulated text
                    flush()
                    # Extract heading text (skip nested bullet images + comments)
                    parts: list[str] = []
                    for node in child.descendants:
                        if isinstance(node, Comment):
                            continue
                        if isinstance(node, NavigableString):
                            t = norm(str(node))
                            if t:
                                parts.append(t)
                        elif isinstance(node, Tag) and node.name == "br":
                            parts.append(" ")
                    h = norm(" ".join(parts))
                    if h:
                        segments.append(("heading", h))
                else:
                    # Other inline tags (b, a, …) — grab text
                    for node in child.descendants:
                        if isinstance(node, Comment):
                            continue
                        if isinstance(node, NavigableString):
                            t = norm(str(node))
                            if t:
                                buf.append(t)

        flush()   # final flush

        # Convert segments to items
        for kind, text in segments:
            if kind == "section":
                items.append({"type": "section", "text": text})
            elif kind == "heading":
                items.append({"type": "heading", "text": text})
            elif kind == "text":
                items.append({"type": "entry", "text": text})

    return items


def items_to_markdown(items: list[dict], intro: str) -> str:
    lines = [intro, ""]

    # Track whether we're inside a section (skip items before first section)
    in_section = False

    for item in items:
        t = item["type"]
        text = htmllib.unescape(item["text"])

        if t == "section":
            in_section = True
            lines.append(f"\n## {text}\n")
        elif t == "heading" and in_section:
            lines.append(f"\n**{text}**\n")
        elif t == "entry" and in_section:
            # Skip note-like lines (HTML remnants, pure whitespace)
            if re.search(r"<[a-z]", text, re.I):   # skip lines with leftover HTML tags
                continue
            lines.append(f"- {text}")

    return "\n".join(lines).strip()


def main() -> None:
    print(f"Fetching: {SOURCE_URL}")
    r = SESSION.get(SOURCE_URL, timeout=30)
    r.encoding = "iso-8859-1"
    print(f"Response: {r.status_code}  ({len(r.content):,} bytes)")
    if r.status_code != 200:
        sys.exit(f"ERROR: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    strip_wayback(soup)

    # The page has two <td colspan="4">:
    #   [0] intro text (no <p> tags)
    #   [1] content with all the <p> entries
    all_tds = soup.find_all("td", attrs={"colspan": "4"})
    intro_td   = all_tds[0] if len(all_tds) > 0 else None
    content_td = next((td for td in all_tds if td.find("p")), None)

    if not content_td:
        sys.exit("ERROR: could not find content cell")

    intro_text = norm(intro_td.get_text(" ")) if intro_td else ""
    intro_text = htmllib.unescape(intro_text)

    items = parse_content_td(content_td)
    body  = items_to_markdown(items, intro_text)

    content = (
        f"---\n"
        f"title: \"practikal chinese for practikal people\"\n"
        f"original_url: \"{SOURCE_URL}\"\n"
        f"---\n\n"
        f"{body}\n"
    )

    OUTPUT_FILE.write_text(content, encoding="utf-8")
    n_entries  = sum(1 for it in items if it["type"] == "entry")
    n_headings = sum(1 for it in items if it["type"] == "heading")
    n_sections = sum(1 for it in items if it["type"] == "section")
    print(f"\nSaved → {OUTPUT_FILE}")
    print(f"  {n_sections} sections, {n_headings} categories, {n_entries} entries")


if __name__ == "__main__":
    main()
