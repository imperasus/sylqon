"""Public web pages — the S3 website MVP (roadmap §5.2).

Server-rendered HTML straight from the service (no build step, no JS
framework): a Riot-ID → pool-audit report page plus SEO-friendly champion
pages computed from our own Match-V5 aggregation. Visual language follows
the landing page ("Graphite Volt" — neutral graphite, lime accent).

ToS framing rule: every number on these pages measures *pool coverage* or
champion presence in our dataset — never player skill. No MMR/ELO anywhere.
"""
from __future__ import annotations

import html
import logging
import threading
import time
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app import builds, config, db, pool, regions

log = logging.getLogger(__name__)

router = APIRouter()

# Graphite Volt tokens — 1:1 with ui/src/index.css and landing/landing.html:
# neutral graphite, lime primary + amber grace, Space Grotesk + Inter + JetBrains
# Mono. Flat hairline surfaces (no glow/glass) — the "pro-analytics" look.
_CSS = """
:root{--bg:#0e0e0f;--surface:#19191a;--surface2:#212123;--text:#f0f0f1;
--muted:#8a8b8e;--accent:#a3e635;--accent-2:#fbbf24;--red:#f87171;--border:#2a2a2d;
--font-display:"Space Grotesk",system-ui,sans-serif;
--font-body:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
--font-mono:"JetBrains Mono",ui-monospace,SFMono-Regular,monospace}
*{box-sizing:border-box}body{margin:0;font:16px/1.6 var(--font-body);
background:var(--bg);color:var(--text)}a{color:var(--accent);text-decoration:none}
.wrap{max-width:1000px;margin:0 auto;padding:0 1.2rem}
header{border-bottom:1px solid var(--border);background:rgba(14,14,15,.9)}
header .wrap{display:flex;align-items:center;justify-content:space-between;min-height:60px}
.brand{display:inline-flex;align-items:center;gap:.55rem;font-family:var(--font-display);
font-weight:700;letter-spacing:.04em;color:var(--text);font-size:1.15rem}
.brand svg{width:22px;height:22px;flex:none}
.brand span{color:var(--accent)}
nav a{margin-left:1.2rem;color:var(--muted);font-size:.9rem}nav a:hover{color:var(--text)}
h1,h2,h3{font-family:var(--font-display);font-weight:600;letter-spacing:-.01em}
h1{font-size:1.7rem;margin:2rem 0 .4rem}h2{font-size:1.15rem;margin:1.6rem 0 .6rem}
.muted{color:var(--muted)}.small{font-size:.85rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
padding:1.1rem 1.3rem;margin:1rem 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:.8rem}
.score{font-family:var(--font-mono);font-size:2.2rem;font-weight:700;color:var(--accent)}
.bar{height:8px;border-radius:4px;background:var(--surface2);overflow:hidden;margin:.25rem 0 .6rem}
.bar i{display:block;height:100%;background:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{text-align:left;padding:.45rem .6rem;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em}
.tag{display:inline-block;font-size:.72rem;font-weight:600;padding:.15rem .55rem;
border-radius:999px;border:1px solid var(--border);color:var(--accent);margin-right:.3rem}
.tag.warn{color:var(--red)}
input[type=text],select{background:var(--surface2);border:1px solid var(--border);color:var(--text);
padding:.65rem .9rem;border-radius:8px;font-size:1rem;font-family:inherit}
input[type=text]{width:280px;max-width:60vw}
select{cursor:pointer}
.searchbar{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
button{background:var(--accent);color:#0e0e0f;border:0;padding:.68rem 1.2rem;border-radius:8px;
font-family:var(--font-display);font-weight:700;font-size:.95rem;cursor:pointer}
button:hover{filter:brightness(1.08)}
section{scroll-margin-top:80px}
.hero{padding:2.6rem 0 .6rem;max-width:64ch}
.eyebrow{font-family:var(--font-display);text-transform:uppercase;letter-spacing:.14em;
font-size:.74rem;font-weight:600;color:var(--accent);margin:0 0 .6rem}
.hero h1{font-size:clamp(2rem,4.5vw,2.9rem);line-height:1.08;margin:0 0 .8rem}
.hl{color:var(--accent)}
.lead{color:var(--muted);font-size:1.08rem;line-height:1.55;margin:0 0 1.4rem;max-width:58ch}
.cta-row{display:flex;flex-wrap:wrap;gap:.7rem;margin-bottom:.9rem}
a.btn{display:inline-flex;align-items:center;background:var(--accent);color:#0e0e0f;
padding:.7rem 1.25rem;border-radius:8px;font-family:var(--font-display);font-weight:700;font-size:.95rem}
a.btn:hover{filter:brightness(1.08)}
a.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--border)}
a.btn.ghost:hover{border-color:var(--muted);filter:none}
.trust{margin:.2rem 0 0}
.profile-head{display:flex;align-items:center;gap:1rem;margin-top:1.4rem}
.pfp{border-radius:12px;border:1px solid var(--border)}
.lvl{color:var(--muted);font-size:.9rem}
.rank .rank-tier{font-family:var(--font-display);font-size:1.3rem;font-weight:600;
color:var(--accent);margin:.15rem 0}
.champ-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.7rem}
.champ{background:var(--surface);border:1px solid var(--border);border-radius:12px;
padding:.7rem;text-align:center}
.champ img{border-radius:8px;margin-bottom:.4rem}
.champ-name{font-family:var(--font-display);font-weight:600;font-size:.92rem}
.mlist{display:flex;flex-direction:column;gap:.5rem;margin-top:1rem}
.mrow{display:flex;align-items:center;gap:.9rem;background:var(--surface);color:var(--text);
border:1px solid var(--border);border-left-width:3px;border-radius:10px;padding:.6rem .9rem}
.mrow:hover{border-color:var(--muted)}
.mrow.win{border-left-color:var(--accent)}.mrow.loss{border-left-color:var(--red)}
.mrow>img{width:44px;height:44px;border-radius:8px;flex:none}
.mrow .mmeta{min-width:118px}
.mrow .res{font-family:var(--font-display);font-weight:700;font-size:.85rem}
.mrow .res.win{color:var(--accent)}.mrow .res.loss{color:var(--red)}
.mrow .champ-lbl{font-family:var(--font-display);font-weight:600}
.mrow .kda{font-family:var(--font-mono);font-weight:700}
.mspacer{flex:1}
.team{margin:1.2rem 0}
.team-head{display:flex;justify-content:space-between;align-items:baseline;margin:.2rem 0 .4rem}
.team-head .res{font-family:var(--font-display);font-weight:700}
.team-head .res.win{color:var(--accent)}.team-head .res.loss{color:var(--red)}
.sb-wrap{overflow-x:auto}
.cchamp{display:flex;align-items:center;gap:.5rem;font-weight:600}
.cchamp img{width:32px;height:32px;border-radius:6px;flex:none}
.num{font-family:var(--font-mono);text-align:right;white-space:nowrap}
.items{display:flex;gap:2px}
.items img{width:22px;height:22px;border-radius:4px;background:var(--surface2)}
.stats-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:.7rem}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:.8rem 1rem}
.stat .v{font-family:var(--font-mono);font-size:1.5rem;font-weight:700;color:var(--accent)}
.stat .l{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.08em}
.lesson{border-left:3px solid var(--accent-2)}
.tabs{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.6rem 0}
.tab{padding:.38rem .8rem;border:1px solid var(--border);border-radius:999px;color:var(--muted);
font-size:.82rem;font-family:var(--font-display);font-weight:600}
.tab:hover{color:var(--text)}
.tab.active{background:var(--accent);color:#0e0e0f;border-color:var(--accent)}
.hot{color:var(--accent-2)}
footer{border-top:1px solid var(--border);margin-top:3rem;padding:1.4rem 0;color:var(--muted);font-size:.78rem}
"""

