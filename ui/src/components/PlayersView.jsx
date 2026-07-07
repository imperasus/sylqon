import { useMemo } from "react";
import {
  Crosshair, Eye, Flame, Lock, Radar, Scale, Swords, TrendingUp, Users,
} from "lucide-react";
import { useStaticData } from "../api.js";
import { DAMAGE_COLORS, ROLE_LABELS, ROLE_ORDER, pct } from "../assets.js";
import { ChampPortrait, Chip, EmptyState, Panel, ThreatBadge } from "./shared.jsx";
import { NumCell, RankCell, RoleCell, TeamRow, TeamTable } from "./TeamTable.jsx";

/* Playstyle tag → chip tone (mirrors the draft-board scout strip). */
const TAG_TONE = {
  aggressive: "enemy", "carry-threat": "amber", "one-trick": "amber",
  "farm-focused": "accent", playmaker: "ally", calculated: "good",
  frontliner: "ally", "vision-control": "accent",
};

/* A single glanceable flag derived from recent form / comfort. */
function playerFlag(p) {
  const f = p.recent_form || {};
  const s = f.streak || 0;
  if (s <= -3) return { label: "tilt risk", tone: "amber", icon: Flame };
  if (s >= 3 && (f.win_rate || 0) >= 0.58) return { label: "hot", tone: "good", icon: TrendingUp };
  if (p.comfort && (p.comfort.share || 0) >= 0.55) return { label: "one-trick", tone: "amber", icon: Crosshair };
  return null;
}

/* Hover depth for a scouted player: comfort + averages. */
function scoutTip(p) {
  const bits = [];
  if (p.comfort?.champion) bits.push(`mains ${p.comfort.champion} (${pct(p.comfort.share || 0)} of games${p.comfort.win_rate != null ? `, ${pct(p.comfort.win_rate)} WR` : ""})`);
  const kda = p.avg_kda || {};
  if (kda.ratio != null) bits.push(`avg ${kda.ratio.toFixed(1)} KDA · ${p.avg_cs_per_min ?? 0} cs/m`);
  if (p.aggression != null) bits.push(`aggression ${(p.aggression * 100).toFixed(0)}%`);
  return bits.join("\n");
}

/* Scouted (ally or revealed enemy) player as a table row. */
function ScoutRow({ p, champ, patch }) {
  if (p.hidden) {
    return (
      <TeamRow dim>
        <RoleCell role={ROLE_LABELS[p.position || p.main_role]} />
        <div className="flex min-w-0 items-center gap-1.5">
          <Lock className="h-3.5 w-3.5 shrink-0 text-white/35" />
          <span className="truncate text-xs text-white/45">{p.name}</span>
        </div>
        <span className="text-2xs text-white/25">hidden</span>
        <NumCell value={null} /><NumCell value={null} />
        <span className="text-2xs text-white/25">—</span>
        <span className="text-2xs text-white/25">history hidden / anonymized</span>
      </TeamRow>
    );
  }
  const f = p.recent_form || {};
  const wr = f.games ? f.win_rate : null;
  const streak = f.streak || 0;
  const flag = playerFlag(p);
  const tags = (p.playstyle_tags || []).slice(0, 2);
  const kda = p.avg_kda || {};
  const pool = (p.champion_pool || []).slice(0, 4);

  return (
    <TeamRow self={p.is_self} title={scoutTip(p)}>
      <RoleCell role={ROLE_LABELS[p.position || p.main_role]} />

      <div className="flex min-w-0 items-center gap-1.5">
        <ChampPortrait slug={champ?.slug || p.comfort?.slug} patch={patch} size="h-7 w-7"
                       accent={p.is_self ? "accent" : "ally"} title={champ?.name || p.comfort?.champion} />
        <div className="min-w-0 leading-tight">
          <div className="flex items-center gap-1">
            <span className="truncate text-xs font-bold text-white/90">{p.name}</span>
            {p.is_self && <span className="text-3xs font-bold tracking-widest text-accent">YOU</span>}
          </div>
          <div className="truncate text-3xs text-white/40">{p.games_analyzed}g scouted</div>
        </div>
      </div>

      <RankCell rank={p.rank} />

      <NumCell value={wr != null ? pct(wr) : null}
               tone={wr != null ? (wr >= 0.5 ? "text-good" : "text-bad") : "text-white/35"}
               sub={streak && Math.abs(streak) >= 2 ? `${streak > 0 ? "+" : ""}${streak}` : null}
               title="recent form win rate · streak" />

      <NumCell value={kda.ratio != null ? kda.ratio.toFixed(1) : null}
               sub={p.avg_cs_per_min != null ? `${p.avg_cs_per_min} cs/m` : null}
               title="recent averages" />

      <div className="flex min-w-0 flex-wrap items-center gap-0.5">
        {flag && (
          <Chip tone={flag.tone}>
            <flag.icon className="mr-0.5 inline h-2.5 w-2.5" />{flag.label}
          </Chip>
        )}
        {tags.slice(0, flag ? 1 : 2).map((t) => <Chip key={t} tone={TAG_TONE[t] || "muted"}>{t}</Chip>)}
      </div>

      <div className="flex min-w-0 items-center gap-1">
        {pool.map((c) => (
          <ChampPortrait key={c.champion_id} slug={c.slug} patch={patch} size="h-5 w-5" round
                         title={`${c.champion} · ${c.games}g ${pct(c.win_rate)}`} />
        ))}
        {p.comfort?.champion && (
          <span className="ml-1 flex min-w-0 items-center gap-1 font-mono text-2xs text-white/45"
                title={`mains ${p.comfort.champion}`}>
            <span className="truncate">{p.comfort.champion}</span>
            {p.comfort.win_rate != null && <span className="text-white/55">{pct(p.comfort.win_rate)}</span>}
          </span>
        )}
        {pool.length === 0 && !p.comfort?.champion && <span className="text-2xs text-white/25">—</span>}
      </div>
    </TeamRow>
  );
}

