import { useMemo } from "react";
import { Ban, Crown, Radar, Shuffle, Sparkles, Swords, Target } from "lucide-react";
import { useStaticData } from "../api.js";
import { DAMAGE_COLORS, ROLE_LABELS, squareUrl } from "../assets.js";
import {
  Bar, ChampPortrait, ChampionRow, Chip, Panel, Score100, SpellPips, ThreatBadge,
} from "./shared.jsx";

/* Segmented progress: one cell per draft slot, lit as picks lock in. */
function DraftProgress({ allyCount, enemyCount, phase }) {
  const total = 10;
  const locked = Math.min(total, allyCount + enemyCount);
  const phaseLabel = {
    counter: "Your counter window",
    blind: "Blind pick — lock soon",
    locked: "Draft complete",
    waiting: "Draft in progress",
  }[phase] || "Draft in progress";
  return (
    <div className="frost flex items-center gap-3 px-3 py-1.5">
      <span className="t-label shrink-0">Draft</span>
      <div className="flex flex-1 gap-1">
        {Array.from({ length: total }).map((_, i) => {
          const on = i < locked;
          const active = i === locked;
          return (
            <span key={i}
              className={`h-1.5 flex-1 rounded-full transition-colors
                ${on ? "bg-accent" : active ? "bg-accent/40 pulse-soft" : "bg-white/10"}`} />
          );
        })}
      </div>
      <span className="shrink-0 text-[11px] font-bold tracking-wide text-accent/80">{phaseLabel}</span>
    </div>
  );
}

/* One tight player row in a team column. */
function PlayerRow({ pick, patch, side, isMe }) {
  if (!pick) {
    return (
      <div className="frost flex min-h-0 flex-1 items-center gap-2 px-2.5 opacity-35">
        <div className="h-9 w-9 rounded border border-dashed border-white/15" />
        <span className="text-[11px] tracking-widest text-white/30">AWAITING</span>
      </div>
    );
  }
  const accent = isMe ? "accent" : side;
  return (
    <div className={`frost ${isMe ? "frost-accent" : ""} flex min-h-0 flex-1 items-center gap-2.5 px-2.5`}>
      <ChampPortrait slug={pick.slug} patch={patch} size="h-9 w-9" accent={accent} title={pick.name} />
      <div className="min-w-0 flex-1 leading-tight">
        <div className="flex items-center gap-1">
          <span className="truncate text-[13px] font-bold text-white/90">{pick.name || "…"}</span>
          {isMe && <span className="text-[9px] font-bold tracking-widest text-accent">YOU</span>}
        </div>
        <div className="flex items-center gap-1 text-[10px] font-bold tracking-widest text-white/40">
          <span>{ROLE_LABELS[pick.role] || "—"}</span>
          {pick.damage_type && pick.damage_type !== "—" && (
            <span className={`rounded border px-0.5 ${DAMAGE_COLORS[pick.damage_type] || ""}`}>{pick.damage_type}</span>
          )}
        </div>
      </div>
      {side === "enemy" && pick.threats?.length > 0 && (
        <div className="flex max-w-[70px] flex-wrap justify-end gap-0.5">
          {pick.threats.slice(0, 2).map((t) => <ThreatBadge key={t} threat={t} />)}
        </div>
      )}
      <SpellPips spells={pick.spells} patch={patch} size="h-4 w-4" />
    </div>
  );
}

