import { useMemo } from "react";
import {
  Flame, Radar, Skull, Swords, TrendingUp, UsersRound,
} from "lucide-react";
import { useStaticData } from "../api.js";
import {
  ROLE_LABELS, ROLE_ORDER, benchTarget, dyingMoreThanUsual, itemUrl, spellUrl, pct,
  poolEntryLabel, sampleNote, wrTone,
} from "../assets.js";
import {
  CalloutList, ChampPortrait, Chip, EmptyState, LaneEdge, Panel, PlayerDetail,
} from "./shared.jsx";
import { NumCell, RankCell, RoleCell, Skeleton, TeamRow, TeamTable } from "./TeamTable.jsx";

/* Fallback CS/min targets, used only if the rank-band benchmarks (/api/benchmarks)
   haven't loaded. Normally the gauge grades against the player's OWN rank band
   (see benchTarget) so a Gold ADC isn't measured against a Challenger's farm. */
const CS_TARGET_FALLBACK = { top: 6.5, jungle: 5.0, middle: 7.0, bottom: 7.3, utility: 1.2 };

/* Roles whose job includes vision — only these get a vision shortfall flag. */
const VISION_ROLES = new Set(["utility", "jungle"]);
const VISION_LOW_RATIO = 0.75;   // this far under their rank band → worth saying

/* Premade groups are colored independently of team; same color = same party.
   Pastel categorical set — light enough for the dark badge text. */
const PREMADE_PALETTE = ["#c4b5fd", "#fcd34d", "#fda4af", "#7dd3fc", "#86efac"];
const premadeColor = (g) => PREMADE_PALETTE[g % PREMADE_PALETTE.length];
const premadeLetter = (g) => String.fromCharCode(65 + (g % 26));
/* Party size → pill label. Groups can be any size from a duo to a full 5-stack. */
const PREMADE_LABEL = { 2: "DUO", 3: "TRIO", 4: "QUAD", 5: "5-STACK" };
const premadeLabel = (size) => PREMADE_LABEL[size] || "PARTY";

