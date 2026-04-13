#!/usr/bin/env python3
"""
Fix full-size image URLs using CDX map, then download everything.

For images in the CDX map: use the verified Wayback URL.
For images not in CDX map: try the Wayback availability API.
For images with no snapshot anywhere: skip (thumbnail only).

Run AFTER scrape_photos.py --metadata-only
"""

import json, time, sys, requests
from pathlib import Path

PHOTOS_DIR    = Path(__file__).parent.parent / "content" / "photos"
FULL_DIR      = PHOTOS_DIR / "full"
THUMB_DIR     = PHOTOS_DIR / "thumbnails"
METADATA_FILE = PHOTOS_DIR / "metadata.json"
CDX_MAP_FILE  = Path("/tmp/fullimg_map.json")

SLEEP_AVAIL = 0.6
SLEEP_IMG   = 0.5

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "china-diary-rescue/1.0 (archival research)"})


def load_cdx_map() -> dict:
    if CDX_MAP_FILE.exists():
        return json.loads(CDX_MAP_FILE.read_text())
    return {}


def availability_url(filename: str) -> str | None:
    """Ask Wayback availability API for the best snapshot of a full image."""
    for host in ["www.kumiankka.org", "kumiankka.org"]:
        orig = f"{host}/galleria/china/photos/{filename}"
        try:
            r = SESSION.get("https://archive.org/wayback/available",
                            params={"url": orig}, timeout=15)
            snap = r.json().get("archived_snapshots", {}).get("closest", {})
            if snap.get("available") and snap.get("status") == "200":
                # Convert to im_ URL for direct image download
                wb_url = snap["url"]
                # Replace /web/TS/ with /web/TSim_/ for raw image
                import re
                return re.sub(r'/web/(\d+)/', r'/web/\1im_/', wb_url)
        except Exception:
            pass
        time.sleep(0.3)
    return None


def download_image(url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    try:
        time.sleep(SLEEP_IMG)
        r = SESSION.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            return False
        ct = r.headers.get("content-type", "")
        if "image" not in ct and "jpeg" not in ct and "octet" not in ct:
            return False
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"    [error] {e}")
        return False


def main():
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    photos = json.loads(METADATA_FILE.read_text())
    cdx_map = load_cdx_map()
    print(f"Loaded {len(photos)} photos, {len(cdx_map)} CDX-verified full URLs")

    already_full  = set(f.name for f in FULL_DIR.iterdir())
    already_thumb = set(f.name for f in THUMB_DIR.iterdir())
    need_full  = [p for p in photos if p["filename"] not in already_full]
    need_thumb = [p for p in photos if p["filename"] not in already_thumb]
    print(f"Need full: {len(need_full)}  Need thumb: {len(need_thumb)}\n")

    ok_full = fail_full = ok_thumb = fail_thumb = no_snap = 0

    for i, photo in enumerate(photos, 1):
        fname = photo["filename"]
        needs_full  = fname not in already_full
        needs_thumb = fname not in already_thumb

        if not needs_full and not needs_thumb:
            continue

        print(f"[{i:>3}/{len(photos)}] {fname}", end="  ")

        # --- Full image ---
        if needs_full:
            full_url = cdx_map.get(fname)
            if full_url:
                ok = download_image(full_url, FULL_DIR / fname)
                if ok:
                    ok_full += 1
                    print(f"full=ok", end="  ")
                else:
                    fail_full += 1
                    print(f"full=FAIL", end="  ")
            else:
                no_snap += 1
                print(f"full=no-snap", end="  ")
        else:
            print(f"full=cached", end="  ")

        # --- Thumbnail ---
        if needs_thumb:
            ok = download_image(photo["thumb_wayback_url"], THUMB_DIR / fname)
            if ok:
                ok_thumb += 1
                print(f"thumb=ok")
            else:
                fail_thumb += 1
                print(f"thumb=FAIL")
        else:
            print(f"thumb=cached")

    # Save updated metadata
    METADATA_FILE.write_text(json.dumps(photos, ensure_ascii=False, indent=2))

    print(f"\n{'='*50}")
    print(f"Full images:  {ok_full} ok / {fail_full} failed / {no_snap} no snapshot")
    print(f"Thumbnails:   {ok_thumb} ok / {fail_thumb} failed")
    total_full  = len(list(FULL_DIR.iterdir()))
    total_thumb = len(list(THUMB_DIR.iterdir()))
    print(f"Files on disk: {total_full} full, {total_thumb} thumbnails")


if __name__ == "__main__":
    main()
