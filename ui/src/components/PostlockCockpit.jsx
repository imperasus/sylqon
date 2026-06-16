import { Fragment, useState } from "react";
import {
  Brain, Check, CheckCircle2, ChevronDown, ChevronRight, Loader2, Lock, Package, Sparkles, Sword,
} from "lucide-react";
import { usePerkIcons } from "../api.js";
import { itemUrl, spellUrl } from "../assets.js";
import { useBuildVariants } from "../hooks/useBuildVariants.js";
import { Chip, EmptyState, Panel, SectionTitle, Tabs } from "./shared.jsx";

const EMPTY_DIFF = { added: [], removed: [] };
const ROLE_STARTER_IDS = new Set([1101, 1102, 1103, 3865, 3866, 3867]);

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
  const enemySummary = (state?.lobby?.enemies || []).map((e) => e.name).slice(0, 3).join(", ");
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center gap-3">
        <Banner injection={state?.injection} />
        <div className="scroll-thin flex-1 overflow-x-auto">
          <VariantTabs variants={variants} activeIndex={activeIndex} importVariant={importVariant} importing={importing} patch={patch} />
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[1.3fr_1fr] gap-3">
        <ItemsPanel build={activeBuild} patch={patch} enemySummary={enemySummary} />
        <RunesPanel build={activeBuild} />
      </div>
      <AIInsight build={activeBuild} />
    </div>
  );
}
