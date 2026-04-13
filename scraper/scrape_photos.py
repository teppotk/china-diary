#!/usr/bin/env python3
"""
Scrape China Diary photo archive from the Wayback Machine.
Source: kumiankka.org/china/photoarchive.php (2001 snapshot)

Strategy:
  Phase 1 — Metadata: crawl all 16 grid pages + individual photo pages
             to collect filenames, captions, and Wayback image URLs.
             Saves content/photos/metadata.json (resumable).
  Phase 2 — Download: fetch full-size images and thumbnails from Wayback.
             Skips files that already exist (fully resumable).

Output:
  content/photos/metadata.json         — photo index with captions
  content/photos/full/DSC01233.jpg     — full-size images
  content/photos/thumbnails/DSC01233.jpg

Usage:
    python3 scraper/scrape_photos.py
    python3 scraper/scrape_photos.py --metadata-only   # skip downloads
    python3 scraper/scrape_photos.py --download-only   # skip metadata fetch
"""

import re
import sys
import time
import json
import argparse
import requests
from pathlib import Path
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ARCHIVE_TIMESTAMP = "20011030125802"
ORIGINAL_BASE     = "http://www.kumiankka.org/china"
WAYBACK_BASE      = "https://web.archive.org"

PHOTOS_DIR    = Path(__file__).parent.parent / "content" / "photos"
FULL_DIR      = PHOTOS_DIR / "full"
THUMB_DIR     = PHOTOS_DIR / "thumbnails"
METADATA_FILE = PHOTOS_DIR / "metadata.json"

PAGE_STARTS   = list(range(0, 384, 24))   # 0, 24, 48, … 360 → 16 pages

SLEEP_PAGE    = 1.5   # between archive page fetches
SLEEP_PHOTO   = 1.5   # between individual photo page fetches
SLEEP_IMG     = 0.5   # between image downloads

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "china-diary-rescue/1.0 (archival research)"})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wayback_url(path_or_url: str, timestamp: str = ARCHIVE_TIMESTAMP) -> str:
    """Build an absolute Wayback URL from a relative /web/... path or original URL."""
    if path_or_url.startswith("http"):
        return f"{WAYBACK_BASE}/web/{timestamp}im_/{path_or_url}"
    if path_or_url.startswith("/web/"):
        return f"{WAYBACK_BASE}{path_or_url}"
    return path_or_url


def archive_page_url(start_from: int) -> str:
    base = f"{ORIGINAL_BASE}/photoarchive.php"
    qs   = f"?startFrom={start_from}" if start_from > 0 else ""
    return f"{WAYBACK_BASE}/web/{ARCHIVE_TIMESTAMP}/{base}{qs}"


def photo_page_url(filename: str) -> str:
    return (f"{WAYBACK_BASE}/web/{ARCHIVE_TIMESTAMP}/"
            f"{ORIGINAL_BASE}/photoarchive.php?picture={filename}")