/* Rune tree → accent color for the keystone chip (matches the in-app palette). */
const TREE_COLOR = {
  Precision: "#fbbf24", Domination: "#fb7185", Sorcery: "#a78bfa",
  Resolve: "#34d399", Inspiration: "#38bdf8",
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
  const tree = TREE_COLOR[p.runes?.primary] || "#9a9b9e";
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

/* Hover depth for the player cell: recent pool + history averages. */
function rowTip(p) {
  const bits = [];
  const pool = (p.champion_pool || []).slice(0, 4);
  if (pool.length) bits.push("pool: " + pool.map(poolEntryLabel).join(" · "));
  const kda = p.avg_kda || {};
  if (kda.ratio != null) bits.push(`recent avg ${kda.ratio.toFixed(1)} KDA · ${p.avg_cs_per_min ?? 0} cs/m · ${Math.round(p.avg_vision_score ?? 0)} vis`);
  const cc = p.current_champ || {};
  if (cc.mastery_points != null) bits.push(`mastery M${cc.mastery_level || "?"} ${(cc.mastery_points / 1000).toFixed(0)}k`);
  return bits.join("\n");
}

/* One live player as a table row: identity, rank, recent form, live K/D/A + CS
   pace, flags, and the live build strip. */
function LiveRow({ p, patch, benchmarks, matchup, gameTime = 0 }) {
  const acc = p.account || {};
  const solo = acc.solo;
  const cc = p.current_champ || {};
  const form = p.recent_form || {};
  const tags = (p.playstyle_tags || []).slice(0, 2);
  const hasGroup = p.premade_group != null;
  const partners = p.premade_partners || [];

  // Grade CS against the player's OWN rank band, not a fixed high-elo constant.
  const csTarget = benchTarget(benchmarks, p.role, solo?.tier, "cs_per_min")
    ?? CS_TARGET_FALLBACK[p.role] ?? 7;
  const graded = gameTime >= 180 && p.role !== "utility";
  const csTone = !graded ? "text-white/35"
    : p.cs_per_min - csTarget >= 0.3 ? "text-good"
    : p.cs_per_min - csTarget <= -0.3 ? "text-bad" : "text-white/35";

  // Recent form: hot only with a supporting win rate; "cold" is a factual streak
  // note, escalated to a tilt read only when recent deaths are above the player's
  // own baseline (evidence, not a psychology guess). See recent_form.avg_deaths.
  const streak = form.streak || 0;
  const dyingMore = dyingMoreThanUsual(p);
  const formChip = streak >= 3 && (form.win_rate || 0) >= 0.55
    ? { tone: "good", icon: TrendingUp, label: `${streak}W` }
    : streak <= -3
      ? { tone: "bad", icon: Flame, label: dyingMore ? `${Math.abs(streak)}L tilt?` : `${Math.abs(streak)}L cold` }
      : null;

  // "Fresh blood" alone just means recently promoted/demoted into the tier — a
  // weak smurf signal. Only call it a smurf when it's paired with a hard-carry
  // record over a real sample.
  const smurfSuspect = solo?.fresh_blood && (solo.win_rate ?? 0) >= 0.65
    && (solo.games ?? 0) >= 20 && (p.avg_kda?.ratio ?? 0) >= 3.5;

  // Vision is the job in these roles, so a persistent shortfall against their own
  // rank band is a real, actionable read rather than trivia.
  const visionTarget = benchTarget(benchmarks, p.role, solo?.tier, "vision_score");
  const lowVision = VISION_ROLES.has(p.role) && visionTarget != null
    && p.avg_vision_score != null && p.avg_vision_score < visionTarget * VISION_LOW_RATIO;

  return (
    <TeamRow premade={hasGroup ? premadeColor(p.premade_group) : null} self={p.isSelf}
             dim={p.is_dead} title={rowTip(p)}
             detail={<PlayerDetail p={p} matchup={matchup} />}>
      <RoleCell role={ROLE_LABELS[p.role]} />

      <div className="flex min-w-0 items-center gap-1.5">
        <div className="relative shrink-0">
          <div className={p.is_dead ? "grayscale" : ""}>
            <ChampPortrait slug={p.slug} patch={patch} size="h-7 w-7"
                           accent={p.isSelf ? "accent" : p.side === "enemy" ? "enemy" : "ally"} title={p.champion} />
          </div>
          <span className="absolute -right-1 -bottom-1 grid h-3.5 min-w-[0.875rem] place-items-center
                           rounded-full border border-line bg-bg-2 px-0.5 text-3xs font-bold text-white/85">
            {p.level || "?"}
          </span>
        </div>
        <div className="min-w-0 leading-tight">
          <div className="flex items-center gap-1">
            <span className="truncate text-xs font-bold text-white/90">{p.name}</span>
            {p.isSelf && <span className="text-3xs font-bold tracking-widest text-accent">YOU</span>}
            {solo?.fresh_blood && (smurfSuspect
              ? <span className="rounded border border-amber/50 px-1 text-3xs font-bold text-amber"
                      title={`new to this rank AND winning hard (${pct(solo.win_rate)} over ${solo.games}g, ${p.avg_kda?.ratio?.toFixed(1)} KDA) — possible smurf`}>SMURF?</span>
              : <span className="rounded border border-ally/40 px-1 text-3xs font-bold text-ally"
                      title="promoted/demoted into this tier recently (fresh blood) — not necessarily a smurf">NEW</span>)}
            {p.autofill && (
              <span className="shrink-0 rounded border border-amber/50 px-1 text-3xs font-bold text-amber"
                    title={`off-role: mains ${ROLE_LABELS[p.autofill.main_role] || p.autofill.main_role}, `
                           + `only ${p.autofill.games} of their recent games here`}>
                AUTOFILL
              </span>
            )}
            {hasGroup && (
              <span className="shrink-0 rounded px-1 text-3xs font-bold"
                    title={partners.length ? `premade with ${partners.join(", ")}` : "premade"}
                    style={{ color: "#0e0e0f", background: premadeColor(p.premade_group) }}>
                {premadeLabel(partners.length + 1)} {premadeLetter(p.premade_group)}
              </span>
            )}
          </div>
          <div className="truncate text-3xs text-white/45">
            {p.champion}
            {cc.games != null && <> · {cc.games}g <span className={wrTone(cc.win_rate, cc.games)}>{pct(cc.win_rate)}</span></>}
          </div>
        </div>
      </div>

      <RankCell rank={p.rank}
                sub={solo?.win_rate != null ? `${pct(solo.win_rate)} · ${solo.games}g`
                  : p.games_analyzed ? `${p.games_analyzed}g history` : null} />

      <NumCell value={form.games ? pct(form.win_rate) : null}
               tone={wrTone(form.win_rate, form.games)}
               sub={form.games ? `${form.games}g` : null}
               pending={p.deep_pending}
               title={`recent form win rate over ${form.games || 0} games${sampleNote(form.games)}`} />

      <NumCell value={`${p.kills ?? 0}/${p.deaths ?? 0}/${p.assists ?? 0}`} tone="text-white/80"
               sub={`${(p.cs_per_min || 0).toFixed(1)} cs/m`} subTone={csTone}
               title={`live score · CS/min (rank-band target ${csTarget.toFixed(1)})`} />

      <div className="flex min-w-0 flex-wrap items-center gap-0.5">
        {p.deep_pending && !p.is_dead && <Skeleton className="w-12" />}
        {p.is_dead && <Chip tone="bad"><Skull className="mr-0.5 inline h-2.5 w-2.5" />{Math.ceil(p.respawn_timer || 0)}s</Chip>}
        {solo?.hot_streak && <Flame className="h-3 w-3 shrink-0 text-bad" title="on a hot streak" />}
        {formChip && !p.is_dead && (
          <Chip tone={formChip.tone}>
            {formChip.icon && <formChip.icon className="mr-0.5 inline h-2.5 w-2.5" />}{formChip.label}
          </Chip>
        )}
        {lowVision && (
          <Chip tone="muted" title={`averages ${Math.round(p.avg_vision_score)} vision vs `
                                    + `~${visionTarget} for their rank band`}>low vis</Chip>
        )}
        {tags.slice(0, 1).map((t) => <Chip key={t} tone={TAG_TONE[t] || "muted"}>{t}</Chip>)}
      </div>

      <Build p={p} patch={patch} />
    </TeamRow>
  );
}

/* Lane-by-lane read: ally vs enemy champion per role. The edge is the backend
   lane-matchup blend (champion counter + form + rank + experience), so a lane
   with thin evidence honestly reads "low data" instead of guessing. */
function LaneLadder({ byRole, matchups, patch }) {
  const edges = matchups?.by_role || {};
  return (
    <Panel title="LANE MATCHUPS" icon={Swords} accent="white" className="gap-0.5">
      {ROLE_ORDER.map((role) => {
        const a = byRole.ally[role];
        const e = byRole.enemy[role];
        const m = edges[role];
        return (
          <div key={role} title={m?.reasons?.[0] || ""}
               className="flex items-center gap-2 rounded px-1 py-0.5 text-2xs even:bg-white/[0.015]">
            <span className="w-6 shrink-0 font-bold tracking-widest text-white/40">{ROLE_LABELS[role]}</span>
            <span className="flex flex-1 items-center gap-1 truncate">
              {a && <ChampPortrait slug={a.slug} patch={patch} size="h-4 w-4" round title={a.champion} />}
              <span className={`truncate ${a?.isSelf ? "text-accent-bright" : "text-ally/90"}`}>{a?.name || "—"}</span>
            </span>
            <span className="w-14 shrink-0 text-center"><LaneEdge m={m} /></span>
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

export default function LiveBoard({ scout, live, matchups, callouts, patch }) {
  const { champions, benchmarks } = useStaticData();

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

  // Per-lane matchup read, shared by the ladder and each row's expanded detail.
  const edges = matchups?.by_role || {};

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
      <div className="surface h-full">
        <EmptyState icon={Radar} label="WAITING FOR LIVE GAME"
                    hint="The board fills the moment the game loads — all 10 players with rank, build, mastery and premade groups." />
      </div>
    );
  }

  const scoutedN = merged.filter((p) => (p.games_analyzed || 0) > 0).length;
  const premadeN = scout?.premade_groups ?? Object.keys(groups).length;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="surface flex flex-wrap items-center gap-3 px-3 py-1.5">
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

      <div className="grid min-h-0 flex-1 grid-cols-[1.6fr_1fr] gap-2">
        <div className="flex min-h-0 flex-col gap-2">
          <TeamTable title="YOUR TEAM" side="ally" lastCol="Build" className="flex-1">
            {ordered("ally").map((p) => (
              <LiveRow key={`a-${p.name}`} p={p} patch={patch} benchmarks={benchmarks}
                       matchup={edges[p.role]} gameTime={live?.game_time} />
            ))}
          </TeamTable>
          <TeamTable title="ENEMY TEAM" side="enemy" lastCol="Build" className="flex-1">
            {ordered("enemy").map((p) => (
              <LiveRow key={`e-${p.name}`} p={p} patch={patch} benchmarks={benchmarks}
                       matchup={edges[p.role]} gameTime={live?.game_time} />
            ))}
          </TeamTable>
        </div>

        <div className="scroll-thin flex min-h-0 flex-col gap-2 overflow-y-auto pr-0.5">
          <CalloutList callouts={callouts} />
          <LaneLadder byRole={byRole} matchups={matchups} patch={patch} />
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
      </div>
    </div>
  );
}
