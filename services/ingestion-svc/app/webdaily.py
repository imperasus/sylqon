"""Daily Draft pages — /daily (today's puzzle) and /daily/{date} (archive).

Everything is server-rendered from the stored ``DailyPuzzle`` payload (one row
read, zero computation); the only JavaScript is a small static island that
records the visitor's answer in localStorage, unhides the pre-rendered
solution, builds the emoji share string and counts the streak. The archive
pages ship pre-solved (no JS needed) — they are the SEO surface and the
landing target of shared links.

Framing rules (docs/WEB_DRAFT_TERV.md §6): the balance number is always
presented as a narrow comp heuristic ("a read, not a prediction"), tiers grade
the answer options, several answers can be right, and the page never shows who
played the frozen match.
"""
from __future__ import annotations

import html
import re
from datetime import date as _date
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from app import champions, db, puzzles
from app.web import _DOWNLOAD_URL, _page

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_TIER_VERDICTS = {
    "strong": "Strong call — the engine has this among the best answers available.",
    "solid": "Solid call — defensible, though the engine saw a slightly stronger angle.",
    "risky": "Risky call — this plays into what the enemy comp wants.",
}

_DAILY_CSS = """
.dd-cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}
@media(max-width:680px){.dd-cols{grid-template-columns:1fr}}
.dd-side{font-family:var(--font-display);font-weight:700;font-size:.8rem;
letter-spacing:.08em;text-transform:uppercase;margin:0 0 .4rem}
.dd-side.blue{color:var(--accent)}.dd-side.red{color:var(--red)}
.slotrow{display:flex;align-items:center;gap:.65rem;padding:.28rem 0}
.slotrow img{width:38px;height:38px;border-radius:8px;flex:none}
.slotrow .role{margin-left:auto;color:var(--muted);font-size:.72rem;
text-transform:uppercase;letter-spacing:.06em}
.slot-q{width:38px;height:38px;border-radius:8px;border:1.5px dashed var(--accent);
display:inline-flex;align-items:center;justify-content:center;color:var(--accent);
font-family:var(--font-display);font-weight:700;flex:none}
.slotrow.you .role,.slotrow.you span{color:var(--accent)}
.cand-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
gap:.7rem;margin:.8rem 0}
button.cand{background:var(--surface);color:var(--text);border:1px solid var(--border);
border-radius:12px;padding:.75rem .5rem .6rem;text-align:center;
font-family:var(--font-body);font-size:.92rem;font-weight:600;cursor:pointer}
button.cand:hover{border-color:var(--muted);filter:none}
button.cand:disabled{cursor:default;opacity:1}
.cand img{width:52px;height:52px;border-radius:10px;display:block;margin:0 auto .4rem}
.cand .sub{display:block;color:var(--muted);font-size:.72rem;font-weight:400;
margin-top:.25rem;min-height:1.1em}
.cand .tierline,.cand .flag{display:none}
.solved .cand .tierline{display:block;font-family:var(--font-display);font-size:.72rem;
font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-top:.35rem}
.solved .cand.t-strong{border-color:var(--accent)}
.solved .cand.t-strong .tierline{color:var(--accent)}
.solved .cand.t-solid{border-color:var(--accent-2)}
.solved .cand.t-solid .tierline{color:var(--accent-2)}
.solved .cand.t-risky{border-color:var(--red)}
.solved .cand.t-risky .tierline{color:var(--red)}
.solved .cand.chosen{outline:2px solid var(--text);outline-offset:2px}
.solved .cand .flag{display:block;font-size:.64rem;font-weight:700;letter-spacing:.08em;
text-transform:uppercase;color:var(--muted);margin-top:.15rem}
#solution{display:none}.solved #solution{display:block}
.pickinfo{display:none}
.verdict{border-left:3px solid var(--accent-2)}
.drv{display:inline-block;font-size:.74rem;font-family:var(--font-mono);
padding:.12rem .5rem;border:1px solid var(--border);border-radius:999px;margin:.15rem .25rem 0 0}
.drv.up{color:var(--accent)}.drv.dn{color:var(--red)}
.epi-head{display:flex;align-items:center;gap:.7rem}
.epi-head img{width:44px;height:44px;border-radius:10px}
.epi-res.win{color:var(--accent);font-weight:700}.epi-res.loss{color:var(--red);font-weight:700}
.sharebar{display:flex;gap:.7rem;align-items:center;flex-wrap:wrap;margin-top:.4rem}
.streak{font-family:var(--font-mono);font-weight:700;color:var(--accent-2)}
.arch-list{display:flex;flex-wrap:wrap;gap:.45rem;margin:.4rem 0}
.arch-list a{border:1px solid var(--border);border-radius:999px;padding:.28rem .7rem;
font-size:.8rem;color:var(--muted)}
.arch-list a:hover{color:var(--text)}
"""

