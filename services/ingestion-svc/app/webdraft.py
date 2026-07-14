"""Draft Lab pages — /draft (live simulator) and /d/{code} (permalink).

The simulator that talks back: fill the two teams and the engine reads both
comps, the structure chips and the clamped balance on every change. The
browser stays thin — a static island collects the picker values and swaps in
a server-rendered HTML fragment (POST /draft/panel), so the live panel and
the shared /d/{code} page come from the *same* Python renderer and can never
drift apart. Permalinks are pure champion-id strings (draftlab codec): no
database row, no expiry, fork-friendly.
"""
from __future__ import annotations

import html
import json

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse

from app import champions, draftintel, draftlab
from app.web import _page
from app.webdaily import _DAILY_CSS

router = APIRouter()

_LAB_CSS = """
.lab-slot{display:flex;align-items:center;gap:.5rem;padding:.22rem 0}
.lab-slot img{width:34px;height:34px;border-radius:8px;flex:none;background:var(--surface2)}
.lab-slot img[src=""]{visibility:hidden}
.lab-slot input{flex:1;width:auto;max-width:none;padding:.5rem .7rem;font-size:.92rem}
.lab-big{font-family:var(--font-mono);font-size:2rem;font-weight:700}
.lab-big.good{color:var(--accent)}.lab-big.bad{color:var(--red)}.lab-big.amber{color:var(--accent-2)}
.lab-chips{display:flex;flex-wrap:wrap;gap:.35rem;margin:.4rem 0}
.pool-row td{vertical-align:middle}
.pool-champ{display:flex;align-items:center;gap:.5rem;font-weight:600}
.pool-champ img{width:28px;height:28px;border-radius:6px}
"""

# Static island — plain string (no f-string templating), all state in the DOM.
_LAB_JS = """
(function(){
var root=document.getElementById('lab');if(!root)return;
var IDX={};CHAMPS.forEach(function(c){IDX[c.name.toLowerCase()]=c});
var POOL=[],timer=null;
function side(name){
  return [].slice.call(root.querySelectorAll('.lab-pick[data-side="'+name+'"]'))
    .map(function(inp){
      var c=IDX[inp.value.trim().toLowerCase()];
      var img=inp.parentNode.querySelector('img');
      img.src=c?'https://ddragon.leagueoflegends.com/cdn/'+DD_VER+'/img/champion/'+c.slug+'.png':'';
      return c?c.name:null;
    }).filter(Boolean);
}
function code(){
  function ids(name){
    return [].slice.call(root.querySelectorAll('.lab-pick[data-side="'+name+'"]'))
      .map(function(inp){var c=IDX[inp.value.trim().toLowerCase()];return c?c.key:'0'})
      .join('.');
  }
  return ids('ally')+'-'+ids('enemy');
}
function update(){
  var ally=side('ally'),enemy=side('enemy');
  var link=document.getElementById('lab-link');
  if(link){link.href='/d/'+code();link.textContent='/d/'+code()}
  fetch('/draft/panel',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ally:ally,enemy:enemy,pool:POOL})})
    .then(function(r){return r.text()})
    .then(function(html){document.getElementById('lab-panel').innerHTML=html})
    .catch(function(){});
}
function schedule(){clearTimeout(timer);timer=setTimeout(update,250)}
root.addEventListener('input',function(e){
  if(e.target.classList.contains('lab-pick'))schedule();
});
var share=document.getElementById('lab-share');
if(share)share.addEventListener('click',function(){
  navigator.clipboard.writeText(location.origin+'/d/'+code())
    .then(function(){share.textContent='Copied!';setTimeout(function(){share.textContent='Copy permalink'},1500)});
});
var loadBtn=document.getElementById('pool-load');
if(loadBtn)loadBtn.addEventListener('click',function(){
  var riot=document.getElementById('pool-riot').value.trim();
  if(!riot)return;
  var note=document.getElementById('pool-note');
  note.textContent='Loading…';
  fetch('/api/draft/pool?riot_id='+encodeURIComponent(riot))
    .then(function(r){if(!r.ok)throw r;return r.json()})
    .then(function(data){
      POOL=data.champions||[];
      note.textContent=POOL.length?('Loaded '+POOL.length+' champions: '+POOL.join(', ')):
        'No stored champions for this Riot ID yet — run the pool audit first.';
      update();
    })
    .catch(function(){note.textContent='Could not load that Riot ID — check the spelling (Name#TAG).'});
});
update();
})();
"""


def _icon(slug: str | None) -> str:
    url = champions.square_url_for_slug(slug)
    return f'<img src="{html.escape(url)}" alt="" loading="lazy">' if url else ""


