import { useMemo } from "react";
import {
  AlertTriangle, Crosshair, Eye, Flame, Lock, Radar, Scale, Swords, TrendingUp, Users,
} from "lucide-react";
import { useStaticData } from "../api.js";
import { DAMAGE_COLORS, ROLE_LABELS, ROLE_ORDER, pct } from "../assets.js";
import { ChampPortrait, Chip, EmptyState, Panel, ThreatBadge } from "./shared.jsx";

/* Playstyle tag → chip tone (mirrors the draft-board scout strip). */
const TAG_TONE = {
  aggressive: "enemy", "carry-threat": "amber", "one-trick": "amber",
  "farm-focused": "accent", playmaker: "ally", calculated: "good",
  frontliner: "ally", "vision-control": "accent",
};

const streakLabel = (s) => (!s || Math.abs(s) < 2 ? null : `${Math.abs(s)}${s > 0 ? "W" : "L"}`);

/* A single glanceable flag derived from recent form / comfort. */
function playerFlag(p) {
  const f = p.recent_form || {};
  const s = f.streak || 0;
  if (s <= -3) return { label: "tilt risk", tone: "amber", icon: Flame };
  if (s >= 3 && (f.win_rate || 0) >= 0.58) return { label: "hot", tone: "good", icon: TrendingUp };
  if (p.comfort && (p.comfort.share || 0) >= 0.55) return { label: "one-trick", tone: "amber", icon: Crosshair };
  return null;
}

