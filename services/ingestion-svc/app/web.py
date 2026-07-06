"""Public web pages — the S3 website MVP (roadmap §5.2).

Server-rendered HTML straight from the service (no build step, no JS
framework): a Riot-ID → pool-audit report page plus SEO-friendly champion
pages computed from our own Match-V5 aggregation. Visual language follows
the landing page (dark HUD, teal accent).

ToS framing rule: every number on these pages measures *pool coverage* or
champion presence in our dataset — never player skill. No MMR/ELO anywhere.
"""
from __future__ import annotations

import html
import logging
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app import builds, db, pool

log = logging.getLogger(__name__)

router = APIRouter()

_CSS = """
:root{--bg:#0b1220;--surface:#111a2c;--surface2:#16213a;--text:#e8edf6;
--muted:#93a0b5;--accent:#4fd7c9;--red:#ef6a6a;--border:#26324a}
*{box-sizing:border-box}body{margin:0;font:16px/1.6 system-ui,Segoe UI,sans-serif;
background:var(--bg);color:var(--text)}a{color:var(--accent);text-decoration:none}
.wrap{max-width:1000px;margin:0 auto;padding:0 1.2rem}
header{border-bottom:1px solid var(--border);background:rgba(11,18,32,.9)}
header .wrap{display:flex;align-items:center;justify-content:space-between;min-height:60px}
.brand{font-weight:700;letter-spacing:.04em;color:var(--text);font-size:1.15rem}
.brand span{color:var(--accent)}
nav a{margin-left:1.2rem;color:var(--muted);font-size:.9rem}nav a:hover{color:var(--text)}
h1{font-size:1.7rem;margin:2rem 0 .4rem}h2{font-size:1.15rem;margin:1.6rem 0 .6rem}
.muted{color:var(--muted)}.small{font-size:.85rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
padding:1.1rem 1.3rem;margin:1rem 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:.8rem}
.score{font-size:2.2rem;font-weight:700;color:var(--accent)}
.bar{height:8px;border-radius:4px;background:var(--surface2);overflow:hidden;margin:.25rem 0 .6rem}
.bar i{display:block;height:100%;background:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{text-align:left;padding:.45rem .6rem;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em}
.tag{display:inline-block;font-size:.72rem;font-weight:600;padding:.15rem .55rem;
border-radius:999px;border:1px solid var(--border);color:var(--accent);margin-right:.3rem}
.tag.warn{color:var(--red)}
input[type=text]{background:var(--surface2);border:1px solid var(--border);color:var(--text);
padding:.65rem .9rem;border-radius:8px;font-size:1rem;width:280px;max-width:60vw}
button{background:var(--accent);color:#06251f;border:0;padding:.68rem 1.2rem;border-radius:8px;
font-weight:700;font-size:.95rem;cursor:pointer}button:hover{filter:brightness(1.08)}
footer{border-top:1px solid var(--border);margin-top:3rem;padding:1.4rem 0;color:var(--muted);font-size:.78rem}
"""


def _page(title: str, body: str, description: str = "") -> HTMLResponse:
    desc = html.escape(description or
                       "Sylqon pool coverage — champion pool analysis from official Riot data.")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Sylqon</title>
