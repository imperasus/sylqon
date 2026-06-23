import { useMemo } from "react";
import {
  Crosshair, Flame, Radar, Skull, Swords, TrendingUp, Users, UsersRound,
} from "lucide-react";
import { useStaticData } from "../api.js";
import { ROLE_LABELS, ROLE_ORDER, itemUrl, spellUrl, pct } from "../assets.js";
import { ChampPortrait, Chip, EmptyState, Panel } from "./shared.jsx";
import { useElementRem } from "../hooks/useFitCount.js";

/* Per-role CS/min targets — a glanceable "keeping up?" gauge, not a hard rule.
   Mirrors livegame/state._CS_TARGETS (support farms by design → low bar). */
const ROLE_CS_TARGET = { top: 7.5, jungle: 5.5, middle: 8.0, bottom: 8.5, utility: 1.5 };

/* Premade groups are colored independently of team; same color = same party. */
const PREMADE_PALETTE = ["#b6a4ff", "#ffc46b", "#ff8fae", "#5fd0ff", "#8ef0a8"];
const premadeColor = (g) => PREMADE_PALETTE[g % PREMADE_PALETTE.length];
const premadeLetter = (g) => String.fromCharCode(65 + (g % 26));
/* Party size → pill label. Groups can be any size from a duo to a full 5-stack. */
const PREMADE_LABEL = { 2: "DUO", 3: "TRIO", 4: "QUAD", 5: "5-STACK" };
const premadeLabel = (size) => PREMADE_LABEL[size] || "PARTY";

/* Rune tree → accent color for the keystone chip (matches the in-app palette). */
const TREE_COLOR = {
  Precision: "#ffc46b", Domination: "#ff6f8b", Sorcery: "#b6a4ff",
  Resolve: "#43e0a8", Inspiration: "#5fd0ff",
};
const KEYSTONE_ABBR = {
  "Press the Attack": "PtA", "Lethal Tempo": "Tempo", "Fleet Footwork": "Fleet",
  "Conqueror": "Conq", "Electrocute": "Elec", "Dark Harvest": "Harvest",
  "Hail of Blades": "HoB", "Summon Aery": "Aery", "Arcane Comet": "Comet",
  "Phase Rush": "Phase", "Grasp of the Undying": "Grasp", "Aftershock": "Aftsk",
  "Guardian": "Guard", "Glacial Augment": "Glacial", "Unsealed Spellbook": "Book",
  "First Strike": "Strike",
};

/* Playstyle tag → chip tone (mirrors the lobby scout strip). */
const TAG_TONE = {
  aggressive: "enemy", "carry-threat": "amber", "one-trick": "amber",
  "farm-focused": "accent", playmaker: "ally", calculated: "good",
  frontliner: "ally", "vision-control": "accent",
};

const norm = (s) => (s || "").trim().toLowerCase();
const mmss = (sec) => {
  const t = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};

/* The summoner-spell display names map to the file basenames in assets.spellUrl. */
function Build({ p, patch }) {
  const spells = p.spells || [];
  const items = (p.items || []).slice(0, 6);
  const ks = p.runes?.keystone;
  const tree = TREE_COLOR[p.runes?.primary] || "#7aa";
  return (
    <div className="flex items-center gap-1">
      {spells.map((s, i) => (
        <img key={`s${i}`} src={spellUrl(patch, s)} alt={s} title={s}
             className="h-4 w-4 rounded-sm border border-white/15 bg-black/40" draggable={false} />
      ))}
      {ks && (
        <span title={`${ks}${p.runes?.secondary ? ` · ${p.runes.secondary}` : ""}`}
              className="ml-0.5 rounded px-1 text-3xs font-bold leading-[0.9375rem]"
              style={{ color: tree, border: `1px solid ${tree}66`, background: `${tree}1f` }}>
          {KEYSTONE_ABBR[ks] || ks.slice(0, 5)}
        </span>
      )}
      {items.length > 0 && <span className="mx-0.5 h-3.5 w-px bg-white/12" />}
      <div className="flex gap-0.5">
        {items.map((id, i) => (
          <img key={`i${i}`} src={itemUrl(patch, id)} alt="" title={`item ${id}`}
               className="h-4 w-4 rounded-sm border border-white/12 bg-black/30" draggable={false} />
        ))}
        {items.length === 0 && <span className="text-3xs text-white/25">no items yet</span>}
      </div>
    </div>
  );
}

