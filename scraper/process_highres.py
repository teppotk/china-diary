#!/usr/bin/env python3
"""
Process the high-resolution originals into web-ready media + media.json.

Input  (not committed, archive copy of the camera files):
    content/photos/highres_originals/
        "2001-03-05_19-05-06 Kiina by Aki DSC01233.JPG"   (Sony Cybershot, q97)
        "... DSC01266.MPG" / "... MOV01405.MPG"            (MPEG-1 320x240)
        "2001-03-08_08-59-36 TXT01283.GIF"                 (camera text mode)
    content/photos/metadata.json   original 2001 photo archive (367 photos, captions)
    content/photos/full/           original 640x480 archive images (kept as-is)

Output (committed):
    content/photos/highres/              DSC01233.jpg (recompressed q75), TXT01283.gif,
                                         MOV01405.mp4 + MOV01405.jpg (video poster)
    content/photos/highres_thumbnails/   DSC01233.jpg, long edge 130px (2x the 2001 thumbs)
    content/photos/media.json            one record per item, sorted by camera number

media.json is the source of truth for the photo archive from now on. Captions
can be edited there by hand: re-running this script keeps existing captions.

Usage:
    python3 scraper/process_highres.py
"""

import json, re, shutil, subprocess, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
PHOTOS     = ROOT / "content" / "photos"
RAW        = PHOTOS / "highres_originals"
OUT        = PHOTOS / "highres"
THUMBS     = PHOTOS / "highres_thumbnails"
ORIG_META  = PHOTOS / "metadata.json"
MEDIA_JSON = PHOTOS / "media.json"

JPEG_QUALITY  = 75     # ≈ Photoshop "7–8"; ~23 % of the q97 originals
THUMB_EDGE    = 130    # 2001 thumbnails were 65px on the long edge
THUMB_QUALITY = 82

# The camera clock stayed on Finnish winter time (UTC+2) for the whole trip:
# "Tai Ji in the morning" is stamped 02:14, i.e. 08:14 in Shanghai (UTC+8).
CHINA_OFFSET = dt.timedelta(hours=6)
# Photos taken before 04:00 China time belong to the previous diary day.
DAY_ROLLOVER = dt.timedelta(hours=4)
# From MOV01405 on, the video filenames are stamped 3h later than the photos
# around them (paired JPG/MPG with the same number differ by exactly 3:00:00).
VIDEO_SKEW_FROM = 1405
VIDEO_SKEW      = dt.timedelta(hours=3)

NAME_RE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)\b.*?(?P<code>(?P<prefix>[A-Z]{3})(?P<num>\d{5}))"
    r"(?P<extra>[^.]*)\.(?P<ext>\w+)$")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def size_of(path: Path) -> tuple[int, int]:
    out = subprocess.run(["magick", "identify", "-format", "%w %h", f"{path}[0]"],
                         check=True, capture_output=True, text=True).stdout.split()
    return int(out[0]), int(out[1])


def video_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return round(float(out), 1)


def make_thumb(src: Path, dst: Path) -> None:
    if not dst.exists():
        run(["magick", f"{src}[0]", "-auto-orient", "-thumbnail",
             f"{THUMB_EDGE}x{THUMB_EDGE}", "-strip", "-quality", str(THUMB_QUALITY), str(dst)])


def process(item: dict) -> dict:
    src  = RAW / item["source"] if item["source"] else PHOTOS / item["file"]
    stem = item["id"]

    if item["type"] == "video":
        mp4    = OUT / f"{stem}.mp4"
        poster = OUT / f"{stem}.jpg"
        if not mp4.exists():
            run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                 "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(mp4)])
        if not poster.exists():
            run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(mp4),
                 "-frames:v", "1", "-q:v", "3", str(poster)])
        make_thumb(poster, THUMBS / f"{stem}.jpg")
        item["width"], item["height"] = size_of(poster)
        item["duration"] = video_duration(mp4)
        return item

    dst = PHOTOS / item["file"]
    if item["source"] and not dst.exists():
        if item["file"].endswith(".gif"):
            shutil.copy2(src, dst)
        else:
            run(["magick", str(src), "-auto-orient", "-sampling-factor", "4:2:0",
                 "-quality", str(JPEG_QUALITY), str(dst)])
    make_thumb(dst, THUMBS / f"{stem}.jpg")
    item["width"], item["height"] = size_of(dst)
    return item


