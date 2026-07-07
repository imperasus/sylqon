import { Gauge } from "lucide-react";
import { squareUrl, spellUrl, THREAT_LABELS } from "../assets.js";

/* Summoner-spell icons with hover tooltip = description. */
export function SpellPips({ spells, patch, size = "h-6 w-6" }) {
  if (!spells?.length) return null;
  return (
    <div className="flex gap-1">
      {spells.map((s) => (
        <img
          key={s.name}
          src={spellUrl(patch, s.name)}
          alt={s.name}
          title={`${s.name} — ${s.description}`}
          className={`${size} rounded border border-white/15 bg-black/40`}
          draggable={false}
        />
      ))}
    </div>
  );
}

const RING = {
  white: "border-white/15",
  accent: "border-accent/55",
  ally: "border-ally/55",
  enemy: "border-enemy/55",
};

/* Champion portrait with optional accent ring. */
export function ChampPortrait({ slug, patch, size = "h-12 w-12", accent = "white",
                                title, round = false, lazy = true }) {
  const ring = RING[accent] || RING.white;
  const shape = round ? "rounded-full" : "rounded-md";
  if (!slug) {
    return (
      <div className={`${size} ${shape} shrink-0 border ${ring} grid place-items-center bg-bg-2 text-white/25`}>
        <span className="text-xs">?</span>
      </div>
    );
  }
  return (
    <img
      src={squareUrl(patch, slug)}
      alt={title || slug}
      title={title}
      className={`${size} ${shape} shrink-0 border ${ring} object-cover`}
      draggable={false}
      loading={lazy ? "lazy" : "eager"}
    />
  );
}

export function ThreatBadge({ threat }) {
  const hot = threat === "suppression" || threat === "heavy_cc";
  return (
    <span
      className={`rounded border px-1 py-px text-2xs font-semibold tracking-wider uppercase
        ${hot
          ? "border-enemy/70 bg-enemy/15 text-enemy"
          : "border-enemy/35 bg-enemy/10 text-enemy/80"}`}
    >
      {THREAT_LABELS[threat] || threat}
    </span>
  );
}

const TITLE_COLOR = {
  accent: "text-accent/85",
  ally: "text-ally/85",
  enemy: "text-enemy/85",
  white: "text-white/50",
};

export function SectionTitle({ children, accent = "accent", icon: Icon, right }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className={`flex items-center gap-1.5 font-display text-sm font-bold tracking-[0.08em] ${TITLE_COLOR[accent] || TITLE_COLOR.white}`}>
        {Icon && <Icon className="h-4 w-4" />}
        {children}
      </div>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}

/* A signed synergy/counter score chip (green up, red down). */
export function ScorePill({ score }) {
  const positive = score > 0;
  const neutral = score === 0;
  return (
    <span
      className={`rounded px-1 py-px font-mono text-sm font-bold tabular-nums
        ${neutral
          ? "bg-white/8 text-white/45"
          : positive
            ? "bg-good/15 text-good"
            : "bg-bad/15 text-bad"}`}
    >
      {positive ? "+" : ""}{score}
    </span>
  );
}

/* A 0-100 strength read: right-aligned mono value + a 2rem micro-bar, graded by
   value (distinct from the signed ScorePill). */
export function Score100({ value }) {
  const v = Math.max(0, Math.min(100, Math.round(value ?? 0)));
  const text = v >= 75 ? "text-good" : v >= 55 ? "text-accent-bright" : "text-white/45";
  const bar = v >= 75 ? "bg-good" : v >= 55 ? "bg-accent" : "bg-white/25";
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <span className="h-1 w-8 overflow-hidden rounded-full bg-white/10">
        <span className={`block h-full ${bar}`} style={{ width: `${v}%` }} />
      </span>
      <span className={`w-6 text-right font-mono text-sm font-bold tabular-nums ${text}`}>{v}</span>
    </span>
  );
}