/* detail: 2 = full (all rows) · 1 = drop the scout row · 0 = identity + stats only.
   The column picks the level that lets all players fit without scrolling. */
function PlayerCard({ p, patch, gameTime = 0, detail = 2 }) {
  const acc = p.account || {};
  const solo = acc.solo;
  const cc = p.current_champ || {};
  const form = p.recent_form || {};
  const kda = p.avg_kda || {};
  const tags = (p.playstyle_tags || []).slice(0, 3);
  const pool = (p.champion_pool || []).slice(0, 3);
  const hasGroup = p.premade_group != null;
  const partners = p.premade_partners || [];
  const sideAccent = p.isSelf ? "accent" : p.side === "enemy" ? "enemy" : "ally";

  const liveKda = ((p.kills + p.assists) / Math.max(1, p.deaths)).toFixed(1);
  const csTarget = ROLE_CS_TARGET[p.role] ?? 7;
  const csRate = (p.cs_per_min || 0).toFixed(1);
  // Benchmark coloring only once laning is underway (~3 min). Before that everyone
  // is at 0 CS and a red "behind" read would just be alarming noise. Support CS
  // isn't a meaningful gauge, so it stays neutral too.
  const benchmark = gameTime >= 180 && p.role !== "utility";
  const csTone = !benchmark ? "text-white/40"
    : p.cs_per_min - csTarget >= 0.3 ? "text-good"
    : p.cs_per_min - csTarget <= -0.3 ? "text-bad" : "text-white/40";

  const seasonWR = solo?.win_rate != null
    ? `${pct(solo.win_rate)} · ${solo.games}g`
    : (p.games_analyzed ? `${p.games_analyzed}g history` : "");

  // Recent-form chip: ≥3 streak reads hot / tilt, else a small signed marker.
  const streak = form.streak || 0;
  const formChip = streak >= 3 && (form.win_rate || 0) >= 0.55
    ? { tone: "good", icon: TrendingUp, label: `${streak}W hot` }
    : streak <= -3
      ? { tone: "bad", icon: Flame, label: `${Math.abs(streak)}L tilt` }
      : form.games ? { tone: "muted", label: `${streak > 0 ? "+" : ""}${streak}` } : null;

  return (
    <div className={`frost relative flex flex-col gap-1 py-1.5 pr-2 pl-2.5
                     ${p.isSelf ? "frost-accent" : ""} ${p.is_dead ? "opacity-75" : ""}`}>
      {hasGroup && (
        <span className="absolute inset-y-0 left-0 w-[0.1875rem] rounded-l-[0.625rem]"
              style={{ background: premadeColor(p.premade_group) }} />
      )}

      {/* Row 1 — portrait + level, identity, premade / dead */}
      <div className="flex items-center gap-2">
        <div className="relative shrink-0">
          <div className={p.is_dead ? "grayscale" : ""}>
            <ChampPortrait slug={p.slug} patch={patch} size="h-8 w-8" accent={sideAccent} title={p.champion} />
          </div>
          <span className="absolute -right-1.5 -bottom-1.5 grid h-4 min-w-[1rem] place-items-center
                           rounded-full border border-line bg-bg-2 px-0.5 text-3xs font-bold text-white/85">
            {p.level || "?"}
          </span>
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="flex items-center gap-1">
            <span className="truncate text-sm font-bold text-white/90">{p.name}</span>
            {p.isSelf && <span className="text-3xs font-bold tracking-widest text-accent">YOU</span>}
            {solo?.hot_streak && <Flame className="h-3 w-3 text-bad" title="on a hot streak" />}
            {solo?.fresh_blood && (
              <span className="rounded border border-ally/40 px-1 text-3xs font-bold tracking-wide text-ally"
                    title="new to this rank — possible smurf / fresh account">SMURF?</span>
            )}
          </div>
          <div className="flex items-center gap-1.5 text-3xs font-bold tracking-wide">
            <span className="tracking-widest text-white/45">{ROLE_LABELS[p.role] || "—"}</span>
            {p.rank
              ? <span className="text-amber/85">{p.rank}</span>
              : <span className="text-white/30">Unranked</span>}
            {acc.flex?.label && <span className="rounded border border-ally/30 px-1 text-3xs text-ally/90"
                                      title="Ranked Flex">{acc.flex.label}</span>}
            {seasonWR && <span className="text-white/35">· {seasonWR}</span>}
          </div>
        </div>
        {p.is_dead
          ? <Chip tone="bad"><Skull className="mr-0.5 inline h-2.5 w-2.5" />dead {Math.ceil(p.respawn_timer || 0)}s</Chip>
          : hasGroup && (
            <span className="shrink-0 rounded px-1.5 py-px text-3xs font-bold"
                  title={partners.length ? `premade with ${partners.join(", ")}` : "premade"}
                  style={{ color: "#0c1020", background: premadeColor(p.premade_group) }}>
              {premadeLabel(partners.length + 1)} {premadeLetter(p.premade_group)}
            </span>
          )}
      </div>

      {/* Row 2 — live K/D/A · CS · cs/m Δ · current champ games/WR/mastery */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-t border-white/8 pt-1 font-mono text-2xs">
        <span className="font-bold text-white/80">{p.kills}/{p.deaths}/{p.assists}</span>
        <span className="text-white/35">{p.cs} CS</span>
        <span className={csTone} title={`CS/min (role target ${csTarget})`}>
          {csRate} cs/m
        </span>
        <span className="mx-0.5 h-3 w-px bg-white/12" />
        <span className="text-white/45" title="games · win-rate · mastery on the champ they're on now">
          <span className="text-white/60">{p.champion}</span>
          {cc.games != null && <> · {cc.games}g <span className={cc.win_rate >= 0.5 ? "text-good" : "text-bad"}>{pct(cc.win_rate)}</span></>}
          {cc.mastery_points != null && (
            <> · <span className="text-white/35">M{cc.mastery_level || "?"} {(cc.mastery_points / 1000).toFixed(0)}k</span></>
          )}
        </span>
      </div>

      {/* Row 3 — live build (spells · keystone · items) */}
      {detail >= 1 && <Build p={p} patch={patch} />}

      {/* Row 4 — recent form, playstyle, pool, history averages */}
      {detail >= 2 && (
      <div className="flex flex-wrap items-center gap-1 text-3xs text-white/45">
        {formChip && (
          <Chip tone={formChip.tone}>
            {formChip.icon && <formChip.icon className="mr-0.5 inline h-2.5 w-2.5" />}{formChip.label}
          </Chip>
        )}
        {tags.map((t) => <Chip key={t} tone={TAG_TONE[t] || "muted"}>{t}</Chip>)}
        {pool.length > 0 && (
          <span className="ml-0.5 flex items-center gap-0.5" title="recent champion pool">
            {pool.map((c) => (
              <ChampPortrait key={c.champion_id} slug={c.slug} patch={patch} size="h-4 w-4" round
                             title={`${c.champion || ""} · ${c.games || 0}g ${c.win_rate != null ? pct(c.win_rate) : ""}`} />
            ))}
          </span>
        )}
        {kda.ratio != null && (
          <span className="ml-auto font-mono text-white/40" title="recent averages (KDA · CS/min · vision)">
            {kda.ratio.toFixed(1)} KDA · {p.avg_cs_per_min ?? 0} cs · {Math.round(p.avg_vision_score ?? 0)} vis
          </span>
        )}
      </div>
      )}
    </div>
  );
}

/* Lane-by-lane read: ally vs enemy champion per role, with a light edge lean
   derived from recent form (ally streak) and the enemy's threat signals. */
function LaneLadder({ byRole, patch }) {
  return (
    <Panel title="LANE MATCHUPS" icon={Swords} accent="white" className="gap-0.5">
      {ROLE_ORDER.map((role) => {
        const a = byRole.ally[role];
        const e = byRole.enemy[role];
        const as = a?.recent_form?.streak || 0;
        const eHot = (e?.recent_form?.streak || 0) >= 3 || (e?.playstyle_tags || []).includes("carry-threat");
        const eTilt = (e?.recent_form?.streak || 0) <= -3;
        const edge = as >= 3 || eTilt ? "ally" : eHot ? "enemy" : "even";
        const edgeEl = edge === "ally"
          ? <span className="text-3xs font-bold text-good">◂ edge</span>
          : edge === "enemy"
            ? <span className="text-3xs font-bold text-enemy/80">risk ▸</span>
            : <span className="text-3xs text-white/30">even</span>;
        return (
          <div key={role} className="flex items-center gap-2 rounded px-1 py-0.5 text-2xs even:bg-white/[0.015]">
            <span className="w-6 shrink-0 font-bold tracking-widest text-white/40">{ROLE_LABELS[role]}</span>
            <span className="flex flex-1 items-center gap-1 truncate">
              {a && <ChampPortrait slug={a.slug} patch={patch} size="h-4 w-4" round title={a.champion} />}
              <span className={`truncate ${a?.isSelf ? "text-accent-bright" : "text-ally/90"}`}>{a?.name || "—"}</span>
            </span>
            <span className="w-12 shrink-0 text-center">{edgeEl}</span>
            <span className="flex flex-1 items-center justify-end gap-1 truncate text-enemy/85">
              <span className="truncate">{e?.name || "—"}</span>
              {e && <ChampPortrait slug={e.slug} patch={patch} size="h-4 w-4" round title={e.champion} />}
            </span>
          </div>
        );
      })}
    </Panel>
  );
}

/* Actionable callouts derived from the enemy reads: premade parties first, then
   the hottest carry threat, then a tilted enemy to punish. */
function Callouts({ enemies, groups }) {
  const flags = [];
  // Premade parties on the enemy team (botlane duos are the headline one).
  for (const [gi, members] of Object.entries(groups)) {
    const enemyMembers = members.filter((m) => m.side === "enemy");
    if (enemyMembers.length < 2) continue;
    const roles = enemyMembers.map((m) => m.role);
    const botlane = roles.includes("bottom") && roles.includes("utility");
    flags.push({
      icon: UsersRound, color: premadeColor(+gi),
      text: botlane
        ? "Enemy botlane is a duo — expect coordinated 2v2 and dives."
        : `Enemy ${enemyMembers.map((m) => ROLE_LABELS[m.role] || "?").join("+")} are premade.`,
    });
  }
  for (const e of enemies) {
    const s = e.recent_form?.streak || 0;
    if ((s >= 4 || e.account?.solo?.hot_streak) && (e.playstyle_tags || []).includes("carry-threat")) {
      flags.push({ icon: Flame, color: "#ff6b78",
        text: `${e.name} (${ROLE_LABELS[e.role] || "?"}) is hot on ${e.champion} — deny early.` });
    }
  }
  for (const e of enemies) {
    const s = e.recent_form?.streak || 0;
    if (s <= -3) flags.push({ icon: Crosshair, color: "#ffc46b",
      text: `${e.name} (${ROLE_LABELS[e.role] || "?"}) is on a ${Math.abs(s)}-loss streak — punish.` });
  }
  if (!flags.length) return null;
  return (
    <Panel title="THREATS" icon={Crosshair} accent="enemy" className="gap-1">
      {flags.slice(0, 4).map((f, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-white/75">
          <f.icon className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: f.color }} />
          <span>{f.text}</span>
        </div>
      ))}
    </Panel>
  );
}