def _drivers(drivers: list[dict]) -> str:
    return "".join(
        f'<span class="drv {"up" if d["sign"] > 0 else "dn"}">'
        f'{"+" if d["sign"] > 0 else "−"} {html.escape(d["text"])}</span>'
        for d in drivers)


def _chips_line(chips: dict) -> str:
    parts = [f'{chips["ad"]} AD · {chips["ap"]} AP · {chips["mixed"]} mixed',
             f'{chips["frontline"]} frontline', f'{chips["heavy_cc"]} heavy CC']
    return "".join(f'<span class="tag">{p}</span>' for p in parts)


def _comp_card(title: str, comp: dict, chips: dict, *, show_plan: bool) -> str:
    signals = "".join(f'<span class="tag">{html.escape(s)}</span>'
                      for s in comp["signals"])
    plan = (f'<p class="muted small" style="margin:.3rem 0 .4rem">'
            f'{html.escape(comp["counter_plan"])}</p>' if show_plan else "")
    return (f'<div class="card"><h2 style="margin-top:0">{title}: '
            f'<span class="hl">{html.escape(comp["label"])}</span> '
            f'<span class="muted small">· {comp["confidence"]}% confidence</span></h2>'
            f'{plan}<div class="lab-chips">{signals}</div>'
            f'<div class="lab-chips">{_chips_line(chips)}</div></div>')


def _pool_table(ranking: list[dict]) -> str:
    if not ranking:
        return ""
    rows = []
    for r in ranking[:8]:
        drivers = _drivers(r["drivers"]) or '<span class="muted small">—</span>'
        rows.append(
            f'<tr class="pool-row"><td><div class="pool-champ">{_icon(r["slug"])}'
            f'<span>{html.escape(r["name"])}</span></div></td>'
            f'<td class="num">{r["win_pct"]}%</td>'
            f'<td>{drivers}</td>'
            f'<td class="muted small">{html.escape(r["ally_archetype"])}</td></tr>')
    return (f'<div class="card"><h2 style="margin-top:0">Your pool, ranked into this draft</h2>'
            f'<div class="sb-wrap"><table><tr><th>Champion</th><th class="num">Balance</th>'
            f'<th>Why</th><th>Team shape</th></tr>{"".join(rows)}</table>'
            f'<p class="muted small" style="margin:.5rem 0 0">Options with reasons — several '
            f'picks can be right.</p></div>')


def _analysis_html(result: dict, pool_ranking: list[dict] | None = None) -> str:
    """The live panel AND the /d/{code} body — one renderer, zero drift."""
    if len(result["ally"]) < 2 and len(result["enemy"]) < 2:
        return ('<div class="card"><p class="muted" style="margin:0">Add at least two picks '
                "on a side and the engine starts reading the draft.</p></div>")
    balance = result["balance"]
    hidden = result["hidden_enemies"]
    hidden_note = (f' · {hidden} enemy pick(s) hidden — the read sharpens as they reveal'
                   if hidden else "")
    return f"""
<div class="dd-cols">
{_comp_card("Your comp", result["ally_comp"], result["ally_chips"], show_plan=False)}
{_comp_card("Enemy comp", result["enemy_comp"], result["enemy_chips"], show_plan=True)}
</div>
<div class="card">
<h2 style="margin-top:0">Draft balance</h2>
<span class="lab-big {balance["tone"]}">{balance["win_pct"]}%</span>
<strong style="margin-left:.5rem">{html.escape(balance["label"])}</strong>
<span class="muted small"> · read confidence {balance["confidence"]}%{hidden_note}</span>
<div class="lab-chips" style="margin-top:.5rem">{_drivers(balance["drivers"])}</div>
<p class="muted small" style="margin:.6rem 0 0">A deliberately narrow comp heuristic
(clamped to 35–65%) — a read, not a prediction.</p>
</div>
{_pool_table(pool_ranking or [])}"""


def _board_inputs(side: str, title: str, color: str, prefill: list[str]) -> str:
    rows = []
    for i in range(draftlab.SLOTS):
        value = html.escape(prefill[i]) if i < len(prefill) else ""
        ident = draftintel.identity(value) if value else None
        icon_url = champions.square_url_for_slug(ident["slug"]) if ident else ""
        rows.append(
            f'<div class="lab-slot"><img src="{html.escape(icon_url or "")}" alt="">'
            f'<input class="lab-pick" list="champ-list" data-side="{side}" data-i="{i}" '
            f'placeholder="Pick {i + 1}" value="{value}" autocomplete="off"></div>')
    return (f'<div class="card"><p class="dd-side {color}">{title}</p>'
            + "".join(rows) + "</div>")