/* Generic flat panel with an optional titled header (full-bleed hairline). */
export function Panel({ title, icon, accent = "accent", right, edge, className = "", children }) {
  const edgeCls = edge === "ally" ? "edge-ally" : edge === "enemy" ? "edge-enemy"
    : edge === "accent" ? "edge-accent" : "";
  return (
    <div className={`surface ${edgeCls} flex min-h-0 flex-col gap-2 p-2.5 ${className}`}>
      {title && (
        <div className="-mx-2.5 border-b border-line/70 px-2.5 pb-1.5">
          <SectionTitle accent={accent} icon={icon} right={right}>{title}</SectionTitle>
        </div>
      )}
      {children}
    </div>
  );
}

/* Tiny labelled chip. tone: accent | ally | enemy | good | bad | amber | muted */
export function Chip({ tone = "muted", children, title }) {
  const tones = {
    accent: "border-accent/40 bg-accent/10 text-accent-bright",
    ally: "border-ally/40 bg-ally/10 text-ally",
    enemy: "border-enemy/40 bg-enemy/10 text-enemy",
    good: "border-good/40 bg-good/10 text-good",
    bad: "border-bad/40 bg-bad/10 text-bad",
    amber: "border-amber/40 bg-amber/10 text-amber",
    muted: "border-white/15 bg-white/5 text-white/55",
  };
  return (
    <span title={title}
          className={`rounded border px-1.5 py-px text-xs font-semibold tracking-wider uppercase ${tones[tone] || tones.muted}`}>
      {children}
    </span>
  );
}

/* Thin progress / confidence bar. */
export function Bar({ value = 0, tone = "accent" }) {
  const bg = { accent: "bg-accent", ally: "bg-ally", enemy: "bg-enemy", good: "bg-good",
               amber: "bg-amber" }[tone] || "bg-accent";
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-white/10">
      <div className={`h-full ${bg}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

const SCORE_TONE = {
  good: { text: "text-good", bg: "bg-good" },
  bad: { text: "text-bad", bg: "bg-bad" },
  amber: { text: "text-amber", bg: "bg-amber" },
};

/* Estimated draft win% — head-to-head composition balance read.
   balance: { win_pct, label, tone, confidence, drivers:[{text, sign}] }.
   Below ~40% confidence (sparse draft) it shows a READING… state instead of a
   misleadingly precise number. Reused by the live draft and post-lock views. */
export function DraftScorecard({ balance }) {
  if (!balance) return null;
  const win = Math.max(0, Math.min(100, balance.win_pct ?? 50));
  const reading = (balance.confidence ?? 0) < 40;
  const t = SCORE_TONE[balance.tone] || SCORE_TONE.amber;
  const lo = Math.min(50, win), hi = Math.max(50, win);
  return (
    <Panel title="DRAFT WIN %" icon={Gauge} accent="accent"
           right={reading
             ? <span className="text-2xs font-bold tracking-widest text-white/35">READING…</span>
             : <Chip tone={balance.tone}>{balance.label}</Chip>}>
      <div className="flex items-center gap-3">
        <div className="flex shrink-0 flex-col items-center leading-none"
             title="Deterministic estimate from comp archetypes, damage balance, frontline and lane matchup — not a trained model.">
          <span className={`font-mono text-4xl font-bold tabular-nums ${reading ? "text-white/30" : t.text}`}>
            {win}<span className="text-lg">%</span>
          </span>
          <span className="mt-0.5 text-3xs font-semibold tracking-[0.08em] text-white/35">EST.</span>
        </div>
        <div className="relative h-1 flex-1 overflow-hidden rounded-full bg-white/8">
          <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-white/25" />
          {!reading && (
            <div className={`absolute inset-y-0 ${t.bg}`}
                 style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
          )}
        </div>
      </div>
      {!reading && balance.drivers?.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {balance.drivers.map((d) => (
            <span key={d.text}
                  className={`font-mono text-xs tabular-nums ${d.sign > 0 ? "text-good" : "text-bad"}`}>
              {d.sign > 0 ? "+" : "−"} {d.text}
            </span>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function EmptyState({ icon: Icon, label, hint }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-white/30">
      {Icon && <Icon className="h-7 w-7" />}
      <span className="font-display text-base tracking-[0.1em]">{label}</span>
      {hint && <span className="max-w-[15rem] text-center text-base text-white/40">{hint}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- buttons
   primary = solid accent (dark text), secondary = outline, ghost = bare. */
export function Button({ variant = "secondary", icon: Icon, children, className = "",
                        disabled, ...rest }) {
  const variants = {
    primary: "border-transparent bg-accent text-bg font-bold hover:bg-accent-bright",
    secondary: "border-line-strong text-white/70 hover:border-accent/50 hover:text-accent-bright",
    ghost: "border-transparent text-white/55 hover:bg-white/8 hover:text-white/85",
    danger: "border-enemy/40 text-enemy/85 hover:bg-enemy/12",
  };
  return (
    <button
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border px-2.5 py-1
        text-xs font-semibold tracking-wider uppercase transition-colors
        ${disabled ? "cursor-default opacity-50" : "cursor-pointer"}
        ${variants[variant] || variants.secondary} ${className}`}
      {...rest}
    >
      {Icon && <Icon className="h-4 w-4" />}
      {children}
    </button>
  );
}