# Google Fonts — served pages, so an external stylesheet link is fine (unlike
# CSP-locked artifacts). Matches the weights landing/landing.html loads.
_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&"
    'family=JetBrains+Mono:wght@500;700&display=swap">'
)

# "Signal S" mark — three offset equalizer bars + one amber data-point dot.
# Same geometry as ui/src/components/BrandMark.jsx (vars remapped to web.py's).
_MARK = (
    '<svg viewBox="0 0 24 24" role="img" aria-label="Sylqon"><title>Sylqon</title>'
    '<rect x="7" y="3" width="14" height="4" rx="1" fill="var(--accent)"/>'
    '<rect x="3" y="10" width="18" height="4" rx="1" fill="var(--accent)"/>'
    '<rect x="3" y="17" width="14" height="4" rx="1" fill="var(--accent)"/>'
    '<circle cx="19.5" cy="19" r="2" fill="var(--accent-2)"/></svg>'
)

# Desktop app release page (GitHub Pages); same target the footer/nav point to.
_DOWNLOAD_URL = "https://imperasus.github.io/sylqon/"

# The radical cut (docs/WEB_DRAFT_TERV.md §5): the generic lookup pages stay
# served through a 90-day sunset window but leave the index — main.py stamps
# an X-Robots-Tag: noindex header on these path prefixes (equivalent to the
# meta tag for crawlers, and it covers the cached champion pages centrally).
NOINDEX_PREFIXES = ("/summoner/", "/match/", "/leaderboard", "/champions",
                    "/champion/", "/search", "/pool-report")


def _page(title: str, body: str, description: str = "") -> HTMLResponse:
    desc = html.escape(description or
                       "Sylqon pool coverage — champion pool analysis from official Riot data.")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Sylqon</title>