/* A team's player cards. Always shows every player; when the column is short it
   drops per-card detail (scout row, then build row) instead of scrolling. */
function PlayerColumn({ label, labelCls, players, patch, gameTime, keyPrefix }) {
  const [boxRef, boxRem] = useElementRem();
  // boxRem includes the ~1.7rem label header; the rest is split across the cards.
  const perCard = players.length ? (boxRem - 1.7) / players.length : 0;
  const detail = perCard >= 7.2 ? 2 : perCard >= 5.6 ? 1 : 0;
  return (
    <div ref={boxRef} className="flex min-h-0 flex-col gap-1.5 overflow-hidden pr-0.5">
      <div className={`t-label flex items-center gap-1 ${labelCls}`}>
        <Users className="h-3.5 w-3.5" /> {label}
      </div>
      {players.map((p) => (
        <PlayerCard key={`${keyPrefix}-${p.name}`} p={p} patch={patch} gameTime={gameTime} detail={detail} />
      ))}
    </div>
  );
}

export default function LiveBoard({ scout, live, patch }) {
  const { champions } = useStaticData();

  const merged = useMemo(() => {
    const slugByName = {};
    for (const c of champions) slugByName[c.name] = c.slug;
    const scoutByName = {};
    for (const p of scout?.players || []) if (p.name) scoutByName[norm(p.name)] = p;
    const gameMin = (live?.game_time || 0) / 60;
    return (live?.roster || []).map((r) => {
      const s = scoutByName[norm(r.name)] || {};
      return {
        ...s, ...r,
        slug: slugByName[r.champion] || s.slug || "",
        cs_per_min: gameMin > 0 ? r.cs / gameMin : 0,
        isSelf: !!live?.my_name && norm(r.name) === norm(live.my_name),
      };
    });
  }, [scout, live, champions]);

  const allies = merged.filter((p) => p.side !== "enemy");
  const enemies = merged.filter((p) => p.side === "enemy");

  const byRole = useMemo(() => {
    const m = { ally: {}, enemy: {} };
    for (const p of allies) if (p.role) m.ally[p.role] = p;
    for (const p of enemies) if (p.role) m.enemy[p.role] = p;
    return m;
  }, [allies, enemies]);

  const groups = useMemo(() => {
    const g = {};
    for (const p of merged) if (p.premade_group != null) (g[p.premade_group] ||= []).push(p);
    return Object.fromEntries(Object.entries(g).filter(([, v]) => v.length >= 2));
  }, [merged]);

  const ordered = (side) => {
    const list = side === "ally" ? allies : enemies;
    const byR = ROLE_ORDER.map((r) => list.find((p) => p.role === r)).filter(Boolean);
    for (const p of list) if (!byR.includes(p)) byR.push(p);
    return byR;
  };

  if (merged.length === 0) {
    return (
      <div className="frost h-full">
        <EmptyState icon={Radar} label="WAITING FOR LIVE GAME"
                    hint="The board fills the moment the game loads — all 10 players with rank, build, mastery and premade groups." />
      </div>
    );
  }

  const scoutedN = merged.filter((p) => (p.games_analyzed || 0) > 0).length;
  const premadeN = scout?.premade_groups ?? Object.keys(groups).length;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="frost flex flex-wrap items-center gap-3 px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-xs font-bold tracking-widest text-accent/80">
          <Radar className="h-4 w-4" /> LIVE GAME
        </span>
        <span className="flex items-center gap-1.5 font-mono text-xs font-bold text-bad">
          <span className="h-2 w-2 rounded-full bg-bad pulse-soft" /> {mmss(live?.game_time)}
        </span>
        {premadeN > 0 && (
          <Chip tone="accent"><UsersRound className="mr-0.5 inline h-3 w-3" />{premadeN} premade{premadeN > 1 ? "s" : ""}</Chip>
        )}
        <span className="ml-auto flex items-center gap-2 text-2xs text-white/35">
          <Chip tone="muted">scouted {scoutedN}/10</Chip>
          read-only · Live Client Data + Riot API
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_0.85fr_1fr] gap-2">
        <PlayerColumn label="YOUR TEAM" labelCls="text-ally/70" players={ordered("ally")}
                      patch={patch} gameTime={live?.game_time} keyPrefix="a" />

        <div className="scroll-thin flex min-h-0 flex-col gap-2 overflow-y-auto pr-0.5">
          <Callouts enemies={enemies} groups={groups} />
          <LaneLadder byRole={byRole} patch={patch} />
          {Object.keys(groups).length > 0 && (
            <Panel title="PREMADES" icon={UsersRound} accent="accent" className="gap-1">
              {Object.entries(groups).map(([gi, members]) => (
                <div key={gi} className="flex items-center gap-2 text-2xs">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: premadeColor(+gi) }} />
                  <span className="font-bold text-white/70">{premadeLetter(+gi)}</span>
                  <span className={members[0]?.side === "enemy" ? "text-enemy/80" : "text-ally/80"}>
                    {members.map((m) => `${ROLE_LABELS[m.role] || "?"} ${m.name}`).join(" + ")}
                  </span>
                </div>
              ))}
              <span className="border-t border-white/8 pt-1 text-3xs text-white/30">
                Inferred from shared recent ranked + normal games.
              </span>
            </Panel>
          )}
        </div>

        <PlayerColumn label="ENEMY TEAM" labelCls="text-enemy/70" players={ordered("enemy")}
                      patch={patch} gameTime={live?.game_time} keyPrefix="e" />
      </div>
    </div>
  );
}
