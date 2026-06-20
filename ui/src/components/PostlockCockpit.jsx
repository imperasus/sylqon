import { Fragment, useState } from "react";
import {
  ArrowLeftRight, Brain, Check, CheckCircle2, ChevronDown, ChevronRight, Gauge,
  Loader2, Lock, Package, ShieldHalf, Skull, Sparkles, Sword, Swords, Target, Users,
} from "lucide-react";
import { usePerkIcons } from "../api.js";
import { DAMAGE_COLORS, ROLE_LABELS, TIER_STYLE, itemUrl, spellUrl } from "../assets.js";
import { useBuildVariants } from "../hooks/useBuildVariants.js";
import {
  ChampPortrait, Chip, EmptyState, Panel, Score100, ScorePill, SectionTitle,
  Tabs, ThreatBadge,
} from "./shared.jsx";

const EMPTY_DIFF = { added: [], removed: [] };
const ROLE_STARTER_IDS = new Set([1101, 1102, 1103, 3865, 3866, 3867]);

const fmtAdv = (v) => `${v > 0 ? "+" : ""}${v}`;

function Banner({ injection }) {
  const status = injection?.status || "idle";
  const map = {
    ok: { icon: CheckCircle2, cls: "border-good/45 bg-good/10 text-good", title: "IMPORTED",
          sub: injection?.detail || "Runes, spells and items are live in the client." },
    partial: { icon: Loader2, spin: true, cls: "border-amber/45 bg-amber/10 text-amber", title: "IMPORTING…",
               sub: injection?.detail || "Spells need an active champ select." },
    idle: { icon: Lock, cls: "border-white/15 bg-white/5 text-white/55", title: "READY",
            sub: "Imports automatically once the lobby is fully locked." },
  };
  const s = map[status] || map.idle;
  return (
    <div className={`frost flex items-center gap-2.5 border px-3 py-1.5 ${s.cls}`}>
      <s.icon className={`h-4 w-4 ${s.spin ? "animate-spin" : ""}`} />
      <div className="leading-tight">
        <div className="font-display text-[13px] font-bold tracking-[0.18em]">{s.title}</div>
        <div className="text-[11px] tracking-wide text-white/55">{s.sub}</div>
      </div>
    </div>
  );
}

function VariantTabs({ variants, activeIndex, importVariant, importing, patch }) {
  if (variants.length < 2) return null;
  const items = variants.map((v, i) => {
    const active = i === activeIndex;
    const icons = (v.items || []).slice(0, 3);
    return {
      key: i,
      label: (
        <span className="flex items-center gap-2" title={v.reasoning || v.name}>
          <span className="truncate font-display tracking-wide">{v.name || (v.primary ? "Recommended" : "Alt")}</span>
          <span className="flex items-center gap-0.5">
            {icons.map((it, j) => (
              <img key={`${it.id}-${j}`} src={itemUrl(patch, it.id)} alt="" className="h-5 w-5 rounded ring-1 ring-white/12" draggable={false} />
            ))}
          </span>
          {v.archetype && <Chip tone="accent">{v.archetype}</Chip>}
          {active && (importing
            ? <Loader2 className="h-4 w-4 animate-spin text-amber" />
            : <Check className="h-4 w-4 text-good" />)}
        </span>
      ),
    };
  });
  return <Tabs items={items} active={activeIndex} onSelect={(i) => importVariant(i)} />;
}

/* ----------------------------------------------------------------- scorecard */

/* SVG strength ring (no gradient — flat stroke), used for the overall score. */
function ScoreRing({ value, label }) {
  const v = Math.round(value ?? 0);
  const r = 22, c = 2 * Math.PI * r;
  const stroke = v >= 75 ? "var(--color-good)" : v >= 55 ? "var(--color-accent)" : "var(--color-amber)";
  return (
    <div className="relative grid shrink-0 place-items-center">
      <svg width="56" height="56" className="-rotate-90">
        <circle cx="28" cy="28" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
        <circle cx="28" cy="28" r={r} fill="none" stroke={stroke} strokeWidth="4" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} />
      </svg>
      <div className="absolute flex flex-col items-center leading-none">
        <span className="font-display text-[18px] font-extrabold" style={{ color: stroke }}>{v}</span>
        <span className="mt-0.5 text-[8px] tracking-[0.15em] text-white/40">{label}</span>
      </div>
    </div>
  );
}