function Meter({ value, tone = "accent" }) {
  const bg = { accent: "bg-accent", ally: "bg-ally", enemy: "bg-enemy", amber: "bg-amber", good: "bg-good" }[tone] || "bg-accent";
  return (
    <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
      <div className={`h-full ${bg}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

/* Full ally scouting card: portrait of the locked champ + the player's
   fingerprint (form, comfort, pool, KDA/CS, aggression). */
function AllyCard({ p, champ, patch }) {
  if (p.hidden) {
    return (
      <div className="frost flex items-center gap-2 px-2.5 py-1.5 opacity-70">
        <Lock className="h-3.5 w-3.5 shrink-0 text-white/35" />
        <span className="truncate text-[11px] text-white/45">{p.name} · history hidden</span>
      </div>
    );
  }
  const f = p.recent_form || {};
  const wr = f.games ? f.win_rate : null;
  const flag = playerFlag(p);
  const tags = (p.playstyle_tags || []).slice(0, 2);
  const kda = p.avg_kda || {};
  const pool = (p.champion_pool || []).slice(0, 4);
  const accent = p.is_self ? "accent" : "ally";

  return (
    <div className={`frost ${p.is_self ? "frost-accent" : ""} flex flex-col gap-1 p-1.5`}>
      <div className="flex items-center gap-1.5">
        <ChampPortrait slug={champ?.slug || p.comfort?.slug} patch={patch} size="h-7 w-7" accent={accent} title={champ?.name || p.comfort?.champion} />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="flex items-center gap-1">
            <span className="truncate text-[11px] font-bold text-white/90">{p.name}</span>
            {p.is_self && <span className="text-[8px] font-bold tracking-widest text-accent">YOU</span>}
          </div>
          <div className="text-[9px] font-bold tracking-widest text-white/50">
            {ROLE_LABELS[p.position || p.main_role] || "—"} · {p.games_analyzed}g
          </div>
          {p.rank && (
            <span className="text-[9px] font-bold tracking-widest text-amber/80">{p.rank}</span>
          )}
        </div>
        {flag && (
          <Chip tone={flag.tone}>
            <flag.icon className="mr-0.5 inline h-2.5 w-2.5" />{flag.label}
          </Chip>
        )}
      </div>

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tags.map((t) => <Chip key={t} tone={TAG_TONE[t] || "muted"}>{t}</Chip>)}
        </div>
      )}

      <div className="flex items-center gap-2">
        <span className={`w-9 shrink-0 font-mono text-[11px] font-bold tabular-nums ${wr != null && wr >= 0.5 ? "text-good" : "text-enemy/80"}`}>
          {wr != null ? pct(wr) : "—"}
        </span>
        <Meter value={(wr ?? 0.5) * 100} tone={wr != null && wr >= 0.5 ? "good" : "amber"} />
        {streakLabel(f.streak) && (
          <span className={`shrink-0 font-mono text-[10px] ${f.streak > 0 ? "text-good/80" : "text-enemy/80"}`}>{streakLabel(f.streak)}</span>
        )}
        {p.comfort?.champion && (
          <div className="flex shrink-0 items-center gap-1"
               title={`mains ${p.comfort.champion}${p.comfort.mastery_points ? ` · ${(p.comfort.mastery_points / 1000).toFixed(0)}k mastery` : ""}`}>
            <ChampPortrait slug={p.comfort.slug} patch={patch} size="h-5 w-5" round title={p.comfort.champion} />
            {p.comfort.win_rate != null
              ? <span className="font-mono text-[10px] text-white/50">{pct(p.comfort.win_rate)}</span>
              : p.comfort.mastery_points
                ? <span className="font-mono text-[10px] text-white/35">{(p.comfort.mastery_points / 1000).toFixed(0)}k</span>
                : null}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 border-t border-white/8 pt-1">
        <div className="flex gap-0.5">
          {pool.map((c) => (
            <ChampPortrait key={c.champion_id} slug={c.slug} patch={patch} size="h-5 w-5" round
                           title={`${c.champion} · ${c.games}g ${pct(c.win_rate)}`} />
          ))}
        </div>
        <span className="ml-auto font-mono text-[10px] text-white/45" title="avg KDA · CS/min">
          {kda.ratio != null ? kda.ratio.toFixed(1) : "—"} KDA · {p.avg_cs_per_min ?? 0} cs
        </span>
        <div className="flex w-10 shrink-0 items-center gap-1" title="aggression">
          <Flame className="h-2.5 w-2.5 text-enemy/60" />
          <Meter value={(p.aggression ?? 0) * 100} tone="enemy" />
        </div>
      </div>
    </div>
  );
}

/* Enemy card: champion threat profile is known from the draft now; the player
   fingerprint resolves once the game starts (read-only Live Client Data). */
function EnemyCard({ e, scout, patch }) {
  if (scout && !scout.hidden && scout.games_analyzed > 0) {
    return <AllyCard p={{ ...scout, is_self: false }} champ={e} patch={patch} />;
  }
  if (!e) {
    return (
      <div className="frost flex min-h-[44px] items-center gap-2 px-2.5 opacity-40">
        <div className="h-7 w-7 rounded border border-dashed border-white/15" />
        <span className="text-[10px] tracking-widest text-white/30">AWAITING</span>
      </div>
    );
  }
  return (
    <div className="frost flex flex-col gap-1.5 p-2">
      <div className="flex items-center gap-2">
        <ChampPortrait slug={e.slug} patch={patch} size="h-8 w-8" accent="enemy" title={e.name} />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[12px] font-bold text-white/90">{e.name}</div>
          <div className="flex items-center gap-1 text-[9px] font-bold tracking-widest text-white/40">
            <span>{ROLE_LABELS[e.role] || "—"}</span>
            {e.damage_type && e.damage_type !== "—" && (
              <span className={`rounded border px-0.5 ${DAMAGE_COLORS[e.damage_type] || ""}`}>{e.damage_type}</span>
            )}
          </div>
        </div>
        <span className="flex shrink-0 items-center gap-1 text-[9px] font-bold tracking-wide text-white/30">
          <Lock className="h-3 w-3" /> SCOUT IN-GAME
        </span>
      </div>
      {e.threats?.length > 0 && (
        <div className="flex flex-wrap gap-0.5">
          {e.threats.slice(0, 3).map((t) => <ThreatBadge key={t} threat={t} />)}
        </div>
      )}
    </div>
  );
}

/* Live in-game readout for one player (read-only Live Client Data): champion,
   level, K/D/A and CS. Used for the enemy column once the game starts, where
   historical fingerprints aren't available (Riot doesn't expose enemy puuids). */
function LivePlayerCard({ p, slug, patch, side = "enemy" }) {
  const kda = ((p.kills + p.assists) / Math.max(1, p.deaths)).toFixed(1);
  const kdaColor = parseFloat(kda) >= 3 ? "text-good" : parseFloat(kda) < 1.5 ? "text-enemy/80" : "text-white/75";

  return (
    <div className="frost flex flex-col gap-1 p-1.5">
      {/* Row 1: portrait · name + role · level/dead */}
      <div className="flex items-center gap-1.5">
        <div className={p.is_dead ? "grayscale opacity-60" : ""}>
          <ChampPortrait slug={slug} patch={patch} size="h-7 w-7" accent={side} title={p.champion} />
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[11px] font-bold text-white/85">{p.name || p.champion}</div>
          <div className="text-[9px] font-bold tracking-widest text-white/40">
            {ROLE_LABELS[p.role] || "—"} · {p.champion}
          </div>
          {p.rank && (
            <span className="text-[9px] font-bold tracking-widest text-amber/80">{p.rank}</span>
          )}
        </div>
        {p.is_dead
          ? <Chip tone="bad">DEAD</Chip>
          : <span className="shrink-0 text-[10px] font-bold text-white/40">Lv {p.level}</span>}
      </div>

      {/* Deaths danger bar */}
      <div className="h-0.5 w-full overflow-hidden rounded-full bg-white/8">
        <div
          className="h-full bg-enemy/50"
          style={{ width: `${Math.min(100, p.deaths * 16)}%` }}
        />
      </div>

      {/* Row 2: K/D/A · KDA ratio · CS */}
      <div className="flex items-center gap-2 border-t border-white/8 pt-1 text-[10px]">
        <span className="font-mono font-bold text-white/70">{p.kills}/{p.deaths}/{p.assists}</span>
        <span className={`font-mono font-bold ${kdaColor}`}>{kda} KDA</span>
        <span className="ml-auto font-mono text-white/50">{p.cs} CS</span>
      </div>
    </div>
  );
}

/* Lane-by-lane read. Ally fingerprint is live; the enemy laner's champion is
   known from the draft / live game, and the edge leans on the ally's recent
   form (enemy history isn't available). */
function LaneLadder({ allyByRole, enemyByRole, enemyScoutByRole, patch }) {
  return (
    <Panel title="LANE MATCHUPS" icon={Swords} accent="white" className="gap-1">
      {ROLE_ORDER.map((role) => {
        const a = allyByRole[role];
        const e = enemyByRole[role];
        const es = enemyScoutByRole[role];
        const s = a?.recent_form?.streak || 0;
        const edge = es ? "even" : s >= 3 ? "ally" : s <= -3 ? "enemy" : "even";
        const edgeEl = edge === "ally"
          ? <span className="text-[9px] font-bold text-good">◂ edge</span>
          : edge === "enemy"
            ? <span className="text-[9px] font-bold text-enemy/80">risk ▸</span>
            : <span className="text-[9px] text-white/35">even</span>;
        return (
          <div key={role} className="flex items-center gap-2 rounded px-1.5 py-1 text-[11px] even:bg-white/[0.015]">
            <span className="w-7 shrink-0 font-bold tracking-widest text-white/40">{ROLE_LABELS[role]}</span>
            <span className={`flex-1 truncate ${a?.is_self ? "text-accent-bright" : "text-ally/90"}`}>{a?.name || "—"}</span>
            <span className="w-12 shrink-0 text-center">{edgeEl}</span>
            <span className="flex flex-1 items-center justify-end gap-1 truncate text-enemy/85">
              {e && <ChampPortrait slug={e.slug} patch={patch} size="h-4 w-4" round title={e.name} />}
              <span className="truncate">{e?.name || "—"}</span>
            </span>
          </div>
        );
      })}
    </Panel>
  );
}

function CompareRow({ label, mine, theirs }) {
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between text-[10px]">
        <span className="font-mono font-bold text-ally">{mine}</span>
        <span className="tracking-widest text-white/40">{label}</span>
        <span className="font-mono font-bold text-white/45">{theirs}</span>
      </div>
      <div className="flex h-1 overflow-hidden rounded-full bg-white/10">
        <div className="bg-ally" style={{ width: "52%" }} />
      </div>
    </div>
  );
}

const FLAG_ICON = { good: "text-good", amber: "text-amber", accent: "text-accent" };

/* Team-level read from the ally fingerprints (enemy aggregates fill in once
   enemies are scouted) plus the actionable flags. */
function TeamRead({ allies }) {
  const live = allies.filter((p) => !p.hidden && p.games_analyzed > 0);
  const avg = (sel) => {
    const xs = live.map(sel).filter((x) => x != null);
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  };
  const form = avg((p) => p.recent_form?.win_rate);
  const aggr = avg((p) => p.aggression);
  const kda = avg((p) => p.avg_kda?.ratio);

  const flags = [];
  for (const p of live) {
    const s = p.recent_form?.streak || 0;
    if (s <= -3) flags.push({ icon: Flame, tone: "amber", text: `${p.name} is tilted (${Math.abs(s)}L) — play around them safely.` });
    else if (s >= 3 && (p.recent_form?.win_rate || 0) >= 0.58) flags.push({ icon: TrendingUp, tone: "good", text: `${p.name} is hot (${s}W) — enable them.` });
    if (p.comfort && (p.comfort.share || 0) >= 0.6) flags.push({ icon: Crosshair, tone: "accent", text: `${p.name} one-tricks ${p.comfort.champion} (${pct(p.comfort.share)} of games).` });
  }

  return (
    <Panel title="TEAM READ" icon={Scale} accent="accent" className="gap-2">
      <div className="flex flex-col gap-1.5">
        <CompareRow label="recent form" mine={form != null ? pct(form) : "—"} theirs="—" tone="ally" />
        <CompareRow label="aggression" mine={aggr != null ? aggr.toFixed(2) : "—"} theirs="—" tone="ally" />
        <CompareRow label="avg KDA" mine={kda != null ? kda.toFixed(1) : "—"} theirs="—" tone="ally" />
      </div>
      {flags.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-white/8 pt-2">
          {flags.slice(0, 4).map((fl, i) => (
            <div key={i} className="flex items-start gap-1.5 text-[11px] text-white/70">
              <fl.icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${FLAG_ICON[fl.tone] || "text-accent"}`} />
              <span>{fl.text}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default function PlayersView({ state }) {
  const { champions } = useStaticData();
  const scout = state?.scout;
  const lobby = state?.lobby;
  const patch = state?.cache?.patch || "16.12.1";

  const slugOf = useMemo(() => {
    const m = {};
    for (const c of champions) m[c.name] = c.slug;
    return m;
  }, [champions]);

  // Ally scout fingerprints (includes self), keyed by role for the lane ladder.
  const allies = (scout?.players || []).filter((p) => p.side !== "enemy");
  const enemyScout = (scout?.players || []).filter((p) => p.side === "enemy");

  // Locked champion per ally role, so each card shows the champ they're on.
  const champByRole = useMemo(() => {
    const m = {};
    if (lobby) {
      if (lobby.my_role) m[lobby.my_role] = { name: lobby.my_champion, slug: lobby.my_slug };
      for (const a of lobby.allies || []) if (a.role) m[a.role] = { name: a.name, slug: a.slug || slugOf[a.name] };
    }
    return m;
  }, [lobby, slugOf]);

  const allyByRole = useMemo(() => {
    const m = {};
    for (const p of allies) if (p.position) m[p.position] = p;
    return m;
  }, [allies]);
  const enemyByRole = useMemo(() => {
    const m = {};
    for (const e of lobby?.enemies || []) if (e.role) m[e.role] = e;
    return m;
  }, [lobby]);
  const enemyScoutByRole = useMemo(() => {
    const m = {};
    for (const p of enemyScout) if (p.position) m[p.position] = p;
    return m;
  }, [enemyScout]);

  // Live in-game roster (read-only Live Client Data): enemies with their current
  // champion + live K/D/A/CS. This is how enemies show up in-game — their match
  // *history* isn't available (Riot doesn't expose enemy puuids to third parties).
  const live = state?.live;
  const liveActive = !!live?.active;
  const liveEnemies = useMemo(
    () => (liveActive ? (live.roster || []) : []).filter((p) => p.side === "enemy"),
    [liveActive, live?.roster]);
  const liveEnemyByRole = useMemo(() => {
    const m = {};
    for (const p of liveEnemies) {
      const key = p.role || `__unknown_${p.name}`;
      m[key] = p;
    }
    return m;
  }, [liveEnemies]);
  const inGame = liveEnemies.length > 0;
  const enemyLadderByRole = useMemo(() => {
    if (!inGame) return enemyByRole;
    const m = {};
    for (const p of liveEnemies) if (p.role) m[p.role] = { slug: slugOf[p.champion], name: p.champion };
    return m;
  }, [inGame, liveEnemies, enemyByRole, slugOf]);

  if (!lobby && allies.length === 0 && !liveActive) {
    return (
      <div className="frost h-full">
        <EmptyState icon={Radar} label="NO LOBBY INTEL YET"
                    hint="Player scouting populates during champion select — teammates first, enemies once the game reveals them." />
      </div>
    );
  }

  const allyRoster = ROLE_ORDER.map((r) => allyByRole[r]).filter(Boolean);
  // any allies without a normalized position still get shown
  for (const p of allies) if (!p.position && !allyRoster.includes(p)) allyRoster.push(p);
  const enemyRoster = ROLE_ORDER.map((r) => enemyByRole[r] || null);

  const scoutedAllies = allies.filter((p) => !p.hidden && p.games_analyzed > 0).length;
  const scoutedEnemies = enemyScout.filter((p) => !p.hidden && p.games_analyzed > 0).length;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2.5">
      <div className="frost flex items-center gap-3 px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-[11px] font-bold tracking-widest text-accent/80">
          <Users className="h-4 w-4" /> LOBBY INTEL
        </span>
        <Chip tone="ally">{scoutedAllies}/5 allies</Chip>
        <Chip tone={inGame || scoutedEnemies ? "enemy" : "muted"}>
          {inGame ? `${liveEnemies.length}/5 enemies` : `${scoutedEnemies}/5 enemies`}
        </Chip>
        {!inGame && scoutedEnemies === 0 && (
          <span className="flex items-center gap-1 text-[11px] text-white/40">
            <Lock className="h-3.5 w-3.5" /> enemies appear in-game (Riot hides them in champ select)
          </span>
        )}
        <span className="ml-auto text-[10px] text-white/30">
          {inGame ? "live · Live Client Data" : scout?.at ? "scouted from LCU match history" : ""}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_0.92fr_1fr] gap-2.5">
        <div className="scroll-thin flex min-h-0 flex-col gap-1.5 overflow-y-auto pr-0.5">
          <div className="t-label text-ally/70">YOUR TEAM</div>
          {allyRoster.length === 0
            ? <div className="frost px-3 py-2 text-[12px] text-white/35">Scouting teammates…</div>
            : allyRoster.map((p) => (
                <AllyCard key={p.name + (p.position || "")} p={p} champ={champByRole[p.position]} patch={patch} />
              ))}
        </div>

        <div className="scroll-thin flex min-h-0 flex-col gap-2.5 overflow-y-auto pr-0.5">
          <LaneLadder allyByRole={allyByRole} enemyByRole={enemyLadderByRole}
                      enemyScoutByRole={enemyScoutByRole} patch={patch} />
          <TeamRead allies={allies} />
          {!inGame && (
            <div className="frost frost-accent flex items-start gap-2.5 p-2.5">
              <Eye className="mt-0.5 h-4 w-4 shrink-0 text-accent-bright" />
              <div className="text-[11px] leading-snug text-white/70">
                <div className="t-label text-accent/70">ENEMY INTEL</div>
                <p className="mt-1">Enemies are hidden in champ select. Once the game loads, their live
                  champion + K/D/A/CS appear here from the read-only Live Client Data API. Riot doesn't
                  expose enemy match history, so there's no historical profile for them.</p>
              </div>
            </div>
          )}
        </div>

        <div className="scroll-thin flex min-h-0 flex-col gap-1.5 overflow-y-auto pr-0.5">
          <div className="t-label text-enemy/70">ENEMY TEAM{inGame && <span className="text-white/30"> · live</span>}</div>
          {inGame
            ? [
                ...ROLE_ORDER.map((r) => liveEnemyByRole[r]).filter(Boolean),
                ...liveEnemies.filter((p) => !p.role || !ROLE_ORDER.includes(p.role)),
              ].map((p, i) => (
                <LivePlayerCard key={`${p.name}-${p.champion}-${i}`} p={p}
                                slug={slugOf[p.champion]} side="enemy" patch={patch} />
              ))
            : enemyRoster.map((e, i) => (
                <EnemyCard key={e ? e.champion_id : `e-${i}`} e={e}
                           scout={e ? enemyScoutByRole[e.role] : null} patch={patch} />
              ))}
        </div>
      </div>
    </div>
  );
}