<meta name="description" content="{desc}">
{_FONTS}
<style>{_CSS}</style></head><body>
<header><div class="wrap">
<a class="brand" href="/">{_MARK}SYL<span>QON</span> <span class="muted small">pool coverage</span></a>
<nav><a href="/daily">Daily Draft</a><a href="/draft">Draft Lab</a>
<a href="/audit">Pool audit</a><a href="/download">Download</a></nav>
</div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap">Sylqon is an unofficial fan-made tool. Not endorsed by Riot Games.
All statistics are aggregated from official Riot Games APIs and measure pool coverage and
champion presence in our dataset — never player skill.</div></footer>
</body></html>""")


def _bar(value: int) -> str:
    return f'<div class="bar"><i style="width:{max(2, min(100, value))}%"></i></div>'


def _fmt_duration(secs: int | None) -> str:
    if not secs:
        return "—"
    minutes, seconds = divmod(int(secs), 60)
    return f"{minutes}:{seconds:02d}"


def _fmt_ago(created_ms: int | None) -> str:
    """Relative age of a match from its epoch-ms creation time."""
    if not created_ms:
        return ""
    delta = time.time() - created_ms / 1000
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _gold_svg(points: list[dict]) -> str:
    """Team gold-difference chart as a server-rendered SVG (build-less; native
    <title> tooltips). Poles are direct-labeled and split by the zero axis, so
    identity is never color-alone; lime/red match the page's team semantics."""
    W, H, PAD_L, PAD_R, PAD_T, PAD_B = 720, 190, 52, 10, 20, 26
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    last_min = max(points[-1]["minute"], 1)
    max_abs = max(1000, max(abs(p["diff"]) for p in points))

    def sx(minute: float) -> float:
        return PAD_L + minute / last_min * plot_w

    def sy(diff: float) -> float:
        return PAD_T + plot_h / 2 - diff / max_abs * (plot_h / 2)

    zero_y = sy(0)
    line = " L ".join(f"{sx(p['minute']):.1f},{sy(p['diff']):.1f}" for p in points)
    area = (f"M {sx(points[0]['minute']):.1f},{zero_y:.1f} L {line} "
            f"L {sx(points[-1]['minute']):.1f},{zero_y:.1f} Z")

    x_ticks = "".join(
        f'<text x="{sx(m):.1f}" y="{H - 8}" text-anchor="middle">{m}</text>'
        for m in range(0, int(last_min) + 1, 5)
    )
    step = plot_w / max(1, len(points) - 1)
    hover = "".join(
        f'<rect x="{sx(p["minute"]) - step / 2:.1f}" y="{PAD_T}" width="{step:.1f}" '
        f'height="{plot_h}" fill="transparent"><title>min {p["minute"]:.0f}: '
        f'{"+" if p["diff"] >= 0 else "−"}{abs(p["diff"]) / 1000:.1f}k '
        f'{"blue" if p["diff"] >= 0 else "red"} lead</title></rect>'
        for p in points
    )
    k = max_abs / 1000
    return f"""
<svg viewBox="0 0 {W} {H}" role="img" aria-label="Team gold difference over time"
 style="width:100%;height:auto" font-family="JetBrains Mono,monospace" font-size="10">
<defs>
<clipPath id="gc-up"><rect x="0" y="0" width="{W}" height="{zero_y:.1f}"/></clipPath>
<clipPath id="gc-dn"><rect x="0" y="{zero_y:.1f}" width="{W}" height="{H - zero_y:.1f}"/></clipPath>
</defs>
<path d="{area}" fill="var(--accent)" opacity=".22" clip-path="url(#gc-up)"/>
<path d="{area}" fill="var(--red)" opacity=".22" clip-path="url(#gc-dn)"/>
<line x1="{PAD_L}" y1="{zero_y:.1f}" x2="{W - PAD_R}" y2="{zero_y:.1f}"
 stroke="var(--border)" stroke-width="1"/>
<path d="M {line}" fill="none" stroke="var(--text)" stroke-width="2"
 stroke-linejoin="round" stroke-linecap="round"/>
<g fill="var(--muted)">
<text x="{PAD_L - 6}" y="{PAD_T + 8}" text-anchor="end">+{k:.0f}k</text>
<text x="{PAD_L - 6}" y="{zero_y + 3:.1f}" text-anchor="end">0</text>
<text x="{PAD_L - 6}" y="{H - PAD_B}" text-anchor="end">−{k:.0f}k</text>
{x_ticks}
</g>
<text x="{PAD_L + 8}" y="{PAD_T + 12}" fill="var(--accent)" font-weight="700"
 letter-spacing=".08em">BLUE LEAD</text>
<text x="{PAD_L + 8}" y="{H - PAD_B - 6}" fill="var(--red)" font-weight="700"
 letter-spacing=".08em">RED LEAD</text>
{hover}
</svg>"""


