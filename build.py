#!/usr/bin/env python3
"""
Build script: content/ → data/ + dist/static/ + dist/dynamic/

Reads:  content/diary/*.md  and  content/photos/media.json
        (falls back to the 2001 archive list content/photos/metadata.json)
Writes:
  data/entries.json          — diary index (date, title, excerpt)
  data/YYYY-MM-DD.json       — per-entry data (body_html, etc.)
  dist/static/               — pre-rendered HTML, original design, works offline
  dist/dynamic/              — JSON + assets for a webserver JS app

Usage:
    pip install -r requirements.txt
    python3 build.py
    open dist/static/index.html
"""

import os, re, json, shutil, html as htmlmod
from pathlib import Path
import markdown as mdlib

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT              = Path(__file__).parent
DIARY_DIR         = ROOT / "content" / "diary"
PHOTOS_DIR        = ROOT / "content" / "photos"
PHOTOS_META_FILE  = PHOTOS_DIR / "metadata.json"   # 2001 archive (367 photos), kept for reference
MEDIA_FILE        = PHOTOS_DIR / "media.json"      # current archive, see scraper/process_highres.py
# Set DYNAMIC_MEDIA_BASE (e.g. "../../photos/") to let dist/dynamic/ link to the static
# package's photo files instead of carrying its own copy (used for the GitHub Pages deploy).
DYNAMIC_MEDIA_BASE = os.environ.get("DYNAMIC_MEDIA_BASE", "")
PRACTICAL_FILE    = ROOT / "content" / "practical.md"
DATA_DIR          = ROOT / "data"
STATIC_DIR        = ROOT / "dist" / "static"
DYNAMIC_DIR       = ROOT / "dist" / "dynamic"

# ---------------------------------------------------------------------------
# Markdown / frontmatter
# ---------------------------------------------------------------------------

MD = mdlib.Markdown(extensions=["nl2br", "tables"])

def parse_md(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, markdown_body) from a .md file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    _, raw_fm, body = text.split("---", 2)
    meta = {}
    for line in raw_fm.strip().splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"')
    return meta, body.strip()

def to_html(md_text: str) -> str:
    # The diary has no code: a tab-indented paragraph or a backtick used as an
    # apostrophe ("don`t") must not turn into <pre>/<code> blocks.
    md_text = re.sub(r"^[ \t]+(?=\S)(?![-*+] |\d+\. )", "", md_text, flags=re.M)
    md_text = md_text.replace("`", "\\`")
    MD.reset()
    html = MD.convert(md_text)
    # Tag paragraphs whose only content is bold text — these are sub-headers in the diary
    html = re.sub(r'<p>(<strong>[^<]*</strong>)\s*</p>', r'<p class="subhead">\1</p>', html)
    return html

def excerpt(html_text: str, length: int = 220) -> str:
    text = re.sub(r"<[^>]+>", "", html_text)
    text = text.strip()
    return text[:length] + ("…" if len(text) > length else "")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def fmt_display_date(date_str: str, title: str) -> str:
    """'2001-03-05' + '05.03.2001 Maanantai' → 'Ma 5.3.2001'  (keep original title)"""
    return title  # use original Finnish title as-is

# ---------------------------------------------------------------------------
# Phase 1 — build data/
# ---------------------------------------------------------------------------