@router.get("/draft", response_class=HTMLResponse)
def draft_lab(d: str | None = None) -> HTMLResponse:
    decoded = draftlab.decode_state(d) if d else None
    ally_pre, enemy_pre = decoded if decoded else ([], [])
    roster = draftintel.roster()
    options = "".join(f'<option value="{html.escape(c["name"])}">' for c in roster)
    champs_json = json.dumps(roster).replace("</", "<\\/")
    body = f"""<style>{_DAILY_CSS}{_LAB_CSS}</style>
<div id="lab">
<section class="hero" style="padding-bottom:0">
<p class="eyebrow">Draft Lab</p>
<h1>The draft simulator <span class="hl">that talks back.</span></h1>
<p class="dd-meta">Fill any picks on both sides — the engine reads the comps, the structure
and the balance on every change. Share the board as a permalink.</p>
</section>
<div class="dd-cols">
{_board_inputs("ally", "Your team", "blue", ally_pre)}
{_board_inputs("enemy", "Enemy team", "red", enemy_pre)}
</div>
<datalist id="champ-list">{options}</datalist>
<div class="card"><div class="sharebar">
<button type="button" id="lab-share">Copy permalink</button>
<a id="lab-link" class="small" href="/draft">—</a>
</div></div>
<div class="card"><h2 style="margin-top:0">Which of my picks fits here?</h2>
<div class="searchbar">
<input type="text" id="pool-riot" placeholder="Name#TAG">
<button type="button" id="pool-load">Load my pool</button>
</div>
<div id="pool-note" class="muted small" style="margin-top:.5rem">Loads your stored champions
from our dataset (<a href="/audit">run the pool audit</a> first if it comes back empty) and
ranks them into the current draft.</div></div>
<div id="lab-panel">{_analysis_html(draftlab.analyze(ally_pre, enemy_pre))}</div>
</div>
<script>var CHAMPS={champs_json};var DD_VER="{html.escape(champions.version())}";</script>
<script>{_LAB_JS}</script>"""
    return _page("Draft Lab — the simulator that talks back", body,
                 "A 5v5 draft simulator with a brain: comp reads, structure chips and a "
                 "clamped balance on every pick — plus your own pool ranked into the draft.")


@router.post("/draft/panel", response_class=HTMLResponse)
def draft_panel(payload: dict = Body(...)) -> HTMLResponse:
    """The live panel fragment the island swaps in on every board change."""
    ally = draftlab.clean_names(payload.get("ally"))
    enemy = draftlab.clean_names(payload.get("enemy"))
    pool = draftlab.clean_names(payload.get("pool"), cap=30)
    result = draftlab.analyze(ally, enemy)
    ranking = draftlab.rank_pool(pool, ally, enemy) if pool else []
    return HTMLResponse(_analysis_html(result, ranking))


def _static_board(result: dict) -> str:
    def side_card(champs: list[dict], title: str, color: str) -> str:
        rows = "".join(f'<div class="slotrow">{_icon(c["slug"])}'
                       f'<span>{html.escape(c["name"])}</span></div>'
                       for c in champs) or '<p class="muted small">no picks</p>'
        return f'<div class="card"><p class="dd-side {color}">{title}</p>{rows}</div>'

    return (f'<div class="dd-cols">{side_card(result["ally"], "Team A", "blue")}'
            f'{side_card(result["enemy"], "Team B", "red")}</div>')


@router.get("/d/{code}", response_class=HTMLResponse)
def shared_draft(code: str) -> HTMLResponse:
    decoded = draftlab.decode_state(code)
    if decoded is None:
        return _page("Draft Lab", '<h1>Not a draft link</h1><p class="muted">Shared drafts '
                     'look like <code>/d/266.64.0.0.0-121.0.0.0.0</code> — open the '
                     '<a href="/draft">Draft Lab</a> to build one.</p>')
    ally, enemy = decoded
    result = draftlab.analyze(ally, enemy)
    vs = (f'{result["ally_comp"]["label"]} vs {result["enemy_comp"]["label"]} — '
          f'{result["balance"]["win_pct"]}% {result["balance"]["label"]}')
    body = f"""<style>{_DAILY_CSS}{_LAB_CSS}</style>
<section class="hero" style="padding-bottom:0">
<p class="eyebrow">Draft Lab · shared board</p>
<h1>{html.escape(vs)}</h1>
<p class="dd-meta">A shared draft read. Disagree?
<a href="/draft?d={html.escape(code)}">Fork it in the Draft Lab →</a></p>
</section>
{_static_board(result)}
{_analysis_html(result)}
<p><a class="btn ghost" href="/draft?d={html.escape(code)}">Open in Draft Lab</a></p>"""
    return _page(f"Draft Lab — {vs}", body,
                 "A shared 5v5 draft with the engine's read: comp archetypes, structure "
                 "chips and the clamped balance. Fork it and make your own call.")