def _region_options(selected: str = regions.DEFAULT_PLATFORM) -> str:
    return "".join(
        f'<option value="{code}"{" selected" if code == selected else ""}>{label}</option>'
        for code, label in regions.PLATFORM_CHOICES
    )


# NOTE: the "/" homepage lives in webdaily.py — the daily puzzle IS the hero
# (docs/WEB_DRAFT_TERV.md §5: the hero doesn't tell, it makes you play).


@router.get("/download", response_class=HTMLResponse)
def download_page() -> HTMLResponse:
    """Download + the "why you can trust installing this" story — the explicit
    counter-position to the companion-app pain points (Overwolf, RAM, ads)."""
    body = f"""
<section class="hero">
<p class="eyebrow">Sylqon Desktop · Windows</p>
<h1>The counter-draft AI, <span class="hl">live in your champ select.</span></h1>
<p class="lead">Sylqon reads your live Champion Select, names the strongest pick from your own
pool, then builds the items, runes and summoner spells that beat those specific five enemies —
and writes the whole loadout into your client automatically.</p>
<div class="cta-row"><a class="btn" href="{_DOWNLOAD_URL}">Download for Windows</a></div>
</section>
<h2>Why you can trust installing it</h2>
<div class="grid">
<div class="card"><strong>100% local</strong><p class="muted small">Runs entirely on your PC
against the official League client API. Your credentials never leave your machine; the AI is
a local Ollama model.</p></div>
<div class="card"><strong>No Overwolf, no ads</strong><p class="muted small">A lean native app —
no ad overlays, no gigabyte-scale RAM footprint, no bundled extras.</p></div>
<div class="card"><strong>Read-only in game</strong><p class="muted small">The in-game coach
only reads Riot's official Live Client Data API. No memory reads, no injection — nothing that
touches the game process.</p></div>
<div class="card"><strong>Open releases</strong><p class="muted small">Every build is published
on GitHub with auto-update — you can see exactly what ships.</p></div>
</div>"""
    return _page("Download Sylqon", body,
                 "Download the Sylqon counter-draft desktop app for Windows — 100% local, "
                 "no Overwolf, read-only in game.")


@router.get("/pool-report")
def pool_report_redirect(riot_id: str | None = Query(None)) -> RedirectResponse:
    """Permanent home of the audit is /audit ("your personal difficulty map")."""
    url = f"/audit?riot_id={quote(riot_id)}" if riot_id else "/audit"
    return RedirectResponse(url, status_code=301)


@router.get("/audit", response_class=HTMLResponse)
def audit_page(riot_id: str | None = Query(None)) -> HTMLResponse:
    if not riot_id:
        body = """
<section class="hero">
<p class="eyebrow">Pool audit</p>
<h1>Your personal <span class="hl">difficulty map.</span></h1>
<p class="lead">Which comps and threats does your champion pool leave uncovered? Paste a Riot ID
and we audit the pool against the meta, from our own aggregation of official Riot match data.</p>
</section>
<div class="card"><form action="/audit" method="get" class="searchbar">
<input type="text" name="riot_id" placeholder="Name#TAG" required>
<button type="submit">Audit my pool</button></form>
<div class="muted small" style="margin-top:.5rem">Official Riot data only. Pool analysis
measures coverage, not player skill.</div></div>
<h2>What you get</h2>
<div class="grid">
<div class="card"><strong>Coverage score</strong><p class="muted small">One number per role,
blending performance, blind-pick safety and counter coverage.</p></div>
<div class="card"><strong>Suggested 3-champion pool</strong><p class="muted small">Anchored on
your comfort pick, filled to cover the gaps your current pool leaves open.</p></div>
<div class="card"><strong>Uncovered threats</strong><p class="muted small">The common picks in
your role that none of your champions hold an even lane record against.</p></div>
</div>"""
        return _page("Pool audit — your personal difficulty map", body,
                     "Audit how well your champion pool covers the meta — coverage, "
                     "blind-pick safety and counter coverage from official Riot data.")
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


@router.get("/search", response_class=HTMLResponse)
def search_redirect(region: str = "euw1", riot_id: str = "") -> HTMLResponse:
    """Region + Name#TAG search form target → redirect to the profile page."""
    platform = regions.normalize(region)
    game_name, _, tag_line = riot_id.partition("#")
    if not game_name.strip() or not tag_line.strip():
        return _page("Search", '<h1>Invalid Riot ID</h1><p class="muted">Use the '
                     "<code>Name#TAG</code> form.</p>")
    url = (f"/summoner/{platform}/{quote(game_name.strip(), safe='')}/"
           f"{quote(tag_line.strip(), safe='')}")
    return RedirectResponse(url, status_code=303)