def strip_wayback(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(id=re.compile(r"^wm-")):
        tag.decompose()

# ---------------------------------------------------------------------------
# Phase 1: metadata collection
# ---------------------------------------------------------------------------

def collect_grid_page(start_from: int) -> list[dict]:
    """Fetch one grid page and return list of {filename, thumb_wayback_url, page}."""
    url  = archive_page_url(start_from)
    page = start_from // 24 + 1
    print(f"  Grid page {page:>2}/16  startFrom={start_from:<4}  {url}")

    time.sleep(SLEEP_PAGE)
    resp = SESSION.get(url, timeout=30)
    resp.encoding = "iso-8859-1"
    if resp.status_code != 200:
        print(f"    [warn] HTTP {resp.status_code}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    photos = []
    for a in soup.find_all("a", href=lambda h: h and "picture=" in h):
        img      = a.find("img")
        filename = a["href"].split("picture=")[1]
        thumb    = wayback_url(img["src"]) if img else ""
        photos.append({
            "filename":          filename,
            "page":              page,
            "page_start":        start_from,
            "thumb_wayback_url": thumb,
            "full_wayback_url":  "",   # filled in phase 1b
            "caption":           "",   # filled in phase 1b
        })
    print(f"    → {len(photos)} photos")
    return photos


def enrich_photo(photo: dict) -> dict:
    """Fetch individual photo page to get caption and full-size Wayback URL."""
    filename = photo["filename"]
    url      = photo_page_url(filename)

    time.sleep(SLEEP_PHOTO)
    resp = SESSION.get(url, timeout=30)
    resp.encoding = "iso-8859-1"
    if resp.status_code != 200:
        print(f"    [warn] {filename}: HTTP {resp.status_code}")
        return photo

    soup = BeautifulSoup(resp.text, "html.parser")
    strip_wayback(soup)

    # Caption: first non-empty teksti cell that isn't navigation
    caption = ""
    for td in soup.find_all("td", class_="teksti"):
        text = td.get_text(strip=True)
        # Skip cells that look like navigation (contain photo filenames listed)
        if len(text) > 5 and "DSC0" not in text and "startFrom" not in text:
            caption = text
            break

    # Full-size image: <img> whose src points to /galleria/china/photos/ (not thumbnails)
    full_url = ""
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "/photos/" in src and "DSC0" in src:
            full_url = wayback_url(src)
            break

    # Fallback: construct the URL if not found in page
    if not full_url:
        full_url = (f"{WAYBACK_BASE}/web/{ARCHIVE_TIMESTAMP}im_/"
                    f"http://www.kumiankka.org/galleria/china/photos/{filename}")

    photo["caption"]          = caption
    photo["full_wayback_url"] = full_url
    return photo


def collect_metadata() -> list[dict]:
    """Run full metadata collection across all 16 pages."""
    print("\n=== Phase 1a: crawl grid pages ===")
    all_photos = []
    for start in PAGE_STARTS:
        photos = collect_grid_page(start)
        all_photos.extend(photos)

    print(f"\nTotal photos found: {len(all_photos)}")

    # Load existing metadata to skip already-enriched photos
    existing = {}
    if METADATA_FILE.exists():
        for p in json.loads(METADATA_FILE.read_text()):
            if p.get("caption") or p.get("full_wayback_url"):
                existing[p["filename"]] = p

    print(f"\n=== Phase 1b: fetch captions ({len(all_photos)} photo pages) ===")
    for i, photo in enumerate(all_photos, 1):
        fname = photo["filename"]
        if fname in existing:
            all_photos[i-1] = existing[fname]
            print(f"  [{i:>3}/{len(all_photos)}] {fname}  (cached)")
            continue
        print(f"  [{i:>3}/{len(all_photos)}] {fname}")
        all_photos[i-1] = enrich_photo(photo)

        # Save checkpoint every 20 photos
        if i % 20 == 0:
            METADATA_FILE.write_text(
                json.dumps(all_photos, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"    [checkpoint saved]")

    METADATA_FILE.write_text(
        json.dumps(all_photos, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\nMetadata saved → {METADATA_FILE}")
    return all_photos


# ---------------------------------------------------------------------------
# Phase 2: image downloads
# ---------------------------------------------------------------------------

def download_image(url: str, dest: Path) -> bool:
    """Download a single image. Returns True on success."""
    if dest.exists():
        return True   # already downloaded
    try:
        time.sleep(SLEEP_IMG)
        resp = SESSION.get(url, timeout=60, stream=True)
        if resp.status_code != 200:
            print(f"    [warn] HTTP {resp.status_code}  {url}")
            return False
        ct = resp.headers.get("content-type", "")
        if "image" not in ct and "jpeg" not in ct and "octet" not in ct:
            print(f"    [warn] unexpected content-type {ct!r}  {url}")
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"    [error] {e}  {url}")
        return False


def download_all(photos: list[dict]) -> None:
    print(f"\n=== Phase 2: download images ({len(photos)} photos × 2) ===")
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    ok_full = ok_thumb = fail_full = fail_thumb = 0

    for i, photo in enumerate(photos, 1):
        fname = photo["filename"]
        print(f"  [{i:>3}/{len(photos)}] {fname}", end="  ")

        # Full-size
        full_dest = FULL_DIR / fname
        if not full_dest.exists():
            ok = download_image(photo["full_wayback_url"], full_dest)
            ok_full += ok; fail_full += not ok
            print(f"full={'ok' if ok else 'FAIL'}", end="  ")
        else:
            ok_full += 1
            print("full=cached", end="  ")

        # Thumbnail
        thumb_dest = THUMB_DIR / fname
        if not thumb_dest.exists():
            ok = download_image(photo["thumb_wayback_url"], thumb_dest)
            ok_thumb += ok; fail_thumb += not ok
            print(f"thumb={'ok' if ok else 'FAIL'}")
        else:
            ok_thumb += 1
            print("thumb=cached")

    print(f"\nFull:  {ok_full} ok / {fail_full} failed")
    print(f"Thumb: {ok_thumb} ok / {fail_thumb} failed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-only", action="store_true",
                        help="Only collect metadata, skip image downloads")
    parser.add_argument("--download-only", action="store_true",
                        help="Only download images using existing metadata.json")
    args = parser.parse_args()

    print("=" * 55)
    print("  China Diary Photo Scraper")
    print("=" * 55)

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    if args.download_only:
        if not METADATA_FILE.exists():
            sys.exit("ERROR: metadata.json not found — run without --download-only first")
        photos = json.loads(METADATA_FILE.read_text())
    else:
        photos = collect_metadata()

    if not args.metadata_only:
        download_all(photos)

    print(f"\nAll done. {len(photos)} photos processed.")
    print(f"  Metadata : {METADATA_FILE}")
    print(f"  Full     : {FULL_DIR}/")
    print(f"  Thumbs   : {THUMB_DIR}/")


if __name__ == "__main__":
    main()
