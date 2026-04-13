# chinese people... — China Diary Rescue

A rescue and remaster of **chinese people...**, a personal travel diary from a trip to China (Shanghai) in spring 2001. The original site ran on PHP/MySQL at `kumiankka.org/china/` — the domain is long gone and the database with it. This project recovers the content from an Internet Archive snapshot and repackages it into two working websites.

## What was recovered

- **80 diary entries** covering 05.03.2001 – 23.05.2001, written in Finnish
- **367 photos** from 16 photo archive subpages
- The **"Practical Chinese"** subpage — a mock phrasebook covering Chinese, Italian, and Tampere dialects
- Original pixel-art site graphics (buttons, hero image, logos), upscaled 4× for modern displays

## Repository layout

```
content/          Source of truth — human-readable, version-controlled
  diary/            80 Markdown files (YYYY-MM-DD.md), one per entry
  photos/           367 full-size JPEGs + thumbnails + metadata.json
  practical.md      The language phrasebook page

data/             Generated JSON data layer
  entries.json      Index of all entries (date, title, excerpt)
  YYYY-MM-DD.json   Per-entry data (title, body_html, original_url)
  all.json          All entries with body_html, for single-fetch "show all"

dist/static/      Package 1 — pre-rendered HTML, works offline
dist/dynamic/     Package 2 — SPA served from a web server

gfx/              Pixel-art site graphics (4× originals)
scraper/          One-off Python scripts used to pull content from Wayback Machine
build.py          Builds both dist/ packages from content/
```

## Running the site

**Package 1 — Static (no server needed)**

```bash
open dist/static/index.html
```

Or deploy the `dist/static/` folder to any web host.

**Package 2 — Dynamic SPA (requires a server)**

```bash
python3 -m http.server 8080 --directory dist/dynamic
# then open http://localhost:8080
```

## Rebuilding from source

```bash
pip install -r requirements.txt
python3 build.py
```

This regenerates both `dist/` packages and the `data/` JSON layer from `content/`.

## Design

Both packages use the original `#E9CB9A` warm-sand background and the pixel-art GIF buttons from the 2001 site, rendered at 2× CSS size with `image-rendering: pixelated` for crisp display on retina screens. Package 1 reproduces the original Verdana/10px aesthetic. Package 2 uses a modern Georgia serif typeset.

## Scraper notes

The scraper scripts in `scraper/` pulled content from the [Wayback Machine](https://web.archive.org/) using a 2003 snapshot of kumiankka.org. They are kept for reference but do not need to be re-run — all recovered content is committed under `content/`.

---

*Original site: kumiankka.org/china/ (2001) — Remastered 2026*