@router.get("/summoner/{region}/{game_name}/{tag_line}", response_class=HTMLResponse)
def summoner_page(region: str, game_name: str, tag_line: str) -> HTMLResponse:
    riot_id = f"{game_name}#{tag_line}"
    platform = regions.normalize(region)
    from app.main import _ingest_service  # resolved lazily; may be None in tests

    if _ingest_service is None:
        return _page("Summoner", "<h1>Service unavailable</h1>"
                     '<p class="muted">Try again in a moment.</p>')
    from app import profile as profile_mod

    data = profile_mod.build_profile(
        _ingest_service._riot, game_name.strip(), tag_line.strip(), platform=platform)
    if data is None:
        return _page("Player not found", f'<h1>Player not found</h1><p class="muted">'
                     f'No account found for <strong>{html.escape(riot_id)}</strong> — '
                     f'check the spelling (Name#TAG).</p>')

    icon = (f'<img class="pfp" src="{html.escape(data["profile_icon_url"])}" alt="" '
            f'width="72" height="72">' if data.get("profile_icon_url") else "")
    level = (f'<span class="lvl">Level {data["summoner_level"]}</span>'
             if data.get("summoner_level") else "")

    if data["ranked"]:
        rank_cards = "".join(
            f'<div class="card rank"><div class="muted small">{html.escape(r["label"])}</div>'
            f'<div class="rank-tier">{html.escape((r["tier"] or "").title())} '
            f'{html.escape(r["division"] or "")}</div>'
            f'<div class="muted small">{r["lp"]} LP · {r["wins"]}W/{r["losses"]}L'
            + (f' · {r["winrate"]}% WR' if r["winrate"] is not None else "")
            + "</div></div>"
            for r in data["ranked"]
        )
    else:
        rank_cards = '<div class="card rank"><div class="muted">Unranked</div></div>'

    champ_cells = "".join(
        '<div class="champ">'
        + (f'<img src="{html.escape(c["square_url"])}" alt="{html.escape(c["name"])}" '
           f'width="56" height="56" loading="lazy">' if c["square_url"] else "")
        + f'<div class="champ-name">{html.escape(c["name"])}</div>'
        + f'<div class="muted small">{(c["mastery_points"] or 0):,} pts'
        + (f' · M{c["mastery_level"]}' if c["mastery_level"] else "")
        + "</div></div>"
        for c in data["top_champions"]
    ) or '<div class="muted">No mastery data.</div>'

    from app import insights as insights_mod

    with db.open_session() as session:
        ins = insights_mod.build_insights(session, data["puuid"], lang="en")

    if ins:
        tiles = []
        form = ins["recent_form"]
        for label, value in (
            ("Win rate", f'{ins["winrate"]}%'),
            ("KDA", f'{ins["kda"]}'),
            ("CS / min", "—" if ins["avg_cs_per_min"] is None else f'{ins["avg_cs_per_min"]}'),
            ("Vision / game", "—" if ins["avg_vision"] is None else f'{ins["avg_vision"]}'),
            (f'Last {form["games"]}', f'{form["wins"]}W/{form["games"] - form["wins"]}L'),
        ):
            tiles.append(f'<div class="stat"><div class="v">{value}</div>'
                         f'<div class="l">{label}</div></div>')
        lesson = ins["lesson"]
        lesson_html = ""
        if lesson and lesson.get("text"):
            lesson_html = (
                f'<div class="card lesson"><div class="muted small">Latest lesson · '
                f'{html.escape(lesson.get("champion") or "")}</div>'
                f'<p style="margin:.4rem 0 0">{html.escape(lesson["text"])}</p></div>'
            )
        insights_html = (
            f'<h2>Coaching insights <span class="muted small">· last {ins["games"]} stored '
            f'matches</span></h2><div class="stats-row">{"".join(tiles)}</div>{lesson_html}'
        )
    else:
        insights_html = ('<h2>Coaching insights</h2><p class="muted">No stored matches yet — '
                         'open the match history to fetch recent games, then check back.</p>')

    body = f"""
<div class="profile-head">{icon}<div>
<h1 style="margin:.2rem 0">{html.escape(data["riot_id"])}</h1>{level}</div></div>
<div class="cta-row" style="margin:.6rem 0 1.2rem">
<a class="btn" href="/summoner/{platform}/{quote(data["game_name"], safe="")}/{quote(data["tag_line"], safe="")}/matches">Match history</a>
<a class="btn ghost" href="/pool-report?riot_id={quote(riot_id)}">Audit champion pool</a>
<a class="btn ghost" href="/">Home</a></div>
<h2>Ranked</h2><div class="grid">{rank_cards}</div>
<h2>Top champions <span class="muted small">· mastery</span></h2>
<div class="champ-grid">{champ_cells}</div>
{insights_html}
<p class="muted small" style="margin-top:1.2rem">Official Riot data (Account, Summoner,
League &amp; Champion Mastery). Insights are coaching aids computed from your own stored
matches — descriptive display only.</p>"""
    return _page(f"{data['riot_id']} — profile", body,
                 f"Summoner profile for {data['riot_id']}: level, rank and top champion mastery.")


