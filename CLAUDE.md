# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is a **China Diary rescue project**. The original diary (05.03.2001–23.05.2001, ~79 daily entries) was a PHP/MySQL website at `kumiankka.org/china/` that is now dead — domain gone, database lost. Fortunately an Internet Archive snapshot exists. The goal is to:

1. **Phase 1 (priority):** Scrape diary text from the Wayback Machine and store it as portable Markdown files.
2. **Phase 2:** Recover photos from 16 photo archive subpages.
3. **Phase 3:** Build two distribution packages from the recovered content.

## Key Source URLs (Internet Archive)

- **Diary entry point:** `https://web.archive.org/web/20030903095308/http://www.kumiankka.org/china/diary.php`
- **Photo archive entry point:** `https://web.archive.org/web/20030904024648/http://www.kumiankka.org/china/photoarchive.php`
- **Wayback CDX API** (use this to discover all archived URLs): `http://web.archive.org/cdx/search/cdx?url=kumiankka.org/china/*&output=json&limit=500`

Before writing any scraper, query the CDX API to map all available snapshots — this reveals the original URL pattern for individual diary entries (likely a `date=` or `id=` query parameter).

## Repository Structure

```
china-diary/
├── scraper/                  # One-off Python scripts to pull content from Wayback Machine
│   ├── scrape_diary.py           # Discovers + fetches all diary entry pages
│   └── scrape_photos.py          # Fetches photo archive pages + images
│
├── content/                  # Source of truth — human-readable, version-controlled
│   ├── diary/                    # YYYY-MM-DD.md, one file per entry (YAML frontmatter + Markdown body)
│   └── photos/                   # Downloaded images + per-subpage metadata JSON
│
├── build.py                  # Master build script: content/ → data/ + dist/
│
├── data/                     # Generated JSON data layer (committed, reusable by any future reader)
│   ├── entries.json              # Index: [{date, title, excerpt, filename}, …] sorted by date
│   └── YYYY-MM-DD.json           # Per-entry: {date, title, body_html, photos[], original_url}
│
└── dist/
    ├── static/               # Package 1 — pre-rendered HTML, works offline (open index.html directly)
    │   ├── index.html
    │   ├── YYYY-MM-DD.html
    │   └── assets/               # style.css matching original design, images
    └── dynamic/              # Package 2 — JS app for webserver, modern design
        ├── index.html            # Single entry point; JS fetches from data/ at runtime
        └── assets/
            ├── app.js            # Vanilla JS or lightweight framework
            └── style.css         # Modern typography, updated layout
```

## Two Distribution Packages

### Package 1 — Static HTML (original design)
- Pre-rendered by `build.py`: each entry baked into its own `.html` file.
- No server needed — works via `file://` by opening `dist/static/index.html`.
- CSS reproduces the original site's visual style as closely as possible.
- Also deployable to any web host.

### Package 2 — Dynamic JS app (modern design)
- Served from a webserver (any static file host, nginx, Node, etc.).
- `app.js` fetches `data/entries.json` and `data/YYYY-MM-DD.json` at runtime.
- Modern typography, updated layout — a fresh reading experience.
- The `data/` directory is shared with Package 1 and is the single data source.

### JSON data layer (`data/`)
The `data/` files are the most portable artefact of the rescue — committed to the repo so anyone can build their own reader without re-scraping. Schema:

```json
// entries.json
[{ "date": "2001-03-05", "title": "...", "excerpt": "...", "filename": "2001-03-05" }]

// YYYY-MM-DD.json
{ "date": "2001-03-05", "title": "...", "body_html": "...", "original_url": "..." }
```

## Development Commands

```bash
# Discover all archived URLs for the original site
curl "http://web.archive.org/cdx/search/cdx?url=kumiankka.org/china/*&output=json&limit=500"

# Install Python dependencies (once requirements.txt exists)
pip install -r requirements.txt

# Run diary scraper
python3 scraper/scrape_diary.py

# Build everything: data/ + dist/static/ + dist/dynamic/
python3 build.py

# Preview Package 1 (also works by opening dist/static/index.html directly)
python3 -m http.server 8080 --directory dist/static/

# Preview Package 2 (requires a server for fetch() to work)
python3 -m http.server 8080 --directory dist/dynamic/
# then open http://localhost:8080 — data/ must be accessible, so run from repo root
# or: python3 -m http.server 8080  (from repo root, with paths in app.js pointing to data/)
```

## Scraper Design Notes

- Use Python with `requests` + `BeautifulSoup4`. Add `time.sleep(1)` between requests to be polite.
- Wayback Machine URL pattern: `https://web.archive.org/web/{timestamp}/{original_url}`.
- Save each diary entry as `content/diary/YYYY-MM-DD.md` with YAML frontmatter: `date`, `title`, `original_url`.
- Strip Wayback Machine toolbar markup (`<div id="wm-ipp-base">` and similar) before extracting content.

## Build Script Notes

`build.py` is a single standalone Python script (stdlib + `markdown`/`mistune`). It:
1. Reads all `content/diary/*.md` files.
2. Converts Markdown bodies to HTML.
3. Writes `data/entries.json` and per-entry `data/YYYY-MM-DD.json`.
4. Renders `dist/static/` using an inline HTML template (original design).
5. Copies `data/` into `dist/dynamic/data/` and writes `dist/dynamic/index.html` + `assets/`.