const STAT_BAR = {
  accent: ["bg-accent", "text-accent"], ally: ["bg-ally", "text-ally"],
  amber: ["bg-amber", "text-amber"], good: ["bg-good", "text-good"], mana: ["bg-mana", "text-mana"],
};

function StatBar({ label, value, display, tone = "accent" }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const [bg, text] = STAT_BAR[tone] || STAT_BAR.accent;
  return (
    <div className="flex items-center gap-2">
      <span className="w-[66px] shrink-0 text-[11px] text-white/55">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
        <div className={`h-full rounded-full ${bg}`} style={{ width: `${v}%` }} />
      </div>
      <span className={`w-9 shrink-0 text-right font-mono text-[11px] font-bold tabular-nums ${text}`}>{display}</span>
    </div>
  );
}

function Scorecard({ matchup, patch }) {
  const ch = matchup.champion || {};
  const s = matchup.scores || {};
  const tier = TIER_STYLE[ch.tier];
  return (
    <Panel title="MATCHUP SCORE" icon={Gauge} accent="accent">
      <div className="flex items-center gap-3">
        <ChampPortrait slug={ch.slug} patch={patch} size="h-14 w-14" accent="accent" title={ch.name} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-display text-[17px] font-extrabold tracking-wide text-white/95">{ch.name}</div>
          <div className="mt-1 flex items-center gap-1.5">
            <Chip tone="ally">{ROLE_LABELS[ch.role] || ch.role || "—"}</Chip>
            {tier && <span className={`rounded border px-1.5 py-px text-[11px] font-bold ${tier.cls}`}>{tier.label}</span>}
          </div>
        </div>
        <ScoreRing value={s.total} label="OVERALL" />
      </div>
      <div className="mt-0.5 flex flex-col gap-1.5">
        <StatBar label="Counter" value={s.counter} display={Math.round(s.counter ?? 0)} tone="accent" />
        <StatBar label="Synergy" value={s.synergy} display={Math.round(s.synergy ?? 0)} tone="ally" />
        <StatBar label="Meta tier" value={s.meta} display={Math.round(s.meta ?? 0)} tone="amber" />
        <StatBar label="Win rate" value={s.win_rate}
                 display={matchup.win_rate_pct != null ? `${matchup.win_rate_pct}%` : "—"} tone="good" />
        <StatBar label="Mastery" value={s.comfort} display={Math.round(s.comfort ?? 0)} tone="mana" />
      </div>
      {matchup.lane_score != null && (
        <div className="mt-0.5 flex items-center justify-between rounded-md border border-white/8 bg-white/[0.015] px-2.5 py-1.5">
          <span className="t-label" title="Laning-phase read: counter score weighted toward your direct opponent.">LANE PHASE</span>
          <Score100 value={matchup.lane_score} />
        </div>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------- synergy / counter rows */

function PairItem({ item, patch, signed }) {
  const v = item.value;
  return (
    <div className="flex flex-col items-center gap-1" title={`${item.name} · ${ROLE_LABELS[item.role] || item.role || ""}`}>
      <ChampPortrait slug={item.slug} patch={patch} size="h-9 w-9" round
                     accent={item.is_lane_opponent ? "accent" : "white"} title={item.name} />
      {v == null
        ? <span className="text-[10px] text-white/25">—</span>
        : signed ? <ScorePill score={v} /> : <span className="font-mono text-[12px] font-bold tabular-nums text-ally">{v}</span>}
    </div>
  );
}

function PairPanel({ title, icon, accent, items, patch, avg, signed }) {
  if (!items?.length) return null;
  const avgEl = avg != null && (
    <span className={`text-[11px] font-bold ${signed ? (avg > 0 ? "text-good" : avg < 0 ? "text-bad" : "text-white/45") : "text-ally"}`}>
      avg {signed ? fmtAdv(avg) : avg}
    </span>
  );
  return (
    <Panel title={title} icon={icon} accent={accent} right={avgEl}>
      <div className="flex flex-wrap justify-around gap-x-2 gap-y-1.5">
        {items.map((it) => <PairItem key={`${it.name}-${it.role}`} item={it} patch={patch} signed={signed} />)}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------- lane matchup */

function killThreatRead(threats = []) {
  const t = new Set(threats);
  if (t.has("suppression") || t.has("burst_ad") || t.has("burst_ap")) return "high";
  if (t.has("heavy_cc")) return "medium";
  return "low";
}

function LaneMatchup({ matchup, patch }) {
  const opp = matchup.lane_opponent;
  if (!opp) return null;
  const adv = opp.advantage;
  const verdict = adv == null ? { label: "NO MATCHUP DATA", tone: "muted" }
    : adv > 1.5 ? { label: `FAVOURED ${fmtAdv(adv)}`, tone: "good" }
    : adv < -1.5 ? { label: `TOUGH ${fmtAdv(adv)}`, tone: "bad" }
    : { label: `EVEN ${fmtAdv(adv)}`, tone: "amber" };
  const trading = adv == null ? "unknown" : adv > 1.5 ? "you win trades" : adv < -1.5 ? "they win trades" : "even trades";
  return (
    <Panel title="LANE MATCHUP" icon={Swords} accent="enemy" right={<Chip tone={verdict.tone}>{verdict.label}</Chip>}>
      <div className="flex items-center gap-2.5">
        <ChampPortrait slug={opp.slug} patch={patch} size="h-11 w-11" accent="enemy" title={opp.name} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[14px] font-bold text-white/90">{opp.name}</span>
            <span className="text-[11px] tracking-widest text-white/35">{ROLE_LABELS[opp.role] || opp.role}</span>
            {opp.damage_type && opp.damage_type !== "—" && (
              <span className={`rounded border px-1 text-[10px] font-bold ${DAMAGE_COLORS[opp.damage_type] || ""}`}>{opp.damage_type}</span>
            )}
          </div>
          {opp.threats?.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {opp.threats.slice(0, 3).map((t) => <ThreatBadge key={t} threat={t} />)}
            </div>
          )}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
        <span className="flex items-center gap-1.5">
          <ArrowLeftRight className="h-3.5 w-3.5 text-accent/70" />
          <span className="text-white/45">Trading:</span><span className="text-white/75">{trading}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <Skull className="h-3.5 w-3.5 text-enemy/70" />
          <span className="text-white/45">Kill threat:</span><span className="text-white/75">{killThreatRead(opp.threats)}</span>
        </span>
      </div>
    </Panel>
  );
}

/* --------------------------------------------------------------- team stats */

function TeamStats({ lobby, intel }) {
  const ally = lobby?.ally_summary || {};
  const comp = intel?.enemy_comp;
  const ad = ally.physical_threats || 0, ap = ally.magic_threats || 0;
  const total = ad + ap || 1;
  const adPct = Math.round((ad / total) * 100), apPct = 100 - adPct;
  return (
    <Panel title="TEAM STATS" icon={ShieldHalf} accent="white">
      <div className="text-[10px] tracking-wide text-white/40">Your team damage profile</div>
      <div className="flex h-2 overflow-hidden rounded-full bg-white/8">
        <div className="bg-amber" style={{ width: `${adPct}%` }} />
        <div className="bg-mana" style={{ width: `${apPct}%` }} />
      </div>
      <div className="flex justify-between text-[10px] font-bold">
        <span className="text-amber">AD {adPct}%</span><span className="text-mana">AP {apPct}%</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(ally.heavy_cc_count || 0) > 0 && <Chip tone="enemy">CC {ally.heavy_cc_count}</Chip>}
        {(ally.frontline || 0) > 0
          ? <Chip tone="ally">FRONTLINE {ally.frontline}</Chip>
          : <Chip tone="bad">NO FRONTLINE</Chip>}
        {(ally.tanks || 0) > 0 && <Chip tone="muted">TANK {ally.tanks}</Chip>}
      </div>
      {comp && comp.archetype !== "unknown" && comp.archetype !== "balanced" && (
        <div className="mt-0.5 border-t border-white/8 pt-2">
          <div className="flex items-center gap-1.5">
            <span className="t-label text-enemy/70">ENEMY COMP</span>
            <Chip tone="enemy">{comp.label}</Chip>
          </div>
          {comp.counter_plan && <p className="mt-1 t-body text-white/60">{comp.counter_plan}</p>}
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------- build */

function ItemCell({ item, patch, added, small }) {
  const box = small ? "h-9 w-9" : "h-10 w-10";
  return (
    <div className="flex shrink-0 flex-col items-center gap-0.5" title={item.description ? `${item.name} — ${item.description}` : item.name}>
      <div className="relative">
        <img src={itemUrl(patch, item.id)} alt={item.name}
             className={`${box} rounded-md ${added ? "ring-2 ring-accent" : ROLE_STARTER_IDS.has(item.id) ? "ring-2 ring-ally/70" : "ring-1 ring-white/12"}`} draggable={false} />
        {added && <span className="absolute -top-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-accent font-mono text-[10px] font-bold text-bg">+</span>}
      </div>
      <span className="line-clamp-1 max-w-[48px] text-center text-[10px] text-white/40">{item.name}</span>
    </div>
  );
}

function ItemRow({ label, sub, items, patch, addedSet, arrows, small }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2">
        <span className="t-label">{label}</span>
        {sub && <span className="text-[10px] tracking-wide text-white/25">{sub}</span>}
      </div>
      <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
        {items.map((it, i) => (
          <Fragment key={`${it.id}-${i}`}>
            <ItemCell item={it} patch={patch} added={addedSet?.has(it.name)} small={small} />
            {arrows && i < items.length - 1 && <ChevronRight className="mt-3 h-4 w-4 shrink-0 text-white/20" />}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function SpellSlot({ patch, name, k }) {
  return (
    <div className="relative" title={`${k} · ${name}`}>
      <img src={spellUrl(patch, name)} alt={name} className="h-8 w-8 rounded border border-mana/40" draggable={false} />
      <span className="absolute -right-1 -bottom-1 grid h-4 w-4 place-items-center rounded bg-bg-2 font-mono text-[9px] font-bold text-mana">{k}</span>
    </div>
  );
}

function ItemsPanel({ build, patch, enemySummary }) {
  const opt = build.optimized;
  const added = new Set(build.diff?.added || []);
  const items = opt.items || [];
  const core = items.slice(0, 4);
  const situational = items.slice(4);
  const chosen = new Set(items.map((i) => i.name));
  const alts = (opt.situational_pool || []).filter((p) => !chosen.has(p.name));

  return (
    <Panel title="ITEM ORDER" icon={Package}
           right={<div className="flex items-center gap-1.5">{opt.archetype && <Chip tone="accent">{opt.archetype}</Chip>}<span className="text-[11px] text-white/35">{opt.source}</span></div>}>
      <div className="flex flex-1 flex-col gap-2">
        {(opt.starting_items || []).length > 0 && (
          <ItemRow label="START" items={opt.starting_items} patch={patch} addedSet={added} small />
        )}
        <ItemRow label="CORE" sub="fixed" items={core} patch={patch} addedSet={added} arrows />
        <ItemRow label="SITUATIONAL" sub={enemySummary ? `vs ${enemySummary}` : ""} items={situational} patch={patch} addedSet={added} arrows />
        {alts.length > 0 && <ItemRow label="ALTERNATIVES" items={alts} patch={patch} small />}

        <div className="mt-auto flex items-center gap-2.5 border-t border-white/8 pt-2">
          <span className="t-label">SUMM</span>
          <SpellSlot patch={patch} name={opt.spell1} k="D" />
          <SpellSlot patch={patch} name={opt.spell2 || "Flash"} k="F" />
          {opt.skill_order?.length > 0 && (
            <>
              <div className="mx-1 h-5 w-px bg-white/10" />
              <span className="t-label">MAX</span>
              <div className="flex items-center gap-1">
                {opt.skill_order.map((kk, i) => (
                  <Fragment key={`${kk}-${i}`}>
                    <span className="grid h-6 w-6 place-items-center rounded border border-accent/40 bg-accent/10 font-display text-[12px] font-extrabold text-accent-bright">{kk}</span>
                    {i < opt.skill_order.length - 1 && <ChevronRight className="h-3 w-3 text-white/25" />}
                  </Fragment>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </Panel>
  );
}

function Perk({ id, icons, keystone }) {
  const icon = icons[id];
  return (
    <div className={`grid place-items-center rounded-full border bg-bg-2 ${keystone ? "glow-accent h-12 w-12 border-accent/70" : "h-8 w-8 border-mana/30"}`} title={icon?.name || id}>
      {icon ? <img src={icon.url} alt="" className={keystone ? "h-[86%] w-[86%]" : "h-[82%] w-[82%]"} draggable={false} />
            : <span className="font-mono text-[10px] text-white/40">{String(id).slice(-2)}</span>}
    </div>
  );
}

function StyleIcon({ id, icons }) {
  const icon = icons[id];
  if (!icon) return null;
  return <img src={icon.url} alt="" className="h-4 w-4" draggable={false} />;
}

function RuneTree({ title, styleId, ids, icons, accent }) {
  const tone = accent === "primary" ? "text-accent/80" : "text-mana/70";
  return (
    <div className="flex flex-1 flex-col gap-1.5 rounded-md border border-white/8 bg-white/[0.015] p-2.5">
      <div className="flex items-center gap-1.5">
        <StyleIcon id={styleId} icons={icons} />
        <span className={`t-label ${tone}`}>{icons[styleId]?.name || title}</span>
      </div>
      {ids.map((id, i) => (
        <div key={`${id}-${i}`} className={`flex items-center gap-2 ${accent === "primary" && i === 0 ? "py-0.5" : ""}`}>
          <Perk id={id} icons={icons} keystone={accent === "primary" && i === 0} />
          <span className={`text-[12px] leading-tight ${accent === "primary" && i === 0 ? "font-semibold text-accent-bright" : "text-white/60"}`}>{icons[id]?.name || "—"}</span>
        </div>
      ))}
    </div>
  );
}

function RunesPanel({ build }) {
  const icons = usePerkIcons();
  const opt = build.optimized;
  const primary = (opt.rune_perk_ids || []).slice(0, 4);
  const secondary = (opt.rune_perk_ids || []).slice(4, 6);

  return (
    <Panel title="RUNES" icon={Sparkles} accent="white">
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex gap-2">
          <RuneTree title="PRIMARY" styleId={opt.primary_style_id} ids={primary} icons={icons} accent="primary" />
          <RuneTree title="SECONDARY" styleId={opt.secondary_style_id} ids={secondary} icons={icons} accent="secondary" />
        </div>
        <div className="mt-auto flex items-center justify-center gap-5 rounded-md border border-mana/20 bg-mana/5 py-1.5">
          {(opt.shard_ids || []).map((id, i) => (
            <div key={`${id}-${i}`} className="flex flex-col items-center gap-0.5" title={icons[id]?.name || id}>
              <div className="grid h-8 w-8 place-items-center rounded-full border border-mana/40 bg-bg-2">
                {icons[id] ? <img src={icons[id].url} alt="" className="h-6 w-6" draggable={false} /> : <span className="font-mono text-[10px] text-mana/60">{String(id).slice(-2)}</span>}
              </div>
              <span className="max-w-[64px] text-center text-[9px] leading-tight text-white/40">{icons[id]?.name || ""}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

/* --------------------------------------------------------- AI strategy foot */

const PHASE_TONE = {
  good: ["border-good", "text-good"], amber: ["border-amber", "text-amber"], mana: ["border-mana", "text-mana"],
};

function Phase({ label, tone, text }) {
  const [border, color] = PHASE_TONE[tone] || PHASE_TONE.good;
  return (
    <div className={`border-l-2 ${border} pl-2.5`}>
      <div className={`text-[10px] font-bold tracking-[0.12em] ${color}`}>{label}</div>
      <div className="mt-0.5 text-[11px] leading-snug text-white/70">{text || "—"}</div>
    </div>
  );
}

function LanePlan({ plan }) {
  return (
    <div className="frost frost-accent p-2.5">
      <SectionTitle accent="accent" icon={Brain}>AI LANE GAME PLAN · OLLAMA</SectionTitle>
      <div className="mt-1.5 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <Phase label="EARLY · 1–6" tone="good" text={plan.early} />
        <Phase label="MID · 7–13" tone="amber" text={plan.mid} />
        <Phase label="LATE · 14+" tone="mana" text={plan.late} />
      </div>
      {plan.win_condition && (
        <div className="mt-2 flex items-start gap-1.5 border-t border-white/8 pt-2">
          <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-bright" />
          <span className="text-[11px]">
            <span className="font-bold tracking-wide text-accent/80">WIN CONDITION: </span>
            <span className="text-white/75">{plan.win_condition}</span>
          </span>
        </div>
      )}
    </div>
  );
}

function AIInsight({ build }) {
  const [expanded, setExpanded] = useState(false);
  const opt = build.optimized;
  const added = build.diff?.added || [];
  const removed = build.diff?.removed || [];
  const reasoning = opt.reasoning || (added.length || removed.length
    ? "Adjusted the standard build for this enemy composition — see the swaps below."
    : "Standard meta build is optimal here; no swaps required.");
  const long = reasoning.length > 180;

  return (
    <div className="frost frost-accent flex items-start gap-2.5 p-2.5">
      <Brain className="mt-0.5 h-4 w-4 shrink-0 text-accent-bright" />
      <div className="min-w-0 flex-1">
        <SectionTitle accent="accent">AI STRATEGY · OLLAMA</SectionTitle>
        <p className={`mt-1 t-body text-white/80 ${expanded ? "" : "line-clamp-3"}`}>{reasoning}</p>
        {long && (
          <button onClick={() => setExpanded((v) => !v)}
            className="mt-0.5 flex cursor-pointer items-center gap-0.5 text-[11px] font-bold tracking-wide text-accent/80 hover:text-accent-bright">
            {expanded ? "Show less" : "Show more"}
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
          </button>
        )}
        {(added.length > 0 || removed.length > 0) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {added.map((n) => <Chip key={n} tone="accent">+ {n}</Chip>)}
            {removed.map((n) => <span key={n} className="rounded border border-bad/30 bg-bad/10 px-1.5 py-px text-[11px] text-bad/80 line-through">{n}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}

export default function PostlockCockpit({ state, api }) {
  const build = state?.build;
  const patch = state?.cache?.patch || "16.12.1";
  const matchup = build?.matchup;
  const lanePlan = build?.lane_plan;
  const lobby = state?.lobby;
  const intel = state?.draft_intel;
  const enemySummary = (lobby?.enemies || []).map((e) => e.name).slice(0, 3).join(", ");
  const { variants, active, activeIndex, importVariant, importing } = useBuildVariants(build, api?.injectVariant);

  if (!build || !active) {
    return (
      <div className="frost h-full">
        <EmptyState icon={Sword} label="NO BUILD COMPILED"
                    hint="Lock in a champion and wait for the lobby to finalize — the loadout imports automatically." />
      </div>
    );
  }
  const activeBuild = { optimized: active, diff: activeIndex === 0 ? build.diff : EMPTY_DIFF };

  const header = (
    <div className="flex items-center gap-3">
      <Banner injection={state?.injection} />
      <div className="scroll-thin flex-1 overflow-x-auto">
        <VariantTabs variants={variants} activeIndex={activeIndex} importVariant={importVariant} importing={importing} patch={patch} />
      </div>
    </div>
  );
  const foot = lanePlan ? <LanePlan plan={lanePlan} /> : <AIInsight build={activeBuild} />;

  // No scored matchup (DB not synced yet) → fall back to the classic build view.
  if (!matchup) {
    return (
      <div className="flex h-full min-h-0 flex-col gap-3">
        {header}
        <div className="grid min-h-0 flex-1 grid-cols-[1.3fr_1fr] gap-3">
          <ItemsPanel build={activeBuild} patch={patch} enemySummary={enemySummary} />
          <RunesPanel build={activeBuild} />
        </div>
        {foot}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2.5">
      {header}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(230px,0.85fr)_minmax(0,1.25fr)_minmax(240px,0.95fr)] gap-2.5">
        {/* Left rail — scorecard + per-champ synergy & counter values. */}
        <div className="scroll-thin flex min-h-0 flex-col gap-2.5 overflow-y-auto pr-0.5">
          <Scorecard matchup={matchup} patch={patch} />
          <PairPanel title="SYNERGY" icon={Users} accent="ally"
                     items={matchup.synergies} patch={patch} avg={matchup.synergy_avg} />
          <PairPanel title="COUNTERS" icon={Swords} accent="enemy"
                     items={matchup.counters} patch={patch} avg={matchup.counter_avg} signed />
        </div>

        {/* Center — direct lane matchup, then the compiled build. */}
        <div className="scroll-thin flex min-h-0 flex-col gap-2.5 overflow-y-auto pr-0.5">
          <LaneMatchup matchup={matchup} patch={patch} />
          <ItemsPanel build={activeBuild} patch={patch} enemySummary={enemySummary} />
        </div>

        {/* Right — runes + team-wide stats / enemy comp. */}
        <div className="scroll-thin flex min-h-0 flex-col gap-2.5 overflow-y-auto pr-0.5">
          <RunesPanel build={activeBuild} />
          <TeamStats lobby={lobby} intel={intel} />
        </div>
      </div>
      {foot}
    </div>
  );
}