@router.get("/summoner/{region}/{game_name}/{tag_line}/matches", response_class=HTMLResponse)
def matches_page(region: str, game_name: str, tag_line: str) -> HTMLResponse:
    riot_id = f"{game_name}#{tag_line}"
    platform = regions.normalize(region)
    cluster = regions.cluster_for(platform)
    from app.main import _ingest_service  # resolved lazily; may be None in tests

    if _ingest_service is None:
        return _page("Match history", "<h1>Service unavailable</h1>"
                     '<p class="muted">Try again in a moment.</p>')
    from app import matches as matches_mod
    from app.crawler import AccountNotFound

    not_found = (f'<h1>Player not found</h1><p class="muted">No account found for '
                 f"<strong>{html.escape(riot_id)}</strong> — check the spelling (Name#TAG).</p>")

    puuid = None
    try:
        puuid = _ingest_service.ingest(
            game_name.strip(), tag_line.strip(), platform=platform).puuid
    except AccountNotFound:
        return _page("Player not found", not_found)
    except Exception as exc:  # transient — fall back to a direct resolve + stored data
        log.info("matches-page ingest failed for %s: %s", riot_id, exc)
    if puuid is None:
        account = _ingest_service._riot.get_account_by_riot_id(
            game_name.strip(), tag_line.strip(), region=cluster)
        puuid = account.get("puuid") if account else None
    if puuid is None:
        return _page("Player not found", not_found)

    with db.open_session() as session:
        rows = matches_mod.list_for_puuid(session, puuid, limit=20)

    prof = f'/summoner/{platform}/{quote(game_name, safe="")}/{quote(tag_line, safe="")}'
    if not rows:
        body = (f'<h1>{html.escape(riot_id)} <span class="muted small">· matches</span></h1>'
                '<p class="muted">No matches stored yet — check back in a minute while we '
                f'fetch them.</p><div class="cta-row"><a class="btn ghost" href="{prof}">'
                "Back to profile</a></div>")
        return _page(f"{riot_id} — matches", body)

    items = []
    for r in rows:
        res = "win" if r["win"] else "loss"
        label = "Victory" if r["win"] else "Defeat"
        cspm = f' · {r["cs_per_min"]}/min' if r["cs_per_min"] is not None else ""
        icon = (f'<img src="{html.escape(r["champion_url"])}" alt="">'
                if r["champion_url"] else "")
        items.append(
            f'<a class="mrow {res}" href="/match/{quote(r["match_id"], safe="")}">{icon}'
            f'<div class="mmeta"><div class="res {res}">{label}</div>'
            f'<div class="muted small">{html.escape(r["queue"])} · {_fmt_ago(r["created"])}</div></div>'
            f'<div class="champ-lbl">{html.escape(r["champion"] or "?")}'
            f'<div class="muted small">{html.escape((r["role"] or "").title())}</div></div>'
            '<div class="mspacer"></div>'
            f'<div style="text-align:right"><span class="kda">'
            f'{r["kills"]}/{r["deaths"]}/{r["assists"]}</span>'
            f'<div class="muted small">{r["cs"]} CS{cspm}</div></div></a>'
        )
    body = (f'<h1>{html.escape(riot_id)} <span class="muted small">· matches</span></h1>'
            f'<div class="cta-row" style="margin:.4rem 0"><a class="btn ghost" href="{prof}">'
            f'Profile</a></div><div class="mlist">{"".join(items)}</div>')
    return _page(f"{riot_id} — match history", body,
                 f"Recent matches for {riot_id} from official Riot match data.")


