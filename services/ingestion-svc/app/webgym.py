"""Draft Gauntlet pages — /gym and its run fragments.

Same fragment pattern as the Draft Lab: a static island only posts actions
(start / pick / next / finish) and swaps in server-rendered HTML, so every
state view comes from one Python renderer. The question fragment is built
spoiler-free (no tiers, no flags) — grading lives in app.gym, server-side.
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse

from app import db, gym
from app.web import _page
from app.webdaily import (
    _DAILY_CSS,
    _TIER_VERDICTS,
    _enemy_read_card,
    _icon,
    _meta_line,
    _team_card,
)

router = APIRouter()

_GYM_CSS = """
.gym-progress{font-family:var(--font-mono);font-weight:700;color:var(--muted);margin:.6rem 0}
.gym-progress .pts{color:var(--accent-2)}
.gym-emoji{font-size:1.4rem;letter-spacing:.1em;margin:.4rem 0}
.gym-score{font-family:var(--font-mono);font-size:2.6rem;font-weight:700;color:var(--accent)}
.gym-note{color:var(--red);font-size:.85rem;margin:.4rem 0 0}
.lb-table td:first-child{font-weight:600}
.verdict-pts{font-family:var(--font-mono);font-weight:700;font-size:1.2rem}
.verdict-pts.p3{color:var(--accent)}.verdict-pts.p1{color:var(--accent-2)}.verdict-pts.p0{color:var(--red)}
"""

# Static island: pure action → fragment swap; the run id travels on the
# fragment root's data-run attribute, nothing is stored client-side.
_GYM_JS = """
(function(){
var root=document.getElementById('gym');if(!root)return;
var busy=false;
function post(url,body){
  if(busy)return;busy=true;
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body||{})})
    .then(function(r){return r.text()})
    .then(function(html){root.innerHTML=html;busy=false;window.scrollTo({top:root.offsetTop-70,behavior:'smooth'})})
    .catch(function(){busy=false});
}
function runId(){var f=root.querySelector('[data-run]');return f?f.dataset.run:null}
root.addEventListener('click',function(e){
  var t=e.target.closest('button,a');if(!t)return;
  if(t.id==='gym-start'||t.id==='gym-again'){e.preventDefault();post('/gym/start');return}
  if(t.classList.contains('cand')){
    var f=t.closest('[data-state]');
    if(!f||f.dataset.state!=='question')return;
    post('/gym/answer',{run:runId(),pick:parseInt(t.dataset.i,10)});return}
  if(t.id==='gym-next'){e.preventDefault();post('/gym/view',{run:runId()});return}
  if(t.id==='gym-finish'){e.preventDefault();
    var nick=document.getElementById('gym-nick');
    post('/gym/finish',{run:runId(),nickname:nick?nick.value:''});return}
  if(t.id==='gym-share'){e.preventDefault();
    navigator.clipboard.writeText(t.dataset.share)
      .then(function(){t.textContent='Copied!'});return}
});
})();
"""


def _candidate_buttons_safe(payload: dict) -> str:
    """Question-state candidates: icon + name + lane-games sub ONLY — the
    tiers and flags never reach the browser before the answer."""
    out = []
    for i, c in enumerate(payload["candidates"]):
        lane = c["lane"]
        sub = (f'{lane["games"]} lane games vs their laner in our data'
               if lane else "&nbsp;")
        out.append(
            f'<button type="button" class="cand" data-i="{i}">'
            f'{_icon(c["slug"])}<span>{html.escape(c["name"])}</span>'
            f'<span class="sub">{sub}</span></button>')
    return f'<div class="cand-grid">{"".join(out)}</div>'


def _candidates_revealed(payload: dict, chosen: int) -> str:
    out = []
    for i, c in enumerate(payload["candidates"]):
        classes = f'cand t-{c["tier"]}' + (" chosen" if i == chosen else "")
        flags = []
        if c["is_real"]:
            flags.append("real pick")
        if c["is_engine_top"]:
            flags.append("engine's read")
        flag = f'<span class="flag">{html.escape(" + ".join(flags))}</span>' if flags else ""
        out.append(
            f'<button type="button" class="{classes}" disabled>'
            f'{_icon(c["slug"])}<span>{html.escape(c["name"])}</span>'
            f'<span class="tierline">{html.escape(c["tier"])} · '
            f'{c["balance"]["win_pct"]}%</span>{flag}</button>')
    return f'<div class="solved"><div class="cand-grid">{"".join(out)}</div></div>'


def _progress(run, offset: int = 0) -> str:
    idx = len(run.answers) + offset
    return (f'<p class="gym-progress">Draft {min(idx + 1, len(run.puzzle_ids))}'
            f'/{len(run.puzzle_ids)} · <span class="pts">{run.score} pts</span></p>')


def _question_html(run, payload: dict) -> str:
    return f"""<div class="gym-frag" data-run="{run.run_id}" data-state="question">
{_progress(run)}
<p class="dd-meta">{_meta_line(payload)} · you fill the
<strong>{html.escape(payload["role_label"])}</strong> slot.</p>
<div class="dd-cols">{_team_card(payload, payload["side"])}
{_team_card(payload, "red" if payload["side"] == "blue" else "blue")}</div>
{_enemy_read_card(payload)}
<h2>Pick your answer</h2>
{_candidate_buttons_safe(payload)}
</div>"""


def _verdict_html(run, result: dict) -> str:
    payload, tier, points = result["payload"], result["tier"], result["points"]
    epi = payload["epilogue"]
    top = next(c for c in payload["candidates"] if c["is_engine_top"])
    res = "won" if epi["win"] else "lost"
    next_label = "See your result →" if result["done"] else "Next draft →"
    return f"""<div class="gym-frag" data-run="{run.run_id}" data-state="verdict">
{_progress(run, offset=-1)}
<div class="card verdict">
<span class="verdict-pts p{points}">+{points} pts</span> —
<strong>{html.escape(tier)}</strong>.
{html.escape(_TIER_VERDICTS[tier])}
<p class="muted small" style="margin:.5rem 0 0">The engine's strongest read:
<strong>{html.escape(top["name"])}</strong> ({top["balance"]["win_pct"]}%) · the real player
locked <strong>{html.escape(epi["name"])}</strong> and {res} the game
({epi["kills"]}/{epi["deaths"]}/{epi["assists"]}).</p>
</div>
{_candidates_revealed(payload, result["pick"])}
<p><button type="button" id="gym-next">{next_label}</button></p>
</div>"""


def _leaderboards_html(session) -> str:
    def table(rows: list[tuple[str, int]], title: str) -> str:
        if not rows:
            body = '<p class="muted small">No runs yet — be the first name here.</p>'
        else:
            body = ("<table class='lb-table'>"
                    + "".join(f'<tr><td>{i + 1}.</td><td>{html.escape(n)}</td>'
                              f'<td class="num">{s} pts</td></tr>'
                              for i, (n, s) in enumerate(rows))
                    + "</table>")
        return f'<div class="card"><h2 style="margin-top:0">{title}</h2>{body}</div>'

    return (f'<div class="dd-cols">{table(gym.leaderboard(session, days=1), "Today")}'
            f'{table(gym.leaderboard(session), "All time")}</div>')


def _final_html(session, run, note: str | None = None) -> str:
    share = (f"Sylqon Draft Gauntlet — {run.score}/{gym.max_score()} "
             f"{gym.emoji_summary(run)} https://sylqon.com/gym")
    if run.nickname:
        name_row = (f'<p class="muted">On the board as '
                    f'<strong>{html.escape(run.nickname)}</strong>.</p>')
    else:
        name_row = (
            '<div class="searchbar" style="margin:.6rem 0">'
            '<input type="text" id="gym-nick" maxlength="16" placeholder="Name for the board">'
            '<button type="button" id="gym-finish">Save score</button></div>')
    note_html = f'<p class="gym-note">{html.escape(note)}</p>' if note else ""
    return f"""<div class="gym-frag" data-run="{run.run_id}" data-state="final">
