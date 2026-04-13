#!/usr/bin/env python3
"""
Top-up scraper: fetch the remaining diary entries (May 14–23, 2001) that
were not present in the main diary.php page snapshot.

These entries have individual Wayback snapshots discovered via CDX.
Run AFTER scrape_diary.py.
"""

import re
import sys
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag

OUTPUT_DIR = Path(__file__).parent.parent / "content" / "diary"
SLEEP = 2.0

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "china-diary-rescue/1.0 (archival research)"})

# Known individual snapshots from CDX (timestamp, original URL)
# Status-200 snapshots for entries missing from the main page.
INDIVIDUAL_SNAPSHOTS = [
    ("20030924225118", "http://www.kumiankka.org/china/diary.php?day=20010514Maanantai"),
    ("20030924005601", "http://www.kumiankka.org/china/diary.php?day=20010515Tiistai"),
    ("20030923021619", "http://www.kumiankka.org/china/diary.php?day=20010516Keskiviikko"),
    # May 17 has no known snapshot — will try availability API
    ("20030920165125", "http://www.kumiankka.org/china/diary.php?day=20010518Perjantai"),
    ("20030919220027", "http://www.kumiankka.org/china/diary.php?day=20010519Lauantai"),
    ("20030910011607", "http://www.kumiankka.org/china/diary.php?day=20010520Sunnuntai"),
    ("20030509035152", "http://www.kumiankka.org/china/diary.php?day=20010521Maanantai"),
    # May 22 and 23 — try availability API
]

# Days to try via availability API (no known CDX snapshot)
AVAIL_DAYS = [
    "20010517Perjantai",
    "20010522Tiistai",
    "20010523Keskiviikko",
]

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def strip_wayback(soup):
    for tag in soup.find_all(id=re.compile(r"^wm-")):
        tag.decompose()


def elem_to_md(elem):
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


def cell_to_md(td):
    paragraphs = []
    for p in td.find_all("p"):
        text = elem_to_md(p)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        text = elem_to_md(td)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def parse_single_entry(html_text, source_url):
    """Parse a single-day snapshot page."""
    soup = BeautifulSoup(html_text, "html.parser")
    strip_wayback(soup)

    date_cell = soup.find("td", class_="tekstibold")
    header_text = date_cell.get_text(strip=True) if date_cell else ""

    # Find content cell — the one with <p align="justify">
    content_cell = None
    for td in soup.find_all("td", class_="teksti"):
        if td.find("p", attrs={"align": "justify"}):
            content_cell = td
            break

    # Fallback: largest teksti cell with actual content
    if not content_cell:
        best = None
        for td in soup.find_all("td", class_="teksti"):
            text = td.get_text(strip=True)
            if len(text) > (len(best.get_text(strip=True)) if best else 0):
                best = td
        content_cell = best

    body = cell_to_md(content_cell) if content_cell else ""
    return header_text, body


def day_value_to_date(day_value):
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", day_value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def save(date_str, title, body, source_url):
    out = OUTPUT_DIR / f"{date_str}.md"
    safe_title = title.replace('"', '\\"')
    out.write_text(
        f"---\ndate: {date_str}\ntitle: \"{safe_title}\"\n"
        f"original_url: \"{source_url}\"\n---\n\n{body}\n",
        encoding="utf-8"
    )
    print(f"  saved {out.name}  ({len(body.split())} words)")


def fetch_and_save(wayback_url, original_url):
    date_str = day_value_to_date(original_url.split("day=")[1])
    if not date_str:
        print(f"  could not parse date from {original_url}")
        return False

    out = OUTPUT_DIR / f"{date_str}.md"
    if out.exists():
        print(f"  {date_str} already exists, skipping")
        return True

    print(f"  fetching {date_str} …")
    time.sleep(SLEEP)
    resp = SESSION.get(wayback_url, timeout=30)
    resp.encoding = "iso-8859-1"

    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code} for {wayback_url}")
        return False

    # Check if we got actual diary content or a Wayback "not found" page
    if "kumiankka.org" not in resp.text and "teksti" not in resp.text:
        print(f"  no diary content in response")
        return False

    title, body = parse_single_entry(resp.text, wayback_url)
    if not body.strip():
        print(f"  no content parsed")
        return False

    save(date_str, title, body, wayback_url)
    return True


def try_availability_api(day_value):
    original = f"www.kumiankka.org/china/diary.php?day={day_value}"
    resp = SESSION.get(
        "https://archive.org/wayback/available",
        params={"url": original}, timeout=15
    )
    data = resp.json()
    closest = data.get("archived_snapshots", {}).get("closest", {})
    if closest.get("available") and closest.get("status") == "200":
        return closest["url"], f"http://{original}"
    return None, None


def main():
    print("=" * 50)
    print("  China Diary Top-up Scraper")
    print("=" * 50 + "\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch known individual snapshots
    print("Phase 1: known CDX snapshots")
    for ts, original in INDIVIDUAL_SNAPSHOTS:
        wayback_url = f"https://web.archive.org/web/{ts}/{original}"
        fetch_and_save(wayback_url, original)

    # Try availability API for the unknowns
    print("\nPhase 2: availability API for remaining days")
    for day_value in AVAIL_DAYS:
        date_str = day_value_to_date(day_value)
        out = OUTPUT_DIR / f"{date_str}.md"
        if out.exists():
            print(f"  {date_str} already exists, skipping")
            continue
        print(f"  querying availability for {day_value} …")
        wayback_url, original_url = try_availability_api(day_value)
        if wayback_url:
            print(f"  found: {wayback_url}")
            fetch_and_save(wayback_url, original_url)
        else:
            print(f"  no snapshot found for {day_value}")

    # Final count
    files = sorted(OUTPUT_DIR.glob("*.md"))
    print(f"\nTotal entries in content/diary/: {len(files)}")
    for f in files:
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