# Static island — no templating inside, so a plain (non-f) string stays safe.
_DAILY_JS = """
(function(){
var root=document.getElementById('daily');if(!root||root.dataset.mode!=='play')return;
var DATE=root.dataset.date,KEY='sylqon-daily-v1',st={};
try{st=JSON.parse(localStorage.getItem(KEY))||{}}catch(e){}
st.answers=st.answers||{};
var cands=[].slice.call(root.querySelectorAll('.cand'));
var EMOJI={strong:'\\u{1F7E9}',solid:'\\u{1F7E8}',risky:'\\u{1F7E5}'};
function sq(t){return EMOJI[t]||'\\u2B1C'}
function solve(i){
  root.classList.add('solved');
  cands.forEach(function(c){c.disabled=true});
  if(cands[i])cands[i].classList.add('chosen');
  var info=root.querySelector('.pickinfo[data-i="'+i+'"]');
  if(info)info.style.display='block';
  var squares=cands.map(function(c){return sq(c.dataset.tier)}).join('');
  var mine=cands[i]?sq(cands[i].dataset.tier):'\\u2B1C';
  var share='Sylqon Daily Draft '+DATE+'\\n'+squares+' \\u2014 my pick: '+mine+
            '\\nhttps://sylqon.com/daily';
  var btn=document.getElementById('share-btn');
  if(btn)btn.addEventListener('click',function(){
    navigator.clipboard.writeText(share).then(function(){btn.textContent='Copied!'});
  });
  var n=0,d=new Date(DATE+'T00:00:00Z');
  while(st.answers[d.toISOString().slice(0,10)]!=null){
    n++;d.setUTCDate(d.getUTCDate()-1);
  }
  var s=document.getElementById('streak');
  if(s&&n>1)s.textContent='\\u{1F525} '+n+'-day streak';
}
cands.forEach(function(c,i){c.addEventListener('click',function(){
  if(root.classList.contains('solved'))return;
  st.answers[DATE]=i;
  try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}
  solve(i);
})});
if(st.answers[DATE]!=null)solve(st.answers[DATE]);
})();
"""


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _icon(slug: str | None) -> str:
    url = champions.square_url_for_slug(slug)
    return f'<img src="{html.escape(url)}" alt="" loading="lazy">' if url else ""


def _drivers(drivers: list[dict]) -> str:
    return "".join(
        f'<span class="drv {"up" if d["sign"] > 0 else "dn"}">'
        f'{"+" if d["sign"] > 0 else "−"} {html.escape(d["text"])}</span>'
        for d in drivers)


def _team_card(payload: dict, side: str) -> str:
    """One team panel; the solver's team renders the hidden slot in place."""
    is_ally = side == payload["side"]
    color = "blue" if side == "blue" else "red"
    title = "Your team" if is_ally else "Enemy team"
    rows, ally_iter = [], iter(payload["ally"])
    for role in puzzles.ROLES:
        label = puzzles.ROLE_LABELS[role]
        if is_ally and role == payload["role"]:
            rows.append(f'<div class="slotrow you"><span class="slot-q">?</span>'
                        f'<span>Your pick</span><span class="role">{label}</span></div>')
            continue
        champ = next(ally_iter) if is_ally else \
            payload["enemy"][puzzles.ROLES.index(role)]
        rows.append(f'<div class="slotrow">{_icon(champ["slug"])}'
                    f'<span>{html.escape(champ["name"])}</span>'
                    f'<span class="role">{label}</span></div>')
    return (f'<div class="card"><p class="dd-side {color}">{title} · {side} side</p>'
            + "".join(rows) + "</div>")