def build_data(photos: list[dict]) -> list[dict]:
    DATA_DIR.mkdir(exist_ok=True)
    entries = []
    by_day: dict = {}
    for p in photos:
        if p.get("date"):
            by_day.setdefault(p["date"], []).append(
                {k: p[k] for k in ("id", "type", "thumb", "caption") if k in p})

    for md_file in sorted(DIARY_DIR.glob("*.md")):
        meta, body = parse_md(md_file)
        date       = meta.get("date", md_file.stem)
        title      = meta.get("title", date)
        body_html  = to_html(body)

        entry = {
            "date":     date,
            "title":    title,
            "excerpt":  excerpt(body_html),
            "filename": date,
        }
        entries.append(entry)

        entry_data = {
            "date":         date,
            "title":        title,
            "body_html":    body_html,
            "photos":       by_day.get(date, []),
            "original_url": meta.get("original_url", ""),
        }
        (DATA_DIR / f"{date}.json").write_text(
            json.dumps(entry_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (DATA_DIR / "entries.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # all.json — every entry with body_html, for the "show all" view
    all_data = []
    for md_file in sorted(DIARY_DIR.glob("*.md")):
        meta, body = parse_md(md_file)
        date      = meta.get("date", md_file.stem)
        title     = meta.get("title", date)
        all_data.append({"date": date, "title": title, "body_html": to_html(body)})
    (DATA_DIR / "all.json").write_text(
        json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # photos.json — the whole media archive; paths are relative to photos/
    public = ("id", "type", "file", "thumb", "poster", "date", "taken", "taken_estimated",
              "caption", "width", "height", "duration", "original")
    (DATA_DIR / "photos.json").write_text(
        json.dumps([{k: p[k] for k in public if k in p} for p in photos],
                   ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"data/  — {len(entries)} entries, {len(photos)} media items")
    return entries

# ---------------------------------------------------------------------------
# Photo helpers
# ---------------------------------------------------------------------------

def load_photos() -> list[dict]:
    """Media records: {id, type, file, thumb, poster?, date, taken, caption, ...}.

    Paths are relative to content/photos/ (and to photos/ in the built sites)."""
    if MEDIA_FILE.exists():
        return json.loads(MEDIA_FILE.read_text(encoding="utf-8"))
    if PHOTOS_META_FILE.exists():
        return [{"id": Path(p["filename"]).stem, "type": "image",
                 "file": f"full/{p['filename']}", "thumb": f"thumbnails/{p['filename']}",
                 "caption": p.get("caption") or "", "date": None}
                for p in json.loads(PHOTOS_META_FILE.read_text(encoding="utf-8"))]
    return []


def copy_gfx(dest_assets: Path) -> None:
    """Copy gfx/*.gif (4x buttons + hero) into dest_assets/gfx/."""
    src = ROOT / "gfx"
    dst = dest_assets / "gfx"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*-4x.gif"):
        shutil.copy2(f, dst / f.name)
    for name in ("hero.gif", "kumiankka_china_logo_vaaka.gif"):
        f = src / name
        if f.exists():
            shutil.copy2(f, dst / name)


def copy_photos_to(dest_dir: Path, photos: list[dict]) -> None:
    """Copy the photo subfolders the media records point to (highres/, full/, …)."""
    subs = {p[k].split("/")[0] for p in photos for k in ("file", "thumb", "poster") if p.get(k)}
    for sub in sorted(subs):
        src = PHOTOS_DIR / sub
        dst = dest_dir / sub
        if not src.exists():
            continue
        # Incremental sync: ~300 MB of media, so copy only new/changed files
        dst.mkdir(parents=True, exist_ok=True)
        wanted = set()
        for f in src.iterdir():
            if f.name.startswith("."):
                continue
            wanted.add(f.name)
            t = dst / f.name
            st = f.stat()
            if not t.exists() or t.stat().st_size != st.st_size or t.stat().st_mtime < st.st_mtime:
                shutil.copy2(f, t)
        for t in dst.iterdir():
            if t.name not in wanted:
                t.unlink()


# ---------------------------------------------------------------------------
# Phase 2 — dist/static/  (original design, works offline)
# ---------------------------------------------------------------------------

ORIG_CSS = """\
/* Faithfully reproduced from shanghai.css (kumiankka.org/china/_s/shanghai.css) */
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background-color: #E9CB9A;
  font-family: Verdana, Tahoma, Arial, sans-serif;
  font-size: 10px;
  color: #333333;
  margin: 10px 0;
}

a:link, a:visited { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 10px; color: #333333; text-decoration: underline; }
a:hover, a:active  { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 10px; color: #333333; text-decoration: none; }

.teksti       { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 10px; line-height: normal; color: #333333; }
.tekstibold   { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 12px; line-height: normal; color: #333333; font-weight: bold; }
.tekstiMini   { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 10px; line-height: normal; color: #333333; }
b             { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 10px; line-height: normal; color: #333333; font-weight: bold; }

/* Layout */
.page-wrap    { width: 800px; margin: 0 auto; border-left: 1px solid #482F09; border-right: 1px solid #482F09; }
.top-border   { background: #482F09; height: 1px; width: 800px; margin: 0 auto; }
.bottom-border{ background: #482F09; height: 1px; width: 800px; margin: 0 auto; }
.inner        { width: 698px; margin: 0 auto; padding: 0 10px; }

/* Hero image */
.hero-img { display: block; width: 100%; max-width: 800px; height: auto; }

/* Navigation */
.nav-row { padding: 6px 0 5px; }
.nav-inner { width: 698px; margin: 0 auto; padding: 0 10px; display: flex; gap: 6px; }
.nav-btn { display: block; width: 156px; height: auto; border: none; image-rendering: pixelated; }
.nav-row a { line-height: 0; }
.nav-row a:hover .nav-btn { opacity: 0.8; }

/* All-entries link (index page) */
.all-link { padding: 6px 20px 2px; font-size: 10px; }

/* Practical section title images */
.section-title-img { display: block; width: 466px; max-width: 100%; height: auto; image-rendering: pixelated; margin: 16px 0 8px; }

/* Entry list (index page) */
.entry-list { padding: 16px 20px; }
.entry-list table { border-collapse: collapse; width: 100%; }
.entry-list td { padding: 3px 6px 3px 0; vertical-align: top; }
.entry-list .date-col { white-space: nowrap; font-weight: bold; font-size: 13px; width: 160px; }
.entry-list .excerpt-col { color: #555; }
.entry-list tr:hover td { background: #DDB87A; }

/* Entry content */
.entry-wrap   { padding: 12px 20px 20px 20px; max-width: 550px; }
.entry-date   { font-size: 16px; font-weight: bold; color: #333; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #C4A87A; }
.entry-body   { font-size: 10px; line-height: 1.5; text-align: justify; }
.entry-body p { margin-bottom: 0.8em; }
.entry-body strong { font-size: 11px; font-weight: bold; }
.entry-body .subhead { margin-top: 1.4em; margin-bottom: 0.3em; }
.entry-body hr { border: none; border-top: 1px solid #C4A87A; margin: 12px 0; }
.entry-body ul, .entry-body ol { padding-left: 1.6em; margin-bottom: 0.8em; }
.entry-body li { margin-bottom: 0.2em; }

/* All-posts view date header (same as .entry-date now) */
.all-entry-date { font-size: 16px; font-weight: bold; color: #333; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #C4A87A; }

/* Prev/next navigation */
.entry-nav { padding: 10px 20px; border-top: 1px solid #C4A87A; margin-top: 10px; display: flex; gap: 6px; align-items: center; }
.entry-nav a { font-size: 10px; line-height: 0; }
.nav-arrow { display: block; width: 76px; height: auto; border: none; image-rendering: pixelated; }
.nav-arrow-inactive { opacity: 0.2; }

/* Day selector (index) */
.day-selector { padding: 8px 20px; border-bottom: 1px solid #C4A87A; }
.day-selector select { font-family: Verdana, Tahoma, Arial, sans-serif; font-size: 10px; border: 1px solid #666; padding: 1px; }

/* Footer */
.footer { padding: 8px 20px; border-top: 1px solid #C4A87A; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.footer-logo { width: 129px; height: auto; image-rendering: pixelated; flex-shrink: 0; }
.footer-copy { font-size: 9px; color: #888; text-align: right; }

/* Photo gallery */
.photo-grid { padding: 12px 20px; display: flex; flex-wrap: wrap; gap: 5px; }
.thumb-link img { width: 82px; height: 62px; object-fit: cover; border: 1px solid #8B6914; display: block; }
.thumb-link img:hover { border-color: #482F09; opacity: 0.8; }
.photo-wrap { padding: 12px 20px 4px; text-align: center; }
.photo-wrap img.photo-full { max-width: 100%; height: auto; border: 1px solid #8B6914; display: block; margin: 0 auto; }
.photo-link { line-height: 0; display: block; text-align: center; cursor: pointer; }
video.photo-full { display: block; width: 100%; max-width: 640px; height: auto; margin: 0 auto; border: 1px solid #8B6914; background: #000; }
.photo-meta { font-size: 9px; color: #888; margin-top: 4px; }
.photo-day { padding: 0 20px; }
.photo-day .photo-grid { padding: 4px 0 12px; }
.photo-day-title { font-size: 11px; font-weight: bold; border-bottom: 1px solid #C4A87A; padding: 8px 0 2px; }
.photo-day-title a:link, .photo-day-title a:visited { font-size: 11px; font-weight: bold; }
.photo-day-count { font-weight: normal; color: #888; }
.day-photos { padding: 0 20px 8px; }
.day-photos-title { font-size: 11px; font-weight: bold; border-bottom: 1px solid #C4A87A; padding: 4px 0 2px; }
.day-photos .photo-grid { padding: 6px 0 4px; }
.thumb-link { position: relative; line-height: 0; }
.thumb-link.is-video::after { content: "▶"; position: absolute; right: 3px; bottom: 3px; font-size: 10px; line-height: 1; color: #fff; text-shadow: 0 0 2px #000; }
.photo-caption { font-size: 10px; color: #555; margin-top: 6px; }
.photo-number { font-size: 9px; color: #888; margin-bottom: 4px; }

/* ---- Responsive: tablets and phones (desktop keeps the original 800px layout) ---- */
img, video { max-width: 100%; }
.entry-body, .photo-caption, .entry-list td { overflow-wrap: anywhere; }
.entry-body table { display: block; max-width: 100%; overflow-x: auto; }

@media (max-width: 820px) {
  body { margin: 0; }
  .page-wrap, .top-border, .bottom-border { width: auto; max-width: 800px; }
  .page-wrap { border-left: 0; border-right: 0; }
  .inner, .nav-inner { width: auto; max-width: 698px; }
  .nav-inner a { flex: 1 1 0; min-width: 0; max-width: 156px; }
  .nav-btn { width: 100%; }
}

@media (max-width: 600px) {
  .inner { padding: 0; }
  .nav-inner { padding: 0 12px; }
  .entry-wrap, .entry-list, .day-selector, .all-link, .entry-nav, .footer,
  .photo-day, .day-photos, .photo-wrap { padding-left: 12px; padding-right: 12px; }
  .entry-wrap { max-width: none; }

  /* Readable text: the 2001 design uses 10px Verdana everywhere */
  a:link, a:visited, a:hover, a:active { font-size: inherit; }
  .entry-body { font-size: 15px; line-height: 1.6; text-align: left; }
  .entry-body strong { font-size: 15px; }
  .entry-date, .all-entry-date { font-size: 18px; }
  .all-link { font-size: 14px; }
  .day-selector select { font-size: 16px; max-width: 70%; }

  .entry-list table, .entry-list tbody, .entry-list tr, .entry-list td { display: block; width: auto; }
  .entry-list tr { border-bottom: 1px solid #C4A87A; padding: 8px 0; }
  .entry-list td { padding: 0; }
  .entry-list .date-col { font-size: 15px; white-space: normal; }
  .entry-list .excerpt-col { font-size: 13px; line-height: 1.4; margin-top: 2px; }

  .photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); gap: 5px; }
  .thumb-link img { width: 100%; height: auto; aspect-ratio: 4 / 3; }
  .photo-day-title, .photo-day-title a:link, .photo-day-title a:visited,
  .day-photos-title { font-size: 14px; }
  .photo-caption { font-size: 14px; }
  .photo-meta, .photo-number { font-size: 12px; }

  .footer { flex-wrap: wrap; }
  .footer-copy { font-size: 11px; }
}
"""

def page_shell(title: str, content: str, root: str = "") -> str:
    """Wrap content in the full page shell with header/nav."""
    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{htmlmod.escape(title)} — chinese people...</title>
  <link rel="stylesheet" href="{root}assets/style.css">
</head>
<body>
<div class="top-border"></div>
<div class="page-wrap">
  <img src="{root}assets/gfx/hero.gif" alt="chinese people..." class="hero-img">
  <div class="nav-row">
    <div class="nav-inner">
      <a href="{root}index.html"><img src="{root}assets/gfx/diary-4x.gif" alt="the diary" class="nav-btn"></a>
      <a href="{root}photos/index.html"><img src="{root}assets/gfx/photoarchive-4x.gif" alt="photoarchive" class="nav-btn"></a>
      <a href="{root}practical.html"><img src="{root}assets/gfx/practical_chinese-4x.gif" alt="practical chinese" class="nav-btn"></a>
    </div>
  </div>
  <div class="inner">
    {content}
    <div class="footer">
      <img src="{root}assets/gfx/kumiankka_china_logo_vaaka.gif" alt="kumiankka.org" class="footer-logo">
      <span class="footer-copy">© kumiankka.org 2001 – Remastered 2026</span>
    </div>
  </div>
</div>
<div class="bottom-border"></div>
<script>
document.addEventListener('keydown', function(e) {{
  var spans = document.querySelectorAll('.entry-nav > span');
  if (!spans.length) return;
  if (e.key === 'ArrowLeft') {{ var a = spans[0].querySelector('a'); if (a) location.href = a.href; }}
  else if (e.key === 'ArrowRight') {{ var a = spans[spans.length-1].querySelector('a'); if (a) location.href = a.href; }}
}});
</script>
</body>
</html>"""


def build_static_index(entries: list[dict]) -> None:
    # Build JS-powered day selector that mirrors the original dropdown
    options = "\n".join(
        f'<option value="{e["filename"]}.html">{htmlmod.escape(e["title"])}</option>'
        for e in entries
    )
    rows = "\n".join(
        f"""<tr>
          <td class="date-col"><a href="{e['filename']}.html">{htmlmod.escape(e['title'])}</a></td>
          <td class="excerpt-col">{htmlmod.escape(e['excerpt'][:120])}…</td>
        </tr>"""
        for e in entries
    )
    content = f"""
    <div class="day-selector">
      <form onsubmit="location.href=this.day.value;return false;">
        &nbsp;
        <select name="day">
          <option value="">— Valitse päivä —</option>
          {options}
        </select>
        <input type="image" src="assets/gfx/go_button-4x.gif" alt="Vaihda päivää" style="width:58px;height:auto;image-rendering:pixelated;vertical-align:middle;border:none;">
      </form>
    </div>
    <div class="all-link"><a href="all.html">↓ kaikki merkinnät auki</a></div>
    <div class="entry-list">
      <table>
        {rows}
      </table>
    </div>"""
    write(STATIC_DIR / "index.html", page_shell("diary", content))


def build_static_entry(entry: dict, body_html: str,
                        prev_e: dict | None, next_e: dict | None,
                        day_photos: list[dict] = ()) -> None:
    prev_btn = (f'<a href="{prev_e["filename"]}.html"><img src="assets/gfx/previous-4x.gif" alt="edellinen" class="nav-arrow"></a>'
                if prev_e else '<img src="assets/gfx/previous-4x.gif" alt="" class="nav-arrow nav-arrow-inactive">')
    next_btn = (f'<a href="{next_e["filename"]}.html"><img src="assets/gfx/next-4x.gif" alt="seuraava" class="nav-arrow"></a>'
                if next_e else '<img src="assets/gfx/next-4x.gif" alt="" class="nav-arrow nav-arrow-inactive">')
    content = f"""
    <div class="entry-wrap">
      <div class="entry-date">{htmlmod.escape(entry['title'])}</div>
      <div class="entry-body">{body_html}</div>
    </div>
    {day_photos_html(list(day_photos), "photos/", "photos/")}
    <div class="entry-nav">
      <span>{prev_btn}</span>
      <span><a href="index.html"><img src="assets/gfx/index_button-4x.gif" alt="kaikki päivät" class="nav-arrow"></a></span>
      <span>{next_btn}</span>
    </div>"""
    write(STATIC_DIR / f"{entry['filename']}.html",
          page_shell(entry["title"], content))


def build_static_all(entries: list[dict], by_day: dict) -> None:
    """Generate all.html — all 80 entries expanded on one page."""
    blocks = []
    for entry in entries:
        meta, body = parse_md(DIARY_DIR / f"{entry['filename']}.md")
        body_html  = to_html(body)
        blocks.append(f"""<div class="entry-wrap">
      <div class="all-entry-date"><a href="{entry['filename']}.html">{htmlmod.escape(entry['title'])}</a></div>
      <div class="entry-body">{body_html}</div>
    </div>
    {day_photos_html(by_day.get(entry['filename'], []), "photos/", "photos/")}""")
    sep = '<hr style="border:none;border-top:1px solid #C4A87A;margin:4px 0;">'
    content = sep.join(blocks)
    write(STATIC_DIR / "all.html", page_shell("kaikki merkinnät", content))


def build_static(entries: list[dict], photos: list[dict]) -> None:
    # CSS + gfx
    write(STATIC_DIR / "assets" / "style.css", ORIG_CSS)
    copy_gfx(STATIC_DIR / "assets")

    # Index
    build_static_index(entries)

    by_day: dict = {}
    for p in photos:
        if p.get("date"):
            by_day.setdefault(p["date"], []).append(p)

    # Per-entry pages
    for i, entry in enumerate(entries):
        meta, body = parse_md(DIARY_DIR / f"{entry['filename']}.md")
        body_html  = to_html(body)
        prev_e     = entries[i - 1] if i > 0 else None
        next_e     = entries[i + 1] if i < len(entries) - 1 else None
        build_static_entry(entry, body_html, prev_e, next_e, by_day.get(entry["filename"], []))

    build_static_all(entries, by_day)
    print(f"dist/static/  — {len(entries)} entry pages + index + all.html")


def fmt_taken(p: dict) -> str:
    """'2001-03-06T08:33' → 'klo 08.33' (prefixed with ~ when estimated)."""
    t = p.get("taken")
    if not t:
        return ""
    return ("noin " if p.get("taken_estimated") else "") + "klo " + t[11:16].replace(":", ".")


def media_tag(p: dict, base: str, next_href: str) -> str:
    """Big image (click → next) or native <video> for a media record."""
    cap = htmlmod.escape(p.get("caption") or "")
    if p.get("type") == "video":
        return (f'<video class="photo-full photo-video" controls preload="none" playsinline '
                f'poster="{base}{p["poster"]}"><source src="{base}{p["file"]}" type="video/mp4">'
                f'<a href="{base}{p["file"]}">Lataa video</a></video>')
    return (f'<a href="{next_href}" title="seuraava kuva" class="photo-link">'
            f'<img src="{base}{p["file"]}" class="photo-full" alt="{cap}"></a>')


def media_meta(p: dict, base: str, diary_href: str, day_title: str) -> str:
    """Date/time line under the photo, linking to that day's diary entry."""
    bits = []
    if p.get("date"):
        bits.append(f'<a href="{diary_href}">{htmlmod.escape(day_title or p["date"])}</a>')
    if fmt_taken(p):
        bits.append(fmt_taken(p))
    if p.get("type") == "video" and p.get("duration"):
        bits.append(f'video {p["duration"]:.0f} s')
    elif p.get("width"):
        bits.append(f'<a href="{base}{p["file"]}">täysikokoinen ({p["width"]}×{p["height"]})</a>')
    return f'<div class="photo-meta">{" · ".join(bits)}</div>' if bits else ""


def thumb_link(p: dict, base: str) -> str:
    cap = htmlmod.escape(p.get("caption") or "")
    cls = "thumb-link is-video" if p.get("type") == "video" else "thumb-link"
    return (f'<a href="{p["id"]}.html" class="{cls}">'
            f'<img src="{base}{p["thumb"]}" loading="lazy" alt="{cap}" title="{cap}"></a>')


def photo_grid_by_day(photos: list[dict], base: str, titles: dict, diary_href) -> str:
    """Thumbnail grid grouped under one heading per diary day."""
    groups: dict = {}
    for p in photos:
        groups.setdefault(p.get("date"), []).append(p)
    out = []
    for date, items in groups.items():
        thumbs = "\n".join(thumb_link(p, base) for p in items)
        if date:
            head = (f'<div class="photo-day-title"><a href="{diary_href(date)}">'
                    f'{htmlmod.escape(titles.get(date, date))}</a>'
                    f' <span class="photo-day-count">{len(items)}</span></div>')
        else:
            head = ""
        out.append(f'<div class="photo-day" id="d{date or "x"}">{head}<div class="photo-grid">{thumbs}</div></div>')
    return "\n".join(out)


def day_photos_html(items: list[dict], page_prefix: str, media_prefix: str) -> str:
    """Thumbnail grid shown under a diary entry. page_prefix/media_prefix point to photos/."""
    if not items:
        return ""
    n_vid = sum(p.get("type") == "video" for p in items)
    label = f"{len(items) - n_vid} kuvaa" + (f", {n_vid} videota" if n_vid else "")
    thumbs = "\n".join(
        thumb_link(p, media_prefix).replace(f'href="{p["id"]}.html"', f'href="{page_prefix}{p["id"]}.html"')
        for p in items)
    return (f'<div class="day-photos"><div class="day-photos-title">Päivän kuvat '
            f'<span class="photo-day-count">{label}</span></div>'
            f'<div class="photo-grid">{thumbs}</div></div>')


def archive_summary(photos: list[dict]) -> str:
    n_vid = sum(p.get("type") == "video" for p in photos)
    s = f"{len(photos) - n_vid} photos"
    return s + (f", {n_vid} videos" if n_vid else "")


def build_static_photos(photos: list[dict], titles: dict, media_base: str = "") -> None:
    photos_dir = STATIC_DIR / "photos"
    if not media_base:
        copy_photos_to(photos_dir, photos)
    base = media_base

    for i, p in enumerate(photos):
        prev_p = photos[i - 1] if i > 0 else None
        next_p = photos[i + 1] if i < len(photos) - 1 else None
        prev_btn = (f'<a href="{prev_p["id"]}.html"><img src="../assets/gfx/previous-4x.gif" alt="edellinen" class="nav-arrow"></a>'
                    if prev_p else '<img src="../assets/gfx/previous-4x.gif" alt="" class="nav-arrow nav-arrow-inactive">')
        next_btn = (f'<a href="{next_p["id"]}.html"><img src="../assets/gfx/next-4x.gif" alt="seuraava" class="nav-arrow"></a>'
                    if next_p else '<img src="../assets/gfx/next-4x.gif" alt="" class="nav-arrow nav-arrow-inactive">')
        next_href = f'{next_p["id"]}.html' if next_p else "index.html"
        cap = htmlmod.escape(p.get("caption") or "")
        date = p.get("date")
        content = f"""
    <div class="entry-nav">
      <span>{prev_btn}</span>
      <span><a href="index.html#d{date or 'x'}"><img src="../assets/gfx/index_button-4x.gif" alt="kaikki kuvat" class="nav-arrow"></a></span>
      <span>{next_btn}</span>
    </div>
    <div class="photo-wrap">
      <div class="photo-number">{i + 1} / {len(photos)}</div>
      {media_tag(p, base, next_href)}
      {f'<div class="photo-caption">{cap}</div>' if cap else ''}
      {media_meta(p, base, f"../{date}.html", titles.get(date, ""))}
    </div>"""
        write(photos_dir / f"{p['id']}.html", page_shell(p["id"], content, root="../"))

    grid = photo_grid_by_day(photos, base, titles, lambda d: f"../{d}.html")
    content = f"""
    <div class="entry-wrap">
      <div class="entry-date">Photo archive — {archive_summary(photos)}</div>
    </div>
    {grid}"""
    write(photos_dir / "index.html", page_shell("photoarchive", content, root="../"))
    print(f"dist/static/photos/  — {len(photos)} photo pages + grid")


# ---------------------------------------------------------------------------
# Phase 3 — dist/dynamic/  (JS app for webserver)
# ---------------------------------------------------------------------------

DYNAMIC_CSS = """\
/* China Diary — dynamic reader (modern typography) */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #E9CB9A;
  --bg-header: #3A2208;
  --border:    #C4A060;
  --text:      #2A1F0E;
  --muted:     #7A6040;
  --accent:    #8B5A1A;
  --link:      #5C3A0A;
  --max-w:     680px;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 16px;
  line-height: 1.7;
  padding: 0;
}

/* Hero + nav */
.site-frame { max-width: 800px; margin: 0 auto; }
.hero-img { display: block; width: 100%; height: auto; }

nav { padding: 6px 0 5px; }
.nav-inner { max-width: var(--max-w); margin: 0 auto; padding: 0 24px; display: flex; gap: 6px; }
.nav-btn { display: block; width: 156px; height: auto; border: none; image-rendering: pixelated; }
nav a { line-height: 0; }
nav a:hover .nav-btn { opacity: 0.8; }

/* All-entries link */
.all-link { font-family: sans-serif; font-size: 13px; margin: 0 0 8px; }
.all-link a { color: var(--link); }

/* List indentation fix (CSS reset strips padding) */
#entry-view ul, #entry-view ol,
#all-view ul,   #all-view ol   { padding-left: 1.6em; margin-bottom: 1em; }
#entry-view li, #all-view li   { margin-bottom: 0.2em; }
#all-view strong { font-style: italic; font-size: 15px; color: var(--accent); }
#all-view .subhead { margin-top: 1.6em; margin-bottom: 0.2em; }
#all-view p { margin-bottom: 1em; text-align: justify; }

/* All-posts date header */
.all-entry-date { font-size: 20px; font-weight: normal; font-style: italic; color: var(--accent); margin-bottom: 12px; }

/* Practical section title images */
.section-title-img { display: block; width: 466px; max-width: 100%; height: auto; image-rendering: pixelated; margin: 20px 0 10px; }

main { max-width: var(--max-w); margin: 0 auto; padding: 32px 24px; }

/* Entry list */
#entry-list { list-style: none; }
#entry-list li { border-bottom: 1px solid var(--border); padding: 10px 0; }
#entry-list li a { text-decoration: none; color: var(--text); display: flex; gap: 16px; }
#entry-list li a:hover .entry-title { text-decoration: underline; }
.entry-date-label { font-family: sans-serif; font-size: 12px; color: var(--muted); min-width: 150px; padding-top: 2px; }
.entry-title { font-size: 16px; }
.entry-excerpt { font-size: 13px; color: var(--muted); font-family: sans-serif; line-height: 1.4; margin-top: 3px; }

/* Single entry */
#entry-view h2 { font-size: 20px; font-weight: normal; font-style: italic; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 20px; }
#entry-view p  { margin-bottom: 1em; text-align: justify; }
#entry-view strong { font-style: italic; font-size: 15px; color: var(--accent); }
#entry-view .subhead { margin-top: 1.6em; margin-bottom: 0.2em; }
#entry-view hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }

/* Entry navigation */
#entry-nav { display: flex; gap: 6px; align-items: center; margin-top: 32px; padding-top: 12px; border-top: 1px solid var(--border); }
#entry-nav a { color: var(--link); text-decoration: none; line-height: 0; }
#entry-nav a:hover { text-decoration: none; }
#entry-nav a:hover .nav-arrow { opacity: 0.7; }
.nav-arrow { display: block; width: 76px; height: auto; border: none; image-rendering: pixelated; }
.nav-arrow-inactive { opacity: 0.2; }

/* Loading */
#loading { text-align: center; color: var(--muted); font-family: sans-serif; padding: 40px; }

footer { max-width: var(--max-w); margin: 0 auto; padding: 0 24px 12px; }
.footer-inner { border-top: 1px solid var(--border); padding-top: 12px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.footer-logo { width: 129px; height: auto; image-rendering: pixelated; flex-shrink: 0; }
.footer-copy { font-family: sans-serif; font-size: 12px; color: var(--muted); text-align: right; }

/* Photo gallery */
.photo-grid { display: flex; flex-wrap: wrap; gap: 8px; padding: 24px 0; }
.thumb-link img { width: 90px; height: 68px; object-fit: cover; border: 1px solid var(--border); display: block; transition: opacity 0.15s; }
.thumb-link img:hover { opacity: 0.75; }
.photo-wrap { padding: 0 0 20px; text-align: center; }
.photo-wrap img.photo-full { max-width: 100%; height: auto; border: 1px solid var(--border); display: block; margin: 0 auto; }
.photo-link { line-height: 0; display: block; text-align: center; cursor: pointer; }
video.photo-full { display: block; width: 100%; max-width: 720px; height: auto; margin: 0 auto; border: 1px solid var(--border); background: #000; }
.photo-meta { font-family: sans-serif; font-size: 12px; color: var(--muted); margin-top: 6px; }
.photo-meta a { color: inherit; }
.photo-day-title { font-size: 15px; border-bottom: 1px solid var(--border); padding: 18px 0 4px; }
.photo-day-title a { color: var(--accent); text-decoration: none; }
.photo-day-count { font-family: sans-serif; font-size: 12px; color: var(--muted); }
.day-photos { margin-top: 28px; }
.day-photos-title { font-size: 15px; font-style: italic; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 4px; }
.day-photos .photo-grid { padding: 10px 0 0; }
.photo-day .photo-grid { padding: 10px 0 4px; }
.thumb-link { position: relative; line-height: 0; }
.thumb-link.is-video::after { content: "▶"; position: absolute; right: 4px; bottom: 4px; font-size: 12px; line-height: 1; color: #fff; text-shadow: 0 0 3px #000; }
.photo-caption { font-size: 14px; color: var(--muted); margin-top: 10px; font-style: italic; }
.photo-number { font-family: sans-serif; font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.photo-page-title { font-size: 18px; font-weight: normal; font-style: italic; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 20px; }

/* ---- Responsive: tablets and phones ---- */
img, video { max-width: 100%; }
#entry-view, #all-view, .photo-caption { overflow-wrap: anywhere; }
#entry-view table, #all-view table, main table { display: block; max-width: 100%; overflow-x: auto; }

@media (max-width: 760px) {
  nav a { flex: 1 1 0; min-width: 0; max-width: 156px; }
  .nav-btn { width: 100%; }
}

@media (max-width: 600px) {
  main { padding: 20px 16px; }
  .nav-inner { padding: 0 16px; }
  footer { padding: 0 16px 12px; }
  .footer-inner { flex-wrap: wrap; }
  #entry-view p, #all-view p { text-align: left; }
  #entry-list li a { flex-direction: column; gap: 2px; }
  .entry-date-label { min-width: 0; }
  .photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); gap: 6px; }
  .thumb-link img { width: 100%; height: auto; aspect-ratio: 4 / 3; }
}
"""

DYNAMIC_JS = r"""
// China Diary — dynamic reader
// Fetches data/*.json at runtime; requires a web server.

const DATA_BASE = 'data/';
const PHOTO_PAGES = 'photos/';           // photo pages of this package
const MEDIA_BASE  = '__MEDIA_BASE__';    // where the image files live (set by build.py)

let _entries  = null;   // cached entries list
let _curDate  = null;   // currently viewed entry date

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

function el(id) { return document.getElementById(id); }

function setTitle(t) {
  document.title = t + ' — chinese people...';
}

// ---- Entry list ----
async function showIndex() {
  el('entry-view').style.display = 'none';
  el('entry-nav').style.display  = 'none';
  el('all-view').style.display   = 'none';
  el('loading').style.display    = 'block';
  el('entry-list').innerHTML     = '';

  _curDate = null;
  setTitle('diary');
  try {
    const entries = await fetchJson(DATA_BASE + 'entries.json');
    _entries = entries;
    el('loading').style.display   = 'none';
    el('all-link').style.display  = 'block';
    const ul = el('entry-list');
    entries.forEach(e => {
      const li = document.createElement('li');
      li.innerHTML = `<a href="#${e.filename}">
        <div>
          <div class="entry-title">${esc(e.title)}</div>
          <div class="entry-excerpt">${esc(e.excerpt)}</div>
        </div>
      </a>`;
      ul.appendChild(li);
    });
  } catch(err) {
    el('loading').textContent = 'Error loading entries: ' + err.message;
  }
}

// ---- All entries ----
async function showAll() {
  el('entry-list').innerHTML  = '';
  el('all-link').style.display  = 'none';
  el('entry-view').style.display = 'none';
  el('entry-nav').style.display  = 'none';
  el('loading').style.display    = 'block';
  el('all-view').style.display   = 'none';

  _curDate = null;
  setTitle('kaikki merkinnät');
  try {
    const all = await fetchJson(DATA_BASE + 'all.json');
    el('loading').style.display = 'none';
    const div = el('all-view');
    div.innerHTML = all.map(e =>
      `<div class="entry-wrap" id="${e.date}">
        <div class="all-entry-date">
          <a href="#${e.date}" style="color:inherit;text-decoration:none;">${esc(e.title)}</a>
        </div>
        ${e.body_html}
        <hr style="border:none;border-top:1px solid var(--border);margin:20px 0 4px;">
      </div>`
    ).join('');
    div.style.display = 'block';
  } catch(err) {
    el('loading').textContent = 'Error: ' + err.message;
  }
}

// ---- Single entry ----
async function showEntry(date) {
  el('entry-list').innerHTML     = '';
  el('all-link').style.display   = 'none';
  el('all-view').style.display   = 'none';
  el('entry-view').style.display = 'none';
  el('loading').style.display    = 'block';

  try {
    const [entries, entry] = await Promise.all([
      fetchJson(DATA_BASE + 'entries.json'),
      fetchJson(DATA_BASE + date + '.json'),
    ]);
    _entries = entries;
    _curDate = date;
    el('loading').style.display = 'none';
    setTitle(entry.title);

    el('entry-view').innerHTML = `<h2>${esc(entry.title)}</h2>${entry.body_html}${dayPhotos(entry.photos)}`;
    el('entry-view').style.display = 'block';

    // Prev / next
    const idx  = entries.findIndex(e => e.filename === date);
    const prev = entries[idx - 1];
    const next = entries[idx + 1];
    el('entry-nav').innerHTML =
      `<span>${prev ? `<a href="#${prev.filename}"><img src="assets/gfx/previous-4x.gif" class="nav-arrow" alt="edellinen"></a>` : '<img src="assets/gfx/previous-4x.gif" class="nav-arrow nav-arrow-inactive" alt="">'}</span>
       <span><a href="#"><img src="assets/gfx/index_button-4x.gif" class="nav-arrow" alt="kaikki päivät"></a></span>
       <span>${next ? `<a href="#${next.filename}"><img src="assets/gfx/next-4x.gif" class="nav-arrow" alt="seuraava"></a>` : '<img src="assets/gfx/next-4x.gif" class="nav-arrow nav-arrow-inactive" alt="">'}</span>`;
    el('entry-nav').style.display = 'flex';
  } catch(err) {
    el('loading').textContent = 'Error: ' + err.message;
  }
}

function dayPhotos(items) {
  if (!items || !items.length) return '';
  const vids = items.filter(p => p.type === 'video').length;
  const label = `${items.length - vids} kuvaa` + (vids ? `, ${vids} videota` : '');
  const thumbs = items.map(p => {
    const cap = esc(p.caption || '');
    return `<a href="${PHOTO_PAGES}${p.id}.html" class="thumb-link${p.type === 'video' ? ' is-video' : ''}">` +
           `<img src="${MEDIA_BASE}${p.thumb}" loading="lazy" alt="${cap}" title="${cap}"></a>`;
  }).join('');
  return `<div class="day-photos"><div class="day-photos-title">Päivän kuvat ` +
         `<span class="photo-day-count">${label}</span></div><div class="photo-grid">${thumbs}</div></div>`;
}

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---- Router ----
function route() {
  const hash = location.hash.slice(1);
  if (hash === 'all') {
    showAll();
  } else if (hash && /^\d{4}-\d{2}-\d{2}$/.test(hash)) {
    showEntry(hash);
  } else {
    showIndex();
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('load', route);

// Keyboard navigation for diary entries
document.addEventListener('keydown', function(e) {
  if (!_curDate || !_entries) return;
  const idx = _entries.findIndex(en => en.filename === _curDate);
  if (idx < 0) return;
  if (e.key === 'ArrowLeft' && idx > 0)
    location.hash = _entries[idx - 1].filename;
  else if (e.key === 'ArrowRight' && idx < _entries.length - 1)
    location.hash = _entries[idx + 1].filename;
});
"""

DYNAMIC_HTML = """<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>chinese people...</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <div class="site-frame">
    <img src="assets/gfx/hero.gif" alt="chinese people..." class="hero-img">
    <nav>
      <div class="nav-inner">
        <a href="#"><img src="assets/gfx/diary-4x.gif" alt="the diary" class="nav-btn"></a>
        <a href="photos/index.html"><img src="assets/gfx/photoarchive-4x.gif" alt="photoarchive" class="nav-btn"></a>
        <a href="practical.html"><img src="assets/gfx/practical_chinese-4x.gif" alt="practical chinese" class="nav-btn"></a>
      </div>
    </nav>
  </div>
  <main>
    <div id="loading">Loading…</div>
    <div id="all-link" style="display:none"><p class="all-link"><a href="#all">↓ kaikki merkinnät auki</a></p></div>
    <ul id="entry-list"></ul>
    <div id="entry-view" style="display:none"></div>
    <div id="entry-nav"  style="display:none"></div>
    <div id="all-view"   style="display:none"></div>
  </main>
  <footer>
    <div class="footer-inner">
      <img src="assets/gfx/kumiankka_china_logo_vaaka.gif" alt="kumiankka.org" class="footer-logo">
      <span class="footer-copy">© kumiankka.org 2001 – Remastered 2026</span>
    </div>
  </footer>
  <script src="assets/app.js"></script>
</body>
</html>"""


PRACTICAL_SECTION_IMGS = {
    "Practical Chinese for Practical People": "practical_chisense_title-4x.gif",
    "Practical Italiano":                     "practical_italianos-4x.gif",
    "Practical Tampere":                      "practical_tampere-4x.gif",
}


def inject_section_imgs(html: str, gfx_root: str) -> str:
    """Replace <h2>Section Title</h2> with the corresponding pixel-art header image."""
    for title, imgfile in PRACTICAL_SECTION_IMGS.items():
        html = html.replace(
            f"<h2>{title}</h2>",
            f'<img src="{gfx_root}{imgfile}" alt="{title}" class="section-title-img">',
        )
    return html


def build_practical() -> None:
    """Generate practical.html for both static and dynamic packages."""
    if not PRACTICAL_FILE.exists():
        print("practical/ — content/practical.md not found, skipping")
        return

    meta, body = parse_md(PRACTICAL_FILE)
    title     = meta.get("title", "practikal chinese for practikal people")
    body_html = to_html(body)

    # Static — inject section title images (gfx is at assets/gfx/ relative to site root)
    static_body = inject_section_imgs(body_html, "assets/gfx/")
    content = f"""
    <div class="entry-wrap">
      <div class="entry-date">{htmlmod.escape(title)}</div>
      <div class="entry-body">{static_body}</div>
    </div>"""
    write(STATIC_DIR / "practical.html", page_shell(title, content))

    # Dynamic — inject section title images (gfx is at assets/gfx/ relative to site root)
    dyn_body = inject_section_imgs(body_html, "assets/gfx/")
    dyn_content = f"""
    <div id="practical-body">{dyn_body}</div>"""
    dyn_html = f"""<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{htmlmod.escape(title)} — chinese people...</title>
  <link rel="stylesheet" href="assets/style.css">
  <style>
    #practical-body p  {{ margin-bottom:0.6em; }}
    #practical-body ul {{ margin:0 0 1em 1.2em; }}
    #practical-body li {{ margin-bottom:0.25em; font-family:sans-serif; font-size:14px; }}
    #practical-body strong {{ font-style:normal; font-size:14px; color:var(--accent); }}
  </style>
</head>
<body>
  <div class="site-frame">
    <img src="assets/gfx/hero.gif" alt="chinese people..." class="hero-img">
    <nav>
      <div class="nav-inner">
        <a href="index.html"><img src="assets/gfx/diary-4x.gif" alt="the diary" class="nav-btn"></a>
        <a href="photos/index.html"><img src="assets/gfx/photoarchive-4x.gif" alt="photoarchive" class="nav-btn"></a>
        <a href="practical.html"><img src="assets/gfx/practical_chinese-4x.gif" alt="practical chinese" class="nav-btn"></a>
      </div>
    </nav>
  </div>
  <main>
    {dyn_content}
  </main>
  <footer>
    <div class="footer-inner">
      <img src="assets/gfx/kumiankka_china_logo_vaaka.gif" alt="kumiankka.org" class="footer-logo">
      <span class="footer-copy">© kumiankka.org 2001 – Remastered 2026</span>
    </div>
  </footer>
</body>
</html>"""
    write(DYNAMIC_DIR / "practical.html", dyn_html)
    print(f"practical.html — generated for both packages")


def dyn_photo_shell(title: str, content: str) -> str:
    """Minimal HTML shell for dynamic photo pages (shares assets/style.css)."""
    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{htmlmod.escape(title)} — chinese people...</title>
  <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
  <div class="site-frame">
    <img src="../assets/gfx/hero.gif" alt="chinese people..." class="hero-img">
    <nav>
      <div class="nav-inner">
        <a href="../index.html"><img src="../assets/gfx/diary-4x.gif" alt="the diary" class="nav-btn"></a>
        <a href="index.html"><img src="../assets/gfx/photoarchive-4x.gif" alt="photoarchive" class="nav-btn"></a>
        <a href="../practical.html"><img src="../assets/gfx/practical_chinese-4x.gif" alt="practical chinese" class="nav-btn"></a>
      </div>
    </nav>
  </div>
  <main>
    {content}
  </main>
  <footer>
    <div class="footer-inner">
      <img src="../assets/gfx/kumiankka_china_logo_vaaka.gif" alt="kumiankka.org" class="footer-logo">
      <span class="footer-copy">© kumiankka.org 2001 – Remastered 2026</span>
    </div>
  </footer>
</body>
</html>"""


def build_dynamic_photos(photos: list[dict], titles: dict, media_base: str = "") -> None:
    photos_dir = DYNAMIC_DIR / "photos"
    if not media_base:
        copy_photos_to(photos_dir, photos)
    base = media_base

    for i, p in enumerate(photos):
        prev_p = photos[i - 1] if i > 0 else None
        next_p = photos[i + 1] if i < len(photos) - 1 else None
        prev_btn = (f'<a href="{prev_p["id"]}.html"><img src="../assets/gfx/previous-4x.gif" class="nav-arrow" alt="edellinen"></a>'
                    if prev_p else '<img src="../assets/gfx/previous-4x.gif" class="nav-arrow nav-arrow-inactive" alt="">')
        next_btn = (f'<a href="{next_p["id"]}.html"><img src="../assets/gfx/next-4x.gif" class="nav-arrow" alt="seuraava"></a>'
                    if next_p else '<img src="../assets/gfx/next-4x.gif" class="nav-arrow nav-arrow-inactive" alt="">')
        next_href = f'{next_p["id"]}.html' if next_p else "index.html"
        cap = htmlmod.escape(p.get("caption") or "")
        date = p.get("date")
        content = f"""
    <div id="entry-nav">
      <span>{prev_btn}</span>
      <span><a href="index.html#d{date or 'x'}"><img src="../assets/gfx/index_button-4x.gif" class="nav-arrow" alt="kaikki kuvat"></a></span>
      <span>{next_btn}</span>
    </div>
    <p class="photo-number">{i + 1} / {len(photos)}</p>
    <div class="photo-wrap">
      {media_tag(p, base, next_href)}
      {f'<p class="photo-caption">{cap}</p>' if cap else ''}
      {media_meta(p, base, f"../index.html#{date}", titles.get(date, ""))}
    </div>
    <script>
    document.addEventListener('keydown', function(e) {{
      var spans = document.querySelectorAll('#entry-nav > span');
      if (!spans.length) return;
      if (e.key === 'ArrowLeft') {{ var a = spans[0].querySelector('a'); if (a) location.href = a.href; }}
      else if (e.key === 'ArrowRight') {{ var a = spans[spans.length-1].querySelector('a'); if (a) location.href = a.href; }}
    }});
    </script>"""
        write(photos_dir / f"{p['id']}.html", dyn_photo_shell(p["id"], content))

    grid = photo_grid_by_day(photos, base, titles, lambda d: f"../index.html#{d}")
    index_content = f"""
    <h2 class="photo-page-title">Photo archive — {archive_summary(photos)}</h2>
    {grid}"""
    # dyn_photo_shell already links the photoarchive nav button to index.html (this page)
    write(photos_dir / "index.html", dyn_photo_shell("photoarchive", index_content))
    print(f"dist/dynamic/photos/ — {len(photos)} photo pages + grid")


def build_dynamic(entries: list[dict], photos: list[dict]) -> None:
    write(DYNAMIC_DIR / "index.html",           DYNAMIC_HTML)
    write(DYNAMIC_DIR / "assets" / "style.css", DYNAMIC_CSS)
    # DYNAMIC_MEDIA_BASE is relative to photos/*.html; app.js runs one level up.
    js_media = DYNAMIC_MEDIA_BASE[3:] if DYNAMIC_MEDIA_BASE.startswith("../") else "photos/"
    write(DYNAMIC_DIR / "assets" / "app.js",    DYNAMIC_JS.replace("__MEDIA_BASE__", js_media))
    copy_gfx(DYNAMIC_DIR / "assets")

    # Copy data/ into dist/dynamic/data/
    dyn_data = DYNAMIC_DIR / "data"
    if dyn_data.exists():
        shutil.rmtree(dyn_data)
    shutil.copytree(DATA_DIR, dyn_data)

    print(f"dist/dynamic/ — SPA + {len(entries)} data files copied")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 45)
    print("  China Diary — Build")
    print("=" * 45 + "\n")

    photos  = load_photos()
    entries = build_data(photos)
    titles  = {e["date"]: e["title"] for e in entries}
    build_static(entries, photos)
    build_static_photos(photos, titles)
    build_dynamic(entries, photos)
    build_dynamic_photos(photos, titles, DYNAMIC_MEDIA_BASE)
    build_practical()

    print(f"""
Done.
  Open offline:  open dist/static/index.html
  Run dynamic:   python3 -m http.server 8080 --directory dist/dynamic
                 then open http://localhost:8080
""")


if __name__ == "__main__":
    main()