function TeamColumn({ title, icon, side, picks, patch, comp }) {
  const slots = [...picks, ...Array(Math.max(0, 5 - picks.length)).fill(null)].slice(0, 5);
  return (
    <Panel title={title} icon={icon} accent={side} edge={side} className="gap-1.5">
      {comp && comp.archetype !== "unknown" && comp.archetype !== "balanced" && (
        <div title={[comp.counter_plan, (comp.signals || []).join(", ")].filter(Boolean).join("\n\n")}
             className="flex items-center gap-1.5">
          <Chip tone={side}>{comp.label}</Chip>
          <div className="flex-1"><Bar value={comp.confidence} tone={side} /></div>
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col gap-1.5">
        {slots.map((p, i) => (
          <PlayerRow key={p ? `${side}-${p.champion_id}` : `${side}-e-${i}`}
                     pick={p} patch={patch} side={side} isMe={p?.isMe} />
        ))}
      </div>
    </Panel>
  );
}

function TimingBanner({ timing }) {
  if (!timing || timing.phase === "waiting") return null;
  const skin = {
    counter: "border-good/40 bg-good/10 text-good",
    blind: "border-bad/40 bg-bad/10 text-bad",
    locked: "border-accent/35 bg-accent/8 text-accent/80",
  }[timing.phase] || "border-white/10 text-white/55";
  return (
    <div className={`flex items-center gap-2 rounded-md border px-2.5 py-1 ${skin}`}>
      <Target className="h-4 w-4 shrink-0" />
      <div className="min-w-0 leading-tight">
        <div className="text-[12px] font-bold tracking-wide">{timing.headline}</div>
        <div className="truncate text-[11px] opacity-80">{timing.detail}</div>
      </div>
    </div>
  );
}

/* A compact component readout tooltip (counter/synergy/meta/comfort). */
function compBreakdown(c) {
  if (!c) return "";
  return `Counter ${Math.round(c.counter)} · Synergy ${Math.round(c.synergy)} · `
    + `Meta ${Math.round(c.meta)} · Win ${Math.round(c.win_rate)} · Comfort ${Math.round(c.comfort)}`;
}

/* One side of the dual reco (optimal | pool). */
function PickFace({ label, tone, pick, slugOf, patch, badge, badgeTone, foot }) {
  return (
    <div className="min-w-0 flex-1">
      <div className="t-label mb-1" style={{ color: `var(--color-${tone})` }}>{label}</div>
      <div className="flex items-center gap-2.5">
        <ChampPortrait slug={pick.slug || slugOf[pick.name]} patch={patch} size="h-14 w-14"
                       accent={tone === "accent" ? "accent" : tone} title={pick.name} />
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-display text-[18px] font-extrabold tracking-wide text-white/95">{pick.name}</span>
            {badge && <Chip tone={badgeTone}>{badge}</Chip>}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5" title={compBreakdown(pick.components)}>
            <Score100 value={pick.total} />
            <span className="text-[10px] tracking-widest text-white/35">OVERALL</span>
          </div>
          {foot}
        </div>
      </div>
    </div>
  );
}

function RecoCard({ reco, role, slugOf, patch }) {
  const optimal = reco?.optimal;
  // Legacy/fallback path: no universe scoring → simple single headline.
  if (!optimal && reco?.pick) {
    return (
      <div className="frost frost-accent edge-accent flex items-center gap-3 p-3">
        <ChampPortrait slug={slugOf[reco.pick]} patch={patch} size="h-16 w-16" accent="accent" title={reco.pick} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-accent" />
            <span className="t-label text-accent/70">AI Pick</span>
            <Chip tone="muted">{reco.source}</Chip>
            {role && <Chip tone="ally">{ROLE_LABELS[role] || role}</Chip>}
          </div>
          <div className="font-display text-[22px] font-extrabold tracking-wide text-accent-bright">{reco.pick}</div>
          <p className="t-body text-white/75">{reco.reasoning || "Best fit for this draft."}</p>
        </div>
      </div>
    );
  }
  if (!optimal) {
    return (
      <div className="frost flex flex-col items-center justify-center gap-2 py-5">
        <div className="relative grid h-12 w-12 place-items-center">
          <div className="sweep absolute inset-0 rounded-full" />
          <Radar className="h-6 w-6 text-accent/70" />
        </div>
        <span className="font-display text-[12px] tracking-[0.25em] text-accent/70">ANALYSING DRAFT…</span>
      </div>
    );
  }

  const poolPick = reco.pool_pick;
  // Collapse when the optimal pick already IS the player's best in-pool option.
  const collapsed = optimal.in_pool || !poolPick || poolPick.name === optimal.name;
  const delta = poolPick ? Math.round((optimal.total - poolPick.total) * 10) / 10 : 0;

  return (
    <div className="frost frost-accent edge-accent flex flex-col gap-2 p-3">
      <div className="flex items-center gap-1.5">
        <Sparkles className="h-4 w-4 text-accent" />
        <span className="t-label text-accent/70">AI Pick</span>
        <Chip tone="muted">{reco.source}</Chip>
        {role && <Chip tone="ally">{ROLE_LABELS[role] || role}</Chip>}
      </div>

      {collapsed ? (
        <PickFace label="Optimal · in your pool" tone="accent" pick={optimal} slugOf={slugOf}
                  patch={patch} badge="POOL ✓" badgeTone="good" />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <PickFace label="Optimal" tone="amber" pick={optimal} slugOf={slugOf} patch={patch}
                    badge="OFF-POOL" badgeTone="amber"
                    foot={<div className="mt-0.5 text-[10px] tracking-wide text-amber/70">+{delta} over your pool</div>} />
          <div className="border-l border-white/8 pl-3">
            <PickFace label="From your pool" tone="ally" pick={poolPick} slugOf={slugOf} patch={patch}
                      badge="SAFE" badgeTone="ally"
                      foot={<div className="mt-0.5 text-[10px] tracking-wide text-white/35">your best comfort pick</div>} />
          </div>
        </div>
      )}

      <p className="t-body text-white/75">
        {optimal.reasoning || "Best synergy/counter fit for this draft."}
      </p>
      {reco.alternatives?.length > 0 && (
        <div className="text-[10px] tracking-wide text-white/35">alt: {reco.alternatives.join(" · ")}</div>
      )}
    </div>
  );
}

function RoleTop({ recs, patch }) {
  const rows = (recs || []).slice(0, 6);
  if (rows.length === 0) return null;
  return (
    <Panel title="BEST FOR ROLE" icon={Crown} className="gap-0.5">
      {rows.map((r, i) => {
        const c = r.champion || {};
        return (
          <ChampionRow
            key={c.id ?? c.name} rank={i + 1} slug={c.slug} patch={patch} name={c.name}
            inPool={r.in_pool} title={r.reasoning || ""}
            right={<Score100 value={r.score?.total} />}
          />
        );
      })}
    </Panel>
  );
}

function PoolScored({ scored, pick, slugOf, patch }) {
  const rows = (scored || []).filter((s) => s.name !== pick).slice(0, 4);
  if (rows.length === 0) return null;
  return (
    <Panel title="YOUR POOL" icon={Sparkles} accent="white" className="gap-1">
      {rows.map((s) => (
        <div key={s.name} title={(s.notes || []).join("  •  ")}
             className="flex items-center gap-2 rounded border border-white/8 bg-white/[0.015] px-1.5 py-0.5">
          <ChampPortrait slug={slugOf[s.name]} patch={patch} size="h-7 w-7" title={s.name} />
          <span className="truncate text-[13px] text-white/80">{s.name}</span>
          <span className="ml-auto font-mono text-[12px] font-bold tabular-nums text-white/45">
            {s.score > 0 ? "+" : ""}{s.score}
          </span>
        </div>
      ))}
    </Panel>
  );
}

export default function DraftCockpit({ state }) {
  const { champions } = useStaticData();
  const lobby = state?.lobby;
  const reco = state?.recommendation;
  const intel = state?.draft_intel;
  const patch = state?.cache?.patch || "16.12.1";

  const slugOf = useMemo(() => {
    const m = {};
    for (const c of champions) m[c.name] = c.slug;
    return m;
  }, [champions]);

  if (!lobby) {
    return (
      <div className="frost flex h-full flex-col items-center justify-center gap-2">
        <Radar className="h-8 w-8 text-ally/70" />
        <span className="font-display text-[13px] tracking-[0.3em] text-ally/70">AWAITING CHAMPION SELECT</span>
      </div>
    );
  }

  const me = {
    name: lobby.my_champion || "Choosing…", slug: lobby.my_slug, role: lobby.my_role,
    champion_id: lobby.my_champion_id ?? -1, damage_type: "—", spells: [], isMe: true,
  };
  const allyPicks = [me, ...(lobby.allies || [])];
  const enemyPicks = lobby.enemies || [];
  const threat = lobby.threat_summary || {};
  const allyComp = intel?.ally_comp;
  const enemyComp = intel?.enemy_comp;

  return (
    <div className="grid h-full min-h-0 grid-rows-[auto_1fr_auto] gap-2">
      <DraftProgress allyCount={(lobby.allies || []).length + (lobby.my_champion ? 1 : 0)}
                     enemyCount={enemyPicks.length} phase={intel?.counter_pick?.phase} />

      <div className="grid min-h-0 grid-cols-[1fr_1.15fr_1fr] gap-2">
        <TeamColumn title="YOUR TEAM" icon={Sparkles} side="ally" picks={allyPicks}
                    patch={patch} comp={allyComp} />

        <div className="scroll-thin flex min-h-0 flex-col gap-2 overflow-y-auto pr-0.5">
          <TimingBanner timing={intel?.counter_pick} />
          <RecoCard reco={reco} role={lobby.my_role} slugOf={slugOf} patch={patch} />
          <RoleTop recs={reco?.role_top} patch={patch} />
          <PoolScored scored={reco?.scored} pick={reco?.pick} slugOf={slugOf} patch={patch} />
        </div>

        <TeamColumn title="ENEMY TEAM" icon={Swords} side="enemy" picks={enemyPicks}
                    patch={patch} comp={enemyComp} />
      </div>

      {/* bottom intel strip */}
      <div className="frost grid grid-cols-[1.3fr_1fr_0.9fr] items-center gap-3 px-3 py-1.5">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="flex items-center gap-1 text-[11px] font-bold tracking-widest text-enemy/80">
            <Ban className="h-4 w-4" /> BAN
          </span>
          {(intel?.ban_suggestions || []).slice(0, 3).length === 0
            ? <span className="text-[12px] text-white/30">sync op.gg for ban data</span>
            : intel.ban_suggestions.slice(0, 3).map((b) => (
                <span key={b.name} title={b.reason}
                      className="flex items-center gap-1 rounded border border-white/10 bg-white/[0.02] px-1 py-0.5">
                  <ChampPortrait slug={b.slug} patch={patch} size="h-6 w-6" title={b.name} />
                  <span className="text-[12px] text-white/75">{b.name}</span>
                  {b.tier != null && <span className="text-[10px] text-white/40">T{b.tier}</span>}
                </span>
              ))}
        </div>
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="flex items-center gap-1 text-[11px] font-bold tracking-widest text-white/45">
            <Shuffle className="h-4 w-4" /> FLEX
          </span>
          {(intel?.flex_warnings || []).length === 0
            ? <span className="text-[12px] text-white/30">none flagged</span>
            : intel.flex_warnings.slice(0, 3).map((f) => (
                <span key={f.name} className="truncate text-[12px] text-white/70">
                  {f.name}<span className="text-white/35"> ({(f.roles || []).map((r) => ROLE_LABELS[r] || r).join("/")})</span>
                </span>
              ))}
        </div>
        <div className="flex items-center justify-end gap-1.5">
          <span className="text-[11px] font-bold tracking-widest text-white/45">ENEMY</span>
          <Chip tone="amber">AD {threat.physical_threats || 0}</Chip>
          <Chip tone="accent">AP {threat.magic_threats || 0}</Chip>
          {threat.heavy_cc_count > 0 && <Chip tone="enemy">CC {threat.heavy_cc_count}</Chip>}
        </div>
      </div>
    </div>
  );
}