def main() -> None:
    if not RAW.is_dir():
        raise SystemExit(f"Missing {RAW} — put the camera originals there first.")
    OUT.mkdir(exist_ok=True)
    THUMBS.mkdir(exist_ok=True)

    original = {Path(p["filename"]).stem.upper(): p for p in json.loads(ORIG_META.read_text())}
    previous = {}
    if MEDIA_JSON.exists():
        previous = {m["id"]: m for m in json.loads(MEDIA_JSON.read_text())}

    items, image_codes = [], set()
    for f in sorted(RAW.iterdir()):
        m = NAME_RE.match(f.name)
        if not m:
            continue                      # .DS_Store etc.
        if m["extra"].strip():
            print(f"skip (edited copy): {f.name}")
            continue
        ext  = m["ext"].lower()
        code = m["code"]
        num  = int(m["num"])
        taken = dt.datetime.strptime(m["ts"], "%Y-%m-%d_%H-%M-%S")
        if ext == "mpg":
            if num >= VIDEO_SKEW_FROM:
                taken -= VIDEO_SKEW
            kind = "video"
        else:
            kind = "image"
            image_codes.add(code)
        items.append({"code": code, "num": num, "type": kind, "ext": ext,
                      "source": f.name, "camera_time": taken})

    # Originals from the 2001 archive that have no high-res file: keep the 640px version
    have = {i["code"] for i in items}
    for code, p in original.items():
        if code not in have:
            items.append({"code": code, "num": int(code[3:]), "type": "image", "ext": "jpg",
                          "source": None, "camera_time": None, "fallback": p["filename"]})

    items.sort(key=lambda i: (i["num"], i["type"] == "video"))

    # Undated fallbacks inherit the time of the nearest dated neighbour (by camera number)
    dated = [i for i in items if i["camera_time"]]
    for i in items:
        if i["camera_time"] is None:
            i["camera_time"] = min(dated, key=lambda d: (abs(d["num"] - i["num"]), d["num"]))["camera_time"]
            i["estimated_time"] = True

    records = []
    for i in items:
        code = i["code"]
        if i["type"] == "video":
            rid  = f"{code}-video" if code in image_codes else code
            file = f"highres/{rid}.mp4"
        elif i.get("fallback"):
            rid, file = code, f"full/{i['fallback']}"
        else:
            rid  = code
            file = f"highres/{code}.{'gif' if i['ext'] == 'gif' else 'jpg'}"

        china = i["camera_time"] + CHINA_OFFSET
        orig  = original.get(code) if i["type"] == "image" else None
        caption = (orig or {}).get("caption") or ""
        if rid in previous:
            caption = previous[rid].get("caption", caption)

        rec = {
            "id":       rid,
            "type":     i["type"],
            "file":     file,
            "thumb":    f"highres_thumbnails/{rid}.jpg",
            "date":     (china - DAY_ROLLOVER).date().isoformat(),
            "taken":    china.isoformat(timespec="minutes"),
            "caption":  caption,
            "original": orig["filename"] if orig else None,
            "source":   i["source"],
        }
        if i["type"] == "video":
            rec["poster"] = f"highres/{rid}.jpg"
        if i.get("estimated_time"):
            rec["taken_estimated"] = True
        records.append(rec)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for n, rec in enumerate(pool.map(process, records), 1):
            if n % 100 == 0:
                print(f"  {n}/{len(records)}")

    MEDIA_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kinds = {k: sum(r["type"] == k for r in records) for k in ("image", "video")}
    print(f"media.json — {len(records)} items ({kinds['image']} images, {kinds['video']} videos), "
          f"{sum(1 for r in records if r['caption'])} with captions, "
          f"{sum(1 for r in records if r['original'])} from the 2001 archive")


if __name__ == "__main__":
    main()