def _meta_line(payload: dict) -> str:
    m = payload["match"]
    bits = ["A real game from our dataset",
            html.escape(puzzles.QUEUE_LABELS.get(m["queue_id"], "Summoner's Rift"))]
    if m["patch"]:
        bits.append(f'patch {html.escape(m["patch"])}')
    if m["rank_band"]:
        bits.append(f'seen around {html.escape(m["rank_band"].title())}')
    bits.append(f'{m["duration_min"]} min')
    return " · ".join(bits)


def _enemy_read_card(payload: dict) -> str:
    comp = payload["enemy_comp"]
    signals = "".join(f'<span class="tag">{html.escape(s)}</span>'
                      for s in comp["signals"])
    return (f'<div class="card"><h2 style="margin-top:0">The engine reads their comp: '
            f'<span class="hl">{html.escape(comp["label"])}</span> '
            f'<span class="muted small">· {comp["confidence"]}% confidence</span></h2>'
            f'<p class="muted" style="margin:.2rem 0 .6rem">{html.escape(comp["counter_plan"])}</p>'
            f'{signals}</div>')


def _candidate_buttons(payload: dict, solved: bool) -> str:
    out = []
    for i, c in enumerate(payload["candidates"]):
        lane = c["lane"]
        sub = (f'{lane["games"]} lane games vs their laner in our data'
               if lane else "&nbsp;")
        flags = []
        if c["is_real"]:
            flags.append("real pick")
        if c["is_engine_top"]:
            flags.append("engine's read")
        flag = f'<span class="flag">{html.escape(" + ".join(flags))}</span>' if flags else ""
        tierline = (f'<span class="tierline">{html.escape(c["tier"])} · '
                    f'{c["balance"]["win_pct"]}%</span>')
        out.append(
            f'<button type="button" class="cand t-{c["tier"]}" data-i="{i}" '
            f'data-tier="{c["tier"]}"{" disabled" if solved else ""}>'
            f'{_icon(c["slug"])}<span>{html.escape(c["name"])}</span>'
            f'{tierline}{flag}<span class="sub">{sub}</span></button>')
    return f'<div class="cand-grid">{"".join(out)}</div>'


def _pickinfo_blocks(payload: dict) -> str:
    """Hidden per-candidate verdict cards; the island unhides the chosen one."""
    blocks = []
    for i, c in enumerate(payload["candidates"]):
        lane = c["lane"]
        lane_line = (f'<p class="muted small" style="margin:.3rem 0 0">Lane record vs their '
                     f'laner in our data: {lane["winrate_pct"]}% over {lane["games"]} games.</p>'
                     if lane else "")
        blocks.append(
            f'<div class="pickinfo" data-i="{i}"><div class="card verdict">'
            f'<h2 style="margin-top:0">Your pick: {html.escape(c["name"])} — '
            f'{html.escape(c["tier"])}</h2>'
            f'<p style="margin:.2rem 0 .4rem">{html.escape(_TIER_VERDICTS[c["tier"]])}</p>'
            f'<p class="muted small" style="margin:0 0 .4rem">Your team\'s shape after this '
            f'pick: <strong>{html.escape(c["ally_archetype"])}</strong> · draft balance '
            f'{c["balance"]["win_pct"]}%</p>'
            f'{_drivers(c["balance"]["drivers"])}{lane_line}</div></div>')
    return "".join(blocks)