@router.get("/match/{match_id}", response_class=HTMLResponse)
def match_page(match_id: str) -> HTMLResponse:
    from app import matches as matches_mod

    with db.open_session() as session:
        data = matches_mod.detail(session, match_id)
        gold = matches_mod.gold_timeline(session, match_id) if data else None
    if data is None:
        return _page("Match", '<h1>Match not stored</h1><p class="muted">This match is not in '
                     "our dataset yet — open the owner’s match history to fetch it.</p>")

    gold_html = ""
    if gold:
        gold_html = (f'<div class="card"><h2 style="margin-top:0">Gold difference '
                     f'<span class="muted small">· blue − red, per minute</span></h2>'
                     f"{_gold_svg(gold)}</div>")

    teams_html = []
    for team in data["teams"]:
        res = "win" if team["win"] else "loss"
        side = "Blue" if team["team_id"] == 100 else "Red"
        label = "Victory" if team["win"] else "Defeat"
        rows = []
        for p in team["participants"]:
            icon = (f'<img src="{html.escape(p["champion_url"])}" alt="">'
                    if p["champion_url"] else "")
            item_imgs = "".join(f'<img src="{html.escape(u)}" alt="">' for u in p["items"])
            gold = f'{(p["gold"] or 0) / 1000:.1f}k'
            rows.append(
                f'<tr><td><div class="cchamp">{icon}'
                f'<span>{html.escape(p["champion"] or "?")}</span></div></td>'
                f'<td class="num">{p["kills"]}/{p["deaths"]}/{p["assists"]}</td>'
                f'<td class="num">{p["cs"]}</td><td class="num">{gold}</td>'
                f'<td class="num">{(p["damage"] or 0):,}</td>'
                f'<td class="num">{p["vision"] or 0}</td>'
                f'<td><div class="items">{item_imgs}</div></td></tr>'
            )
        teams_html.append(
            f'<div class="team"><div class="team-head">'
            f'<span class="res {res}">{label} — {side} team</span>'
            f'<span class="muted small">{team["kills"]} kills · '
            f'{team["gold"] / 1000:.1f}k gold</span></div>'
            '<div class="sb-wrap"><table><tr><th>Champion</th><th class="num">KDA</th>'
            '<th class="num">CS</th><th class="num">Gold</th><th class="num">Dmg</th>'
            f'<th class="num">Vis</th><th>Items</th></tr>{"".join(rows)}</table></div></div>'
        )

    patch = f' · patch {html.escape(data["patch"])}' if data["patch"] else ""
    head = (f'<h1>Match <span class="muted small">· {html.escape(data["queue"])} · '
            f'{_fmt_duration(data["duration"])}{patch}</span></h1>')
    return _page(f"Match {html.escape(match_id)}", head + gold_html + "".join(teams_html),
                 f"{data['queue']} match scoreboard from official Riot match data.")


@router.get("/leaderboard")
def leaderboard_root() -> RedirectResponse:
    """Bare /leaderboard → the default queue (was a raw JSON 404)."""
    from app import leaderboard as lb

    return RedirectResponse(f"/leaderboard/{lb.DEFAULT_QUEUE}", status_code=303)


@router.get("/leaderboard/{queue}", response_class=HTMLResponse)
def leaderboard_page(queue: str, tier: str = "CHALLENGER", region: str = "euw1") -> HTMLResponse:
    from app import leaderboard as lb
    from app.main import _ingest_service  # resolved lazily; may be None in tests

    platform = regions.normalize(region)
    tier = tier.upper()
    if queue not in lb.QUEUES:
        queue = lb.DEFAULT_QUEUE
    if tier not in lb.TIERS:
        tier = "CHALLENGER"
    if _ingest_service is None:
        return _page("Leaderboard", "<h1>Service unavailable</h1>"
                     '<p class="muted">Try again in a moment.</p>')

    with db.open_session() as session:
        data = lb.get_leaderboard(session, _ingest_service._riot, tier, queue, platform)

    qtabs = "".join(
        f'<a class="tab{" active" if q == queue else ""}" '
        f'href="/leaderboard/{q}?tier={tier}&amp;region={platform}">{html.escape(label)}</a>'
        for q, label in lb.QUEUES.items()
    )
    ttabs = "".join(
        f'<a class="tab{" active" if t == tier else ""}" '
        f'href="/leaderboard/{queue}?tier={t}&amp;region={platform}">{t.title()}</a>'
        for t in lb.TIERS
    )
    region_form = (
        f'<form method="get" action="/leaderboard/{queue}" class="searchbar" '
        f'style="margin-left:auto"><input type="hidden" name="tier" value="{tier}">'
        f'<select name="region" aria-label="Region">{_region_options(platform)}</select>'
        "<button type=\"submit\">Go</button></form>"
    )

    if data and data["rows"]:
        row_html = []
        for r in data["rows"]:
            hot = ' <span class="hot" title="Hot streak">▲</span>' if r["hot_streak"] else ""
            wr = f'{r["winrate"]}%' if r["winrate"] is not None else "—"
            row_html.append(
                f'<tr><td class="num">{r["rank"]}</td>'
                f'<td>{html.escape(r["name"] or "—")}{hot}</td>'
                f'<td class="num">{(r["lp"] or 0):,}</td>'
                f'<td class="num">{r["wins"]}W/{r["losses"]}L</td>'
                f'<td class="num">{wr}</td></tr>'
            )
        table = (f'<div class="sb-wrap"><table><tr><th class="num">#</th><th>Summoner</th>'
                 f'<th class="num">LP</th><th class="num">W/L</th><th class="num">Win%</th></tr>'
                 f'{"".join(row_html)}</table></div>')
    else:
        table = '<p class="muted">Ladder unavailable right now — try again shortly.</p>'

    head = (f'<h1>Leaderboard <span class="muted small">· {platform.upper()} · '
            f'{tier.title()} · {html.escape(lb.QUEUES[queue])}</span></h1>')
    body = (head + f'<div class="tabs">{qtabs}{region_form}</div>'
            f'<div class="tabs">{ttabs}</div>' + table
            + '<p class="muted small" style="margin-top:1rem">Official Riot ladder '
              "(League-V4). Riot IDs resolve a few per refresh and fill in as the board "
              "updates; not-yet-resolved rows show a dash.</p>")
    return _page(f"{tier.title()} leaderboard — {platform.upper()}", body,
                 f"{tier.title()} {lb.QUEUES[queue]} ladder for {platform.upper()} — "
                 "official Riot ladder data.")