<div class="card">
<h2 style="margin-top:0">Run complete</h2>
<span class="gym-score">{run.score} / {gym.max_score()}</span>
<div class="gym-emoji">{gym.emoji_summary(run)}</div>
<p class="muted small">Points grade your answers against the engine's reads — several picks
can be right, and the engine is a narrow heuristic, not an oracle.</p>
{name_row}{note_html}
<div class="sharebar">
<button type="button" id="gym-share" data-share="{html.escape(share, quote=True)}">Share result</button>
<button type="button" id="gym-again" class="ghost">Run again</button>
</div>
</div>
{_leaderboards_html(session)}
</div>"""


@router.get("/gym", response_class=HTMLResponse)
def gym_page() -> HTMLResponse:
    with db.open_session() as session:
        boards = _leaderboards_html(session)
    body = f"""<style>{_DAILY_CSS}{_GYM_CSS}</style>
<section class="hero" style="padding-bottom:.4rem">
<p class="eyebrow">Draft Gauntlet</p>
<h1>Ten real drafts. <span class="hl">Thirty points.</span></h1>
<p class="lead">A run of ten frozen drafts from real games — pick the missing champion in each.
Strong reads score 3, solid 1, risky 0. Answers are graded server-side; the board below is
the honest kind.</p>
</section>
<div id="gym">
<p><button type="button" id="gym-start">Start a run</button></p>
{boards}
</div>
<script>{_GYM_JS}</script>"""
    return _page("Draft Gauntlet — ten drafts, thirty points", body,
                 "A ten-puzzle draft gauntlet from real games: pick the missing champion, "
                 "score up to 30, put your name on the board.")


def _fragment(builder) -> HTMLResponse:
    """Shared error envelope: rule violations render as a friendly card so the
    island can always swap innerHTML, never a JSON error page."""
    try:
        return HTMLResponse(builder())
    except gym.GymError as exc:
        return HTMLResponse(
            f'<div class="gym-frag" data-state="error"><div class="card">'
            f'<p style="margin:0">{html.escape(str(exc))}</p>'
            f'<p style="margin:.6rem 0 0"><button type="button" id="gym-start">'
            f"Start a run</button></p></div></div>")


@router.post("/gym/start", response_class=HTMLResponse)
def gym_start() -> HTMLResponse:
    def build():
        with db.open_session() as session:
            run = gym.start_run(session)
            payload = gym.current_puzzle(session, run)
            return _question_html(run, payload)
    return _fragment(build)


@router.post("/gym/answer", response_class=HTMLResponse)
def gym_answer(body: dict = Body(...)) -> HTMLResponse:
    def build():
        with db.open_session() as session:
            run = gym.get_run(session, body.get("run"))
            if run is None:
                raise gym.GymError("this run is gone — start a new one")
            result = gym.answer(session, run, body.get("pick"))
            return _verdict_html(run, result)
    return _fragment(build)


@router.post("/gym/view", response_class=HTMLResponse)
def gym_view(body: dict = Body(...)) -> HTMLResponse:
    def build():
        with db.open_session() as session:
            run = gym.get_run(session, body.get("run"))
            if run is None:
                raise gym.GymError("this run is gone — start a new one")
            payload = gym.current_puzzle(session, run)
            if payload is None:
                return _final_html(session, run)
            return _question_html(run, payload)
    return _fragment(build)


@router.post("/gym/finish", response_class=HTMLResponse)
def gym_finish(body: dict = Body(...)) -> HTMLResponse:
    def build():
        with db.open_session() as session:
            run = gym.get_run(session, body.get("run"))
            if run is None:
                raise gym.GymError("this run is gone — start a new one")
            try:
                gym.save_nickname(session, run, body.get("nickname"))
                return _final_html(session, run)
            except gym.GymError as exc:
                return _final_html(session, run, note=str(exc))
    return _fragment(build)