<meta name="description" content="{desc}">
<style>{_CSS}</style></head><body>
<header><div class="wrap">
<a class="brand" href="/">SYL<span>QON</span> <span class="muted small">pool coverage</span></a>
<nav><a href="/">Pool audit</a><a href="/champions">Champions</a>
<a href="https://imperasus.github.io/sylqon/">Desktop app</a></nav>
</div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap">Sylqon is an unofficial fan-made tool. Not endorsed by Riot Games.
All statistics are aggregated from official Riot Games APIs and measure pool coverage and
champion presence in our dataset — never player skill.</div></footer>
</body></html>""")


def _bar(value: int) -> str:
    return f'<div class="bar"><i style="width:{max(2, min(100, value))}%"></i></div>'


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    body = """
<h1>Does your champion pool cover the meta?</h1>
<p class="muted" style="max-width:56ch">Enter a Riot ID and get a per-role pool-coverage
audit: your performance on your champions, how safely they can be blind-picked, and which
common opponents your pool has no answer to — computed from our own aggregation of official
Riot match data.</p>
<div class="card"><form action="/pool-report" method="get">
<input type="text" name="riot_id" placeholder="Name#TAG" required>
<button type="submit">Audit my pool</button>
<div class="muted small" style="margin-top:.5rem">Only public match data is used.
Analysis measures pool coverage, not player skill.</div>
</form></div>
<h2>What you get</h2>
<div class="grid">
<div class="card"><strong>Coverage score</strong><p class="muted small">One number per role,
blending performance, blind-pick safety and counter coverage.</p></div>
<div class="card"><strong>Suggested 3-champion pool</strong><p class="muted small">Anchored on
your comfort pick, filled to cover the gaps your current pool leaves open.</p></div>
<div class="card"><strong>Uncovered threats</strong><p class="muted small">The common picks in
your role that none of your champions hold an even lane record against.</p></div>
</div>"""
    return _page("Champion pool audit", body)


@router.get("/pool-report", response_class=HTMLResponse)
def pool_report_page(riot_id: str = Query(..., min_length=3)) -> HTMLResponse:
    game_name, _, tag_line = riot_id.partition("#")
    if not game_name or not tag_line:
        return _page("Pool audit", '<h1>Invalid Riot ID</h1><p class="muted">'
                     'Use the <code>Name#TAG</code> form.</p>')
    from app.main import _ingest_service  # resolved lazily; may be None in tests

    puuid = None
    if _ingest_service is not None:
        try:
            result = _ingest_service.ingest(game_name.strip(), tag_line.strip())
            puuid = result.puuid
        except Exception as exc:  # AccountNotFound or transient API failure
            log.info("pool-report ingest failed for %s: %s", riot_id, exc)
    if puuid is None:
        return _page("Pool audit", f'<h1>Player not found</h1><p class="muted">'
                     f'No account found for <strong>{html.escape(riot_id)}</strong> — '
                     f'check the spelling (Name#TAG).</p>')

    with db.open_session() as session:
        report = pool.analyze_pool(session, puuid)
    if report is None:
        return _page("Pool audit", f'<h1>{html.escape(riot_id)}</h1><p class="muted">'
                     'No Summoner’s Rift matches stored for this player yet — '
                     'try again in a minute.</p>')

    sections = []
    for role, data in report["roles"].items():
        comps = data["components"]
        current = " · ".join(
            f'{html.escape(c["champion"])} <span class="muted">({c["wins"]}W/{c["games"] - c["wins"]}L)</span>'
            for c in data["current"][:5]
        )
        suggested_rows = []
        for s in data["suggested"]:
            tags = "".join(f'<span class="tag">{html.escape(r)}</span>' for r in s["reasons"])
            if s["personal"]:
                rec = f'{s["personal"]["wins"]}W/{s["personal"]["games"] - s["personal"]["wins"]}L'
            else:
                rec = "—"
            suggested_rows.append(
                f'<tr><td><a href="/champion/{quote(s["champion"])}">'
                f'{html.escape(s["champion"])}</a></td><td>{tags}</td>'
                f'<td class="muted">{rec}</td></tr>'
            )
        suggested = "".join(suggested_rows)
        uncovered = ", ".join(
            f'<a href="/champion/{quote(u)}">{html.escape(u)}</a>' for u in data["uncovered"][:6]
        ) or '<span class="muted">none found</span>'
        low = ('<span class="tag warn">thin data — treat with care</span>'
               if data["low_data"] else "")
        sections.append(f"""