/* Square 32×32 icon action button (add / star / lock). */
export function IconButton({ icon: Icon, title, active, tone = "accent", className = "", ...rest }) {
  const tones = {
    accent: active ? "border-accent/70 bg-accent/20 text-accent-bright"
                   : "border-white/12 text-white/45 hover:border-accent/50 hover:text-accent/90",
    amber: active ? "border-amber/70 bg-amber/20 text-amber"
                  : "border-white/12 text-white/45 hover:border-amber/50 hover:text-amber",
  };
  return (
    <button
      title={title}
      className={`grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md border
        transition-colors ${tones[tone] || tones.accent} ${className}`}
      {...rest}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

/* Win / Loss pill. */
export function WLPill({ win }) {
  return (
    <span className={`grid h-5 w-5 place-items-center rounded text-xs font-extrabold
      ${win ? "bg-good/18 text-good" : "bg-bad/18 text-bad"}`}>
      {win ? "W" : "L"}
    </span>
  );
}

/* Labelled stat badge (e.g. WR / PR) with an explanatory tooltip. */
export function StatBadge({ label, value, tone = "muted", tip }) {
  const tones = {
    good: "text-good", accent: "text-accent-bright", muted: "text-white/70", warn: "text-amber",
  };
  return (
    <span title={tip} className="flex flex-col items-end leading-none">
      <span className={`font-mono text-sm font-bold tabular-nums ${tones[tone] || tones.muted}`}>{value}</span>
      <span className="text-3xs font-bold tracking-widest text-white/35">{label}</span>
    </span>
  );
}

/* Generic list row: portrait + name + right-side slot. Carries interaction states. */
export function ChampionRow({ slug, patch, name, sub, rank, right, accent = "white",
                             selected, inPool, onClick, title, className = "" }) {
  const state = selected ? "row-selected" : inPool ? "row-pool" : "";
  return (
    <div
      onClick={onClick}
      title={title}
      className={`row ${onClick ? "row-hover cursor-pointer" : ""} ${state}
        flex items-center gap-2.5 rounded-md px-2 py-1.5 ${className}`}
    >
      {rank != null && (
        <span className="w-4 shrink-0 text-center font-mono text-xs font-bold tabular-nums text-white/35">{rank}</span>
      )}
      <ChampPortrait slug={slug} patch={patch} size="h-8 w-8" accent={accent} title={name} />
      <div className="min-w-0 flex-1 leading-tight">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-base font-semibold text-white/90">{name}</span>
          {inPool && <Chip tone="accent">pool</Chip>}
        </div>
        {sub && <div className="truncate text-xs text-white/40">{sub}</div>}
      </div>
      {right}
    </div>
  );
}

/* Segmented control. items: [{ key, label, render? }] */
export function Tabs({ items, active, onSelect, className = "" }) {
  return (
    <div className={`inline-flex items-stretch gap-0.5 self-start rounded-md border border-line bg-bg-2 p-0.5 ${className}`}>
      {items.map((it) => {
        const on = it.key === active;
        return (
          <button
            key={it.key}
            onClick={() => onSelect?.(it.key)}
            className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-sm font-semibold
              tracking-wide transition-colors
              ${on ? "bg-elev text-accent-bright"
                   : "text-white/45 hover:bg-white/5 hover:text-white/75"}`}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}