/* Pre-game enemy row: only the champion threat profile is known from the draft;
   the player fingerprint resolves in-game (Riot hides enemy identities). */
function EnemyDraftRow({ e, patch }) {
  if (!e) {
    return (
      <TeamRow dim>
        <RoleCell role={null} />
        <div className="flex min-w-0 items-center gap-1.5">
          <div className="h-7 w-7 shrink-0 rounded border border-dashed border-white/15" />
          <span className="text-2xs tracking-widest text-white/30">AWAITING</span>
        </div>
        <span /><NumCell value={null} /><NumCell value={null} /><span />
        <span />
      </TeamRow>
    );
  }
  return (
    <TeamRow>
      <RoleCell role={ROLE_LABELS[e.role]} />
      <div className="flex min-w-0 items-center gap-1.5">
        <ChampPortrait slug={e.slug} patch={patch} size="h-7 w-7" accent="enemy" title={e.name} />
        <div className="min-w-0 leading-tight">
          <div className="truncate text-xs font-bold text-white/90">{e.name}</div>
          {e.damage_type && e.damage_type !== "—" && (
            <span className={`rounded border px-0.5 text-3xs font-bold ${DAMAGE_COLORS[e.damage_type] || ""}`}>{e.damage_type}</span>
          )}
        </div>
      </div>
      <span className="flex items-center gap-1 text-3xs font-bold tracking-wide text-white/30">
        <Lock className="h-3 w-3" /> IN-GAME
      </span>
      <NumCell value={null} /><NumCell value={null} />
      <span />
      <div className="flex min-w-0 flex-wrap gap-0.5">
        {(e.threats || []).slice(0, 3).map((t) => <ThreatBadge key={t} threat={t} />)}
      </div>
    </TeamRow>
  );
}

/* In-game enemy row from the read-only Live Client Data: live champion, level,
   K/D/A and CS — no historical profile (Riot doesn't expose enemy puuids). */
