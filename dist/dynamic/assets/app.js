
// China Diary — dynamic reader
// Fetches data/*.json at runtime; requires a web server.

const DATA_BASE = 'data/';
const PHOTO_PAGES = 'photos/';           // photo pages of this package
const MEDIA_BASE  = 'photos/';    // where the image files live (set by build.py)

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