@router.get("/champions/{name}")
def champions_name_redirect(name: str) -> RedirectResponse:
    """/champions/Lux → /champion/Lux — the plural form is what people type
    from the /champions index URL (same trap as the bare /leaderboard was)."""
    return RedirectResponse(f"/champion/{quote(name, safe='')}", status_code=303)


@router.get("/champions", response_class=HTMLResponse)
def champions_page() -> HTMLResponse:
    with db.open_session() as session:
        rows = builds.champion_index(session)
    from app import champions

    def _cell(d):
        url = champions.square_url_by_name(d["champion"])
        img = (f'<img src="{html.escape(url)}" alt="" width="28" height="28" loading="lazy">'
               if url else "")
        return (f'<div class="cchamp">{img}<a href="/champion/{quote(d["champion"])}">'
                f'{html.escape(d["champion"])}</a></div>')

    table = "".join(
        f'<tr><td>{_cell(d)}</td>'
        f'<td>{d["role"]}</td><td class="num">{d["games"]}</td>'
        f'<td class="num">{d["winrate_pct"]}%</td></tr>'
        for d in rows
    )
    patch = champions.version()
    patch_lbl = f' <span class="muted small">· patch {html.escape(patch)}</span>' if patch else ""
    body = (f'<h1>Champion meta{patch_lbl}</h1><p class="muted small">Presence and win rate '
            f'across the Summoner’s Rift matches we have aggregated ({len(rows)} champions '
            f'with enough games).</p>'
            f'<div class="card"><table><tr><th>Champion</th><th>Main role</th>'
            f'<th class="num">Games</th><th class="num">Win rate</th></tr>{table}</table></div>')
    return _page("Champion meta", body, "Champion presence and win rates from our own aggregation.")


# Rendered champion pages, keyed by lowercase champion name. Only names that
# resolved to data are stored: misses are index-fast anyway, and the key space
# is arbitrary URL input — caching misses would grow the dict without bound.
# Stale entries are served immediately and refreshed in the background (a cold
# render costs seconds at crawled-dataset scale), so only the first-ever
# render of a champion blocks a visitor — and the startup warmer covers that.
_champ_cache: dict[str, tuple[float, bytes]] = {}
_champ_refreshing: set[str] = set()
_champ_lock = threading.Lock()


def _refresh_champion_page(name: str) -> None:
    """Background re-render of an expired cache entry; single-flight per key."""
    key = name.lower()
    with _champ_lock:
        if key in _champ_refreshing:
            return
        _champ_refreshing.add(key)
    try:
        _render_champion_page(name)
    except Exception:  # a failed refresh keeps serving the stale page
        log.exception("champion page refresh failed for %s", name)
    finally:
        with _champ_lock:
            _champ_refreshing.discard(key)


@router.get("/champion/{name}", response_class=HTMLResponse)
def champion_page(name: str) -> HTMLResponse:
    key = name.lower()
    hit = _champ_cache.get(key)
    if hit:
        if hit[0] <= time.time():  # expired: serve stale, refresh off-thread
            threading.Thread(target=_refresh_champion_page, args=(name,),
                             daemon=True).start()
        return HTMLResponse(hit[1])
    return _render_champion_page(name)


def _render_champion_page(name: str) -> HTMLResponse:
    with db.open_session() as session:
        data = builds.build_for_champion(session, name)
        matchup_rows = []
        if data:
            matchup_rows = builds.champion_matchups(session, data["champion"], data["role"])
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
    resp = _page(f"{data['champion']} — builds & matchups", body,
                 f"{data['champion']}: most-built items and lane matchups from our aggregation.")
    _champ_cache[name.lower()] = (time.time() + config.WEB_CHAMPION_CACHE_TTL, resp.body)
    return resp


def warm_champion_pages() -> int:
    """Render every champion page whose cache entry is missing or expired —
    called from the startup warmer thread so visitors never hit a cold render.
    Returns the number of pages (re)rendered."""
    with db.open_session() as session:
        names = [row["champion"] for row in builds.champion_index(session)]
    warmed = 0
    for n in names:
        hit = _champ_cache.get(n.lower())
        if hit and hit[0] > time.time():
            continue
        try:
            _render_champion_page(n)
            warmed += 1
        except Exception:  # one bad champion must not stop the sweep
            log.exception("champion warmup failed for %s", n)
    return warmed