function EnemyLiveRow({ p, slug, patch }) {
  const kda = (((p.kills ?? 0) + (p.assists ?? 0)) / Math.max(1, p.deaths ?? 0)).toFixed(1);
  const kdaTone = parseFloat(kda) >= 3 ? "text-good" : parseFloat(kda) < 1.5 ? "text-enemy/80" : "text-white/75";
  return (
    <TeamRow dim={p.is_dead}>
      <RoleCell role={ROLE_LABELS[p.role]} />
      <div className="flex min-w-0 items-center gap-1.5">
        <div className={p.is_dead ? "grayscale opacity-60" : ""}>
          <ChampPortrait slug={slug} patch={patch} size="h-7 w-7" accent="enemy" title={p.champion} />
        </div>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-xs font-bold text-white/85">{p.name || p.champion}</div>
          <div className="truncate text-3xs text-white/40">{p.champion}</div>
        </div>
      </div>
      <RankCell rank={p.rank} />
      <NumCell value={null} />
      <NumCell value={`${p.kills ?? 0}/${p.deaths ?? 0}/${p.assists ?? 0}`} tone="text-white/80"
               sub={`${kda} kda`} subTone={kdaTone} />
      <div>{p.is_dead && <Chip tone="bad">DEAD</Chip>}</div>
      <span className="font-mono text-2xs text-white/50">Lv {p.level} · {p.cs} CS</span>
    </TeamRow>
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
          ? <span className="text-3xs font-bold text-good">◂ edge</span>
          : edge === "enemy"
            ? <span className="text-3xs font-bold text-enemy/80">risk ▸</span>
            : <span className="text-3xs text-white/35">even</span>;
        return (
          <div key={role} className="flex items-center gap-2 rounded px-1.5 py-1 text-xs even:bg-white/[0.015]">
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
      <div className="mb-0.5 flex items-center justify-between text-2xs">
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
            <div key={i} className="flex items-start gap-1.5 text-xs text-white/70">
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

  // Locked champion per ally role, so each row shows the champ they're on.
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
      <div className="surface h-full">
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
      <div className="surface flex items-center gap-3 px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-xs font-bold tracking-widest text-accent/80">
          <Users className="h-4 w-4" /> LOBBY INTEL
        </span>
        <Chip tone="ally">{scoutedAllies}/5 allies</Chip>
        <Chip tone={inGame || scoutedEnemies ? "enemy" : "muted"}>
          {inGame ? `${liveEnemies.length}/5 enemies` : `${scoutedEnemies}/5 enemies`}
        </Chip>
        {!inGame && scoutedEnemies === 0 && (
          <span className="flex items-center gap-1 text-xs text-white/40">
            <Lock className="h-3.5 w-3.5" /> enemies appear in-game (Riot hides them in champ select)
          </span>
        )}
        <span className="ml-auto text-2xs text-white/30">
          {inGame ? "live · Live Client Data" : scout?.at ? "scouted from LCU match history" : ""}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1.6fr_1fr] gap-2.5">
        <div className="flex min-h-0 flex-col gap-2.5">
          <TeamTable title="YOUR TEAM" side="ally" lastCol="Pool" className="flex-1">
            {allyRoster.length === 0
              ? <div className="px-3 py-2 text-sm text-white/35">Scouting teammates…</div>
              : allyRoster.map((p) => (
                  <ScoutRow key={p.name + (p.position || "")} p={p} champ={champByRole[p.position]} patch={patch} />
                ))}
          </TeamTable>

          <TeamTable title={inGame ? "ENEMY TEAM · LIVE" : "ENEMY TEAM"} side="enemy"
                     lastCol={inGame ? "Live" : "Threats"} className="flex-1">
            {inGame
              ? [
                  ...ROLE_ORDER.map((r) => liveEnemyByRole[r]).filter(Boolean),
                  ...liveEnemies.filter((p) => !p.role || !ROLE_ORDER.includes(p.role)),
                ].map((p, i) => (
                  <EnemyLiveRow key={`${p.name}-${p.champion}-${i}`} p={p} slug={slugOf[p.champion]} patch={patch} />
                ))
              : enemyRoster.map((e, i) =>
                  e && enemyScoutByRole[e.role] && !enemyScoutByRole[e.role].hidden && enemyScoutByRole[e.role].games_analyzed > 0
                    ? <ScoutRow key={e.champion_id} p={{ ...enemyScoutByRole[e.role], is_self: false }}
                                champ={e} patch={patch} />
                    : <EnemyDraftRow key={e ? e.champion_id : `e-${i}`} e={e} patch={patch} />)}
          </TeamTable>
        </div>

        <div className="scroll-thin flex min-h-0 flex-col gap-2.5 overflow-y-auto pr-0.5">
          <LaneLadder allyByRole={allyByRole} enemyByRole={enemyLadderByRole}
                      enemyScoutByRole={enemyScoutByRole} patch={patch} />
          <TeamRead allies={allies} />
          {!inGame && (
            <div className="surface surface-accent flex items-start gap-2.5 p-2.5">
              <Eye className="mt-0.5 h-4 w-4 shrink-0 text-accent-bright" />
              <div className="text-xs leading-snug text-white/70">
                <div className="t-label text-accent/70">ENEMY INTEL</div>
                <p className="mt-1">Enemies are hidden in champ select. Once the game loads, their live
                  champion + K/D/A/CS appear here from the read-only Live Client Data API. Riot doesn't
                  expose enemy match history, so there's no historical profile for them.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