def _solution_html(payload: dict, date_iso: str, interactive: bool) -> str:
    top = next(c for c in payload["candidates"] if c["is_engine_top"])
    epi = payload["epilogue"]
    res = "win" if epi["win"] else "loss"
    res_label = "won" if epi["win"] else "lost"
    items = "".join(f'<img src="{html.escape(champions.item_url(i))}" alt="">'
                    for i in epi["items"] if champions.item_url(i))
    pickinfo = _pickinfo_blocks(payload) if interactive else ""
    share = ('<div class="card"><div class="sharebar">'
             '<button type="button" id="share-btn">Share result</button>'
             '<span class="streak" id="streak"></span>'
             f'<a class="small" href="/daily/{date_iso}">Permalink</a>'
             '<a class="small" href="/gym">Want more? Draft Gauntlet — 10 drafts, 30 points →</a>'
             "</div></div>") if interactive else ""
    return f"""
<div id="solution">
{pickinfo}
<div class="card">
<h2 style="margin-top:0">The engine's strongest read: <span class="hl">{html.escape(top["name"])}</span>
<span class="muted small">· draft balance {top["balance"]["win_pct"]}%</span></h2>
{_drivers(top["balance"]["drivers"])}
<p class="muted small" style="margin:.6rem 0 0">The balance number is a deliberately narrow
comp heuristic (clamped to 35–65%) — a read, not a prediction. Several answers can be right.</p>
</div>
<div class="card">
<h2 style="margin-top:0">What actually happened</h2>
<div class="epi-head">{_icon(epi["slug"])}<div>
<strong>{html.escape(epi["name"])}</strong> — the real player locked this and
<span class="epi-res {res}">{res_label}</span> the game.</div></div>
<p class="muted" style="margin:.6rem 0 .3rem">{epi["kills"]}/{epi["deaths"]}/{epi["assists"]} KDA
· {epi["cs"]} CS · {payload["match"]["duration_min"]} min</p>
<div class="items">{items}</div>
</div>
{share}
<div class="card">
<strong>The desktop app makes this exact call live in your champ select</strong>
<p class="muted small" style="margin:.3rem 0 .6rem">From your own champion pool, against the
real enemy five — and it writes the full loadout into your client. 100% local, free.</p>
<a class="btn" href="{_DOWNLOAD_URL}">Download for Windows</a>
</div>
</div>"""


def _archive_links(dates: list[str]) -> str:
    if not dates:
        return ""
    links = "".join(f'<a href="/daily/{d}">{d}</a>' for d in dates)
    return f'<h2>Previous puzzles</h2><div class="arch-list">{links}</div>'


def _puzzle_core(date_iso: str, payload: dict, interactive: bool) -> str:
    """Teams + enemy read + candidates + solution — everything but the hero
    and the archive strip, shared by /daily and the homepage."""
    back = ("" if interactive else
            '<p><a class="btn ghost" href="/daily">Play today\'s puzzle →</a></p>')
    prompt = ("<h2>Pick your answer</h2>" if interactive else
              "<h2>The candidates <span class='muted small'>· solution shown</span></h2>")
    return f"""{back}
<div class="dd-cols">{_team_card(payload, payload["side"])}
{_team_card(payload, "red" if payload["side"] == "blue" else "blue")}</div>
{_enemy_read_card(payload)}
{prompt}
{_candidate_buttons(payload, solved=not interactive)}
{_solution_html(payload, date_iso, interactive)}"""