<div class="card">
<h2 style="margin-top:0">{role} <span class="muted small">· {data["games"]} games</span> {low}</h2>
<div class="score">{data["coverage_score"]}</div>
<div class="muted small">pool coverage</div>
<table style="margin-top:.8rem"><tr><th>Component</th><th style="width:55%"></th><th></th></tr>
<tr><td>Performance</td><td>{_bar(comps["performance"])}</td><td>{comps["performance"]}</td></tr>
<tr><td>Blind-pick safety</td><td>{_bar(comps["blind_safety"])}</td><td>{comps["blind_safety"]}</td></tr>
<tr><td>Counter coverage</td><td>{_bar(comps["counter_coverage"])}</td><td>{comps["counter_coverage"]}</td></tr>
</table>
<p class="small"><strong>Current pool:</strong> {current}</p>
<h2>Suggested pool</h2>
<table><tr><th>Champion</th><th>Why</th><th>Your record</th></tr>{suggested}</table>
<p class="small"><strong>Uncovered threats:</strong> {uncovered}</p>
</div>""")

    body = (f'<h1>{html.escape(riot_id)}</h1>'
            f'<p class="muted small">Pool-coverage audit from our own aggregation of official '
            f'Riot match data.</p>{"".join(sections)}')
    return _page(f"{riot_id} pool audit", body,
                 f"Champion-pool coverage audit for {riot_id}.")


@router.get("/champions", response_class=HTMLResponse)
def champions_page() -> HTMLResponse:
    with db.open_session() as session:
        names = builds.champion_names(session)
        rows = []
        for name in names:
            data = builds.build_for_champion(session, name)
            if data:
                rows.append(data)
    rows.sort(key=lambda d: -d["games"])
    table = "".join(
        f'<tr><td><a href="/champion/{quote(d["champion"])}">{html.escape(d["champion"])}</a></td>'
        f'<td>{d["role"]}</td><td>{d["games"]}</td><td>{d["winrate_pct"]}%</td></tr>'
        for d in rows
    )
    body = (f'<h1>Champions in our dataset</h1><p class="muted small">Presence and win rate '
            f'across the Summoner’s Rift matches we have aggregated ({len(rows)} champions '
            f'with enough games).</p>'
            f'<div class="card"><table><tr><th>Champion</th><th>Main role</th>'
            f'<th>Games</th><th>Win rate</th></tr>{table}</table></div>')
    return _page("Champions", body, "Champion presence and win rates from our own aggregation.")


@router.get("/champion/{name}", response_class=HTMLResponse)
def champion_page(name: str) -> HTMLResponse:
    with db.open_session() as session:
        data = builds.build_for_champion(session, name)
        matchup_rows = []
        if data:
            role_data = pool.role_dataset(session, data["role"])
            for (a, b), (games, wins) in sorted(
                role_data["matchups"].items(), key=lambda kv: -kv[1][0]
            ):
                if a.lower() == name.lower() and games >= builds.MIN_MATCHUP_GAMES:
                    matchup_rows.append((b, games, round(wins / games * 100)))
    if not data:
        return _page(name, f'<h1>{html.escape(name)}</h1><p class="muted">Not enough games '
                     'in our dataset for this champion yet — the crawler is still working.</p>')
    items = "".join(
        f'<tr><td>{i + 1}.</td><td>{html.escape(it["name"])}</td>'
        f'<td>{it["pct"]}%</td><td class="muted">{it["games"]} games</td></tr>'
        for i, it in enumerate(data["core_items"])
    )
    matchups = "".join(
        f'<tr><td><a href="/champion/{quote(op)}">{html.escape(op)}</a></td>'
        f'<td>{games}</td><td>{wr}%</td></tr>'
        for op, games, wr in matchup_rows[:10]
    ) or '<tr><td colspan="3" class="muted">no qualifying lane pairings yet</td></tr>'
    body = f"""
<h1>{html.escape(data["champion"])} <span class="muted small">· {data["role"]}</span></h1>
<p class="muted small">{data["games"]} games in our dataset · {data["winrate_pct"]}% win rate</p>
<div class="card"><h2 style="margin-top:0">Most-built core items</h2>
<table><tr><th></th><th>Item</th><th>Build rate</th><th></th></tr>{items}</table></div>
<div class="card"><h2 style="margin-top:0">Lane matchups ({data["role"]})</h2>
<table><tr><th>Opponent</th><th>Games</th><th>{html.escape(data["champion"])} win rate</th></tr>
{matchups}</table>
<p class="muted small">Own-data lane records; small samples are listed as-is — judge accordingly.</p></div>
"""
    return _page(f"{data['champion']} — builds & matchups", body,
                 f"{data['champion']}: most-built items and lane matchups from our aggregation.")
