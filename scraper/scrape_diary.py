#!/usr/bin/env python3
"""
Scrape China Diary entries from the Wayback Machine.
Original site: kumiankka.org/china/diary.php (archived 2003)

Key discovery: the main diary.php page (no parameters) contains ALL ~80 entries
in a single HTML document — no need to fetch each entry separately.

Strategy:
  1. Fetch diary.php once (2003 snapshot, ~149KB, contains everything).
  2. Walk the content table rows, pairing <td class="tekstibold"> date headers
     with <td class="teksti"> content cells.
  3. Group sections by date, save as content/diary/YYYY-MM-DD.md (UTF-8).

Usage:
    pip install -r scraper/requirements.txt
    python3 scraper/scrape_diary.py
"""

import re
import sys
import requests
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_URL = (
    "https://web.archive.org/web/20011004043640/"
    "http://www.kumiankka.org/china/diary.php"
)
OUTPUT_DIR = Path(__file__).parent.parent / "content" / "diary"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "china-diary-rescue/1.0 (archival research)"})

# ---------------------------------------------------------------------------
# Wayback toolbar removal
# ---------------------------------------------------------------------------

def strip_wayback_toolbar(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(id=re.compile(r"^wm-")):
        tag.decompose()
    for script in soup.find_all("script"):
        src = script.get("src", "")
        if "archive.org" in src or "/_static/" in src:
            script.decompose()

# ---------------------------------------------------------------------------
# HTML → Markdown conversion
# ---------------------------------------------------------------------------

def elem_to_md(elem) -> str:
    """Recursively convert element children to Markdown text."""
    parts = []
    for child in elem.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "b":
                inner = elem_to_md(child).strip()
                parts.append(f"**{inner}**" if inner else "")
            elif child.name == "br":
                parts.append("\n")
            elif child.name in ("i", "em"):
                inner = elem_to_md(child).strip()
                parts.append(f"*{inner}*" if inner else "")
            elif child.name == "a":
                parts.append(child.get_text())
            else:
                parts.append(elem_to_md(child))
    return "".join(parts)


def cell_to_md(td: Tag) -> str:
    """Convert a <td class="teksti"> cell to clean Markdown paragraphs."""
    paragraphs = []
    for p in td.find_all("p"):
        text = elem_to_md(p)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            paragraphs.append(text)

    # Some cells have text directly without <p> wrappers — collect those too
    if not paragraphs:
        text = elem_to_md(td)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)

# ---------------------------------------------------------------------------
# Parse all entries from the single-page document
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def parse_entries(html_text: str) -> dict:
    """
    Parse all diary entries from the full-diary HTML page.

    Returns a dict keyed by ISO date string:
      {
        "2001-03-05": {
          "date": "2001-03-05",
          "title": "05.03.2001 Maanantai",
          "sections": ["## Section header", "Markdown body...", ...]
        },
        ...
      }
    """
    soup = BeautifulSoup(html_text, "html.parser")
    strip_wayback_toolbar(soup)

    # Find the main content table — the one that directly contains
    # <td class="tekstibold"> cells.
    first_bold = soup.find("td", class_="tekstibold")
    if not first_bold:
        sys.exit("ERROR: Could not find any tekstibold cells in the page.")

    content_table = first_bold.find_parent("table")

    entries: dict = {}       # date_str → entry dict
    current_date: str | None = None

    for row in content_table.find_all("tr", recursive=False):
        bold_cell = row.find("td", class_="tekstibold")
        teksti_cell = row.find("td", class_="teksti")

        if bold_cell:
            raw_header = bold_cell.get_text(strip=True)
            m = DATE_RE.search(raw_header)

            if m:
                # New date section
                day, month, year = m.groups()
                current_date = f"{year}-{month}-{day}"
                if current_date not in entries:
                    entries[current_date] = {
                        "date": current_date,
                        "title": raw_header,
                        "sections": [],
                    }
                else:
                    # Same date already exists (parallel narratives, e.g. Hainan/Guilin)
                    # Add a section break with the new header
                    entries[current_date]["sections"].append(f"\n---\n\n**{raw_header}**")

            elif current_date and raw_header:
                # No date found — a sub-location or sub-author header within current date
                entries[current_date]["sections"].append(f"\n**{raw_header}**\n")

        elif teksti_cell and current_date:
            md = cell_to_md(teksti_cell)
            if md.strip():
                entries[current_date]["sections"].append(md)

    return entries

# ---------------------------------------------------------------------------
# Save entries to content/diary/
# ---------------------------------------------------------------------------

def save_entries(entries: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for date_str in sorted(entries.keys()):
        entry = entries[date_str]
        body = "\n\n".join(entry["sections"]).strip()
        safe_title = entry["title"].replace('"', '\\"')

        content = (
            f"---\n"
            f"date: {date_str}\n"
            f"title: \"{safe_title}\"\n"
            f"original_url: \"{SOURCE_URL}\"\n"
            f"---\n\n"
            f"{body}\n"
        )

        out_path = OUTPUT_DIR / f"{date_str}.md"
        out_path.write_text(content, encoding="utf-8")
        word_count = len(body.split())
        print(f"  {date_str}  {entry['title']:<40}  {word_count:>5} words")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 55)
    print("  China Diary Scraper  (single-page strategy)")
    print("=" * 55)
    print(f"\nFetching: {SOURCE_URL}\n")

    resp = SESSION.get(SOURCE_URL, timeout=30)
    resp.encoding = "iso-8859-1"
    print(f"Response: {resp.status_code}  ({len(resp.content):,} bytes)\n")

    if resp.status_code != 200:
        sys.exit(f"ERROR: got HTTP {resp.status_code}")

    entries = parse_entries(resp.text)
    print(f"Parsed {len(entries)} diary entries.\n")

    save_entries(entries)

    print(f"\nDone — {len(entries)} files written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