def _render(date_iso: str, payload: dict, recent: list[str],
            interactive: bool) -> HTMLResponse:
    mode = "play" if interactive else "solved"
    body = f"""<style>{_DAILY_CSS}</style>
<div id="daily" class="{mode}" data-date="{date_iso}" data-mode="{mode}">
<section class="hero" style="padding-bottom:0">
<p class="eyebrow">Daily Draft · {date_iso}</p>
<h1>One pick is missing. <span class="hl">Make the call.</span></h1>
<p class="dd-meta">{_meta_line(payload)} · you fill the
<strong>{html.escape(payload["role_label"])}</strong> slot.</p>
</section>
{_puzzle_core(date_iso, payload, interactive)}
{_archive_links(recent)}
</div>
<script>{_DAILY_JS}</script>"""
    title = ("Daily Draft — today's puzzle" if interactive
             else f"Daily Draft — {date_iso}")
    return _page(title, body,
                 "A real draft frozen before one pick. Choose the missing champion, "
                 "see the engine's read — and what actually happened in the game.")


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """sylqon.com homepage — the hero doesn't tell, it makes you play
    (WEB_DRAFT_TERV §5): today's puzzle above the fold, download as the CTA."""
    today = _today_iso()
    with db.open_session() as session:
        payload = puzzles.get_puzzle(session, today)
        recent = puzzles.recent_dates(session, today, limit=7)
    hero = """
<section class="hero" style="padding-bottom:.4rem">
<p class="eyebrow">Counter-draft AI · League of Legends</p>
<h1>Can you make <span class="hl">the right call?</span></h1>
<p class="lead">Every day, one real draft frozen before a pick. Choose — the engine explains
its read, then you see what actually happened. The desktop app makes this exact call live in
your champ select, and writes the counter-loadout into your client.</p>
<div class="cta-row">
<a class="btn" href="/download">Download for Windows</a>
<a class="btn ghost" href="/audit">Audit your pool</a>
</div>
<p class="trust small muted">100% local — your credentials never leave your PC ·
No Overwolf, no ads</p>
</section>"""
    if payload is None:
        body = hero + _archive_links(recent)
        return _page("Sylqon — counter-draft AI for League of Legends", body,
                     "Sylqon picks the strongest answer from your pool live in champ select "
                     "and builds the counter-loadout. Plus a daily draft puzzle from real games.")
    body = f"""<style>{_DAILY_CSS}</style>
<div id="daily" class="play" data-date="{today}" data-mode="play">
{hero}
<h2 style="margin-top:1.2rem">Today's puzzle <span class="muted small">· {today}</span></h2>
<p class="dd-meta">{_meta_line(payload)} · you fill the
<strong>{html.escape(payload["role_label"])}</strong> slot.</p>
{_puzzle_core(today, payload, interactive=True)}
{_archive_links(recent)}
</div>
<script>{_DAILY_JS}</script>"""
    return _page("Sylqon — counter-draft AI for League of Legends", body,
                 "Sylqon picks the strongest answer from your pool live in champ select "
                 "and builds the counter-loadout. Plus a daily draft puzzle from real games.")


@router.get("/daily", response_class=HTMLResponse)
def daily_page() -> HTMLResponse:
    today = _today_iso()
    with db.open_session() as session:
        payload = puzzles.get_puzzle(session, today)
        recent = puzzles.recent_dates(session, today, limit=14)
    if payload is None:
        body = f"""
<section class="hero"><p class="eyebrow">Daily Draft</p>
<h1>No puzzle yet today.</h1>
<p class="lead">A new draft puzzle is frozen from a real game every day —
check back soon.</p></section>
{_archive_links(recent)}"""
        return _page("Daily Draft", body,
                     "A daily League of Legends draft puzzle from real games.")
    return _render(today, payload, recent, interactive=True)


@router.get("/daily/{date_iso}", response_class=HTMLResponse)
def daily_archive(date_iso: str):
    today = _today_iso()
    if not _DATE_RE.match(date_iso):
        return _page("Daily Draft", "<h1>Not a puzzle date</h1>"
                     '<p class="muted">Dates look like <code>/daily/2026-07-13</code>.</p>')
    try:
        _date.fromisoformat(date_iso)
    except ValueError:
        return _page("Daily Draft", "<h1>Not a puzzle date</h1>"
                     '<p class="muted">That calendar day does not exist.</p>')
    if date_iso >= today:
        # Today's puzzle is played on /daily; future puzzles (pre-generated for
        # curation) must never leak through the archive.
        return RedirectResponse("/daily", status_code=303)
    with db.open_session() as session:
        payload = puzzles.get_puzzle(session, date_iso)
        recent = puzzles.recent_dates(session, today, limit=14)
    if payload is None:
        body = (f'<h1>No puzzle for {html.escape(date_iso)}</h1>'
                '<p class="muted">Nothing was frozen that day.</p>'
                + _archive_links(recent))
        return _page("Daily Draft", body)
    return _render(date_iso, payload, [d for d in recent if d != date_iso],
                   interactive=False)
