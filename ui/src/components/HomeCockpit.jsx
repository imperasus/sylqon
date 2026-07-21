import { useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  ChevronLeft, ChevronRight, History, Plus, RefreshCw, Search, Sparkles, Star,
  TrendingUp, X,
} from "lucide-react";
import {
  useChampionsByRole, useChampionStats, useMacroCoach, usePool, useRecentMatches,
  useScout, useStaticData,
} from "../api.js";
import { useFitCount, useMediaQuery } from "../hooks/useFitCount.js";
import { pct, ROLE_LABELS, ROLE_ORDER, TIER_STYLE } from "../assets.js";
import {
  Button, ChampPortrait, ChampionRow, Chip, EmptyState, IconButton, Panel, SectionTitle,
  StatBadge, Tabs, WLPill,
} from "./shared.jsx";
import ChampionDetailModal from "./ChampionDetailModal.jsx";
import MatchAnalysisModal from "./MatchAnalysisModal.jsx";
import MacroCoach from "./MacroCoach.jsx";
import NextMatchBar from "./NextMatchBar.jsx";

/* ------------------------------------------------------------------ hero */
function KPI({ label, tone = "text-white/90", title, onClick, children }) {
  const body = (
    <>
      <span className="t-label">{label}</span>
      <span className={`font-mono text-lg leading-none font-semibold tabular-nums ${tone}`}>{children}</span>
    </>
  );
  if (!onClick) {
    return <div className="flex min-w-0 flex-col justify-center gap-1 px-4" title={title}>{body}</div>;
  }
  return (
    <button onClick={onClick} title={title}
            className="flex min-w-0 cursor-pointer flex-col justify-center gap-1 px-4 text-left
                       transition-colors hover:bg-white/5">
      {body}
    </button>
  );
}

/* One flat strip of headline numbers — the "analytics dashboard" signature.
   The role selector lives here too: it drives the pool, meta and scout below. */
function HeroStrip({ role, onRole, poolCount, recentWr, builds, patch, onPool, onSync }) {
  const roleItems = ROLE_ORDER.map((r) => ({ key: r, label: ROLE_LABELS[r] }));
  return (
    <div className="surface flex shrink-0 items-stretch divide-x divide-line px-1 py-2">
      <div className="flex flex-col justify-center gap-1 px-3">
        <span className="t-label">Role</span>
        <Tabs items={roleItems} active={role} onSelect={onRole} />
      </div>
      <KPI label="Pool" title="Champions in your role pool — click to add one" onClick={onPool}>
        {poolCount}
      </KPI>
      <KPI label="Recent WR"
           tone={recentWr == null ? "text-white/30" : recentWr >= 0.5 ? "text-good" : "text-bad"}
           title="Win rate over the recently fetched games">
        {recentWr == null ? "—" : pct(recentWr)}
      </KPI>
      <KPI label="Builds" title="Cached builds — click to re-sync from op.gg" onClick={onSync}>
        {builds}
      </KPI>
      <KPI label="Patch">{patch}</KPI>
    </div>
  );
}

/* A titled sub-section inside a shared flat surface (hairline-divided). */
function Section({ title, icon, accent = "accent", right, className = "", children }) {
  return (
    <section className={`flex min-h-0 flex-col gap-2 p-2.5 ${className}`}>
      <div className="-mx-2.5 border-b border-line/70 px-2.5 pb-1.5">
        <SectionTitle accent={accent} icon={icon} right={right}>{title}</SectionTitle>
      </div>
      {children}
    </section>
  );
}

/* Overflow affordance. The panels deliberately show only what fits, but the
   hidden rows used to be unreachable — this makes the count a real control that
   opens the rest instead of a dead label. */
function MoreToggle({ hidden, expanded, onToggle, noun }) {
  if (hidden <= 0) return null;
  return (
    <button onClick={onToggle}
            className="w-full cursor-pointer pt-0.5 text-center text-2xs tracking-wide text-white/30
                       transition-colors hover:text-accent">
      {expanded ? "show less" : `+${hidden} more ${noun}${hidden === 1 ? "" : "s"}`}
    </button>
  );
}

/* ----------------------------------------------------------------- pool */
function PoolCard({ name, slug, patch, stat, onRemove }) {
  const wr = stat?.games >= 1 ? stat.win_rate : null;
  return (
    <div className="group row relative flex items-center gap-2.5 rounded-md border border-white/8 bg-white/[0.015] px-2 py-1.5">
      <ChampPortrait slug={slug} patch={patch} size="h-9 w-9" accent="accent" title={name} round />
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-base font-semibold text-accent-bright/90">{name}</div>
        <div className="text-xs text-white/40">
          {stat?.games >= 1 ? `${stat.games} game${stat.games === 1 ? "" : "s"}` : "no games yet"}
        </div>
      </div>
      {wr != null
        ? <StatBadge label="WR" value={pct(wr)} tone={wr >= 0.5 ? "good" : "warn"} tip="Your win rate on this champion" />
        : <span className="text-xs text-white/20">—</span>}
      <button onClick={() => onRemove(name)}
        className="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md border border-transparent text-white/25 opacity-0 transition-all hover:border-bad/50 hover:text-bad group-hover:opacity-100"
        title="Remove from pool">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function PoolSection({ role, pool, champions, patch, stats, scout, save, searchRef, className = "" }) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const slugOf = useMemo(() => {
    const m = {};
    for (const c of champions) m[c.name] = c.slug;
    return m;
  }, [champions]);
  const current = pool[role] || [];
  const inPool = new Set(current);

  const add = (name) => {
    if (inPool.has(name)) return;
    save({ ...pool, [role]: [...current, name] });
    setQuery("");
  };
  const remove = (name) => save({ ...pool, [role]: current.filter((c) => c !== name) });
  const matches = query.trim()
    ? champions.filter((c) => c.name.toLowerCase().includes(query.toLowerCase()) && !inPool.has(c.name)).slice(0, 6)
    : [];
  const top = matches[0];
  // Pool grows with the column; show what fits (no scroll), and let the overflow
  // count open the rest on demand.
  const [listRef, fit] = useFitCount({ rowRem: 3.0, gapRem: 0.25, min: 1, max: current.length || 1 });
  const shown = expanded ? current : current.slice(0, fit);

  return (
    <Section title="YOUR POOL" icon={Star} right={<Chip tone="muted">{ROLE_LABELS[role]}</Chip>} className={className}>
      <div ref={listRef}
           className={`-mr-1 flex min-h-0 flex-1 flex-col gap-1 pr-1 ${expanded ? "overflow-y-auto" : "overflow-hidden"}`}>
        {current.length === 0
          ? <span className="px-1 text-sm text-white/30">No champions for {ROLE_LABELS[role]} — search below.</span>
          : shown.map((name) => (
              <PoolCard key={name} name={name} slug={slugOf[name]} patch={patch} stat={stats[name]} onRemove={remove} />
            ))}
        <MoreToggle hidden={current.length - fit} expanded={expanded} noun="champion"
                    onToggle={() => setExpanded((v) => !v)} />
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute top-1/2 left-2 h-4 w-4 -translate-y-1/2 text-white/30" />
          <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search champion…"
            onKeyDown={(e) => { if (e.key === "Enter" && top) add(top.name); }}
            className="w-full rounded-md border border-line bg-black/30 py-1.5 pr-2 pl-7 text-base text-white/80 outline-none placeholder:text-white/25 focus:border-accent/40" />
          {matches.length > 0 && (
            <div className="absolute z-20 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-line-strong bg-bg-2/98 shadow-xl">
              {matches.map((c) => (
                <button key={c.slug} onClick={() => add(c.name)}
                  className="flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left hover:bg-accent/10">
                  <ChampPortrait slug={c.slug} patch={patch} size="h-6 w-6" round />
                  <span className="text-base text-white/80">{c.name}</span>
                  <Plus className="ml-auto h-4 w-4 text-accent/70" />
                </button>
              ))}
            </div>
          )}
        </div>
        <Button variant="primary" icon={Plus} disabled={!top} onClick={() => top && add(top.name)}>Add</Button>
      </div>

      {scout?.pick && (
        <div className="border-t border-line/70 pt-2">
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-accent" />
            <span className="t-label text-accent/70">Meta Scout</span>
            <Chip tone="muted">{scout.source === "ollama" ? "AI" : "meta"}</Chip>
          </div>
          <div className="mt-2 flex items-center gap-2.5 rounded-md border border-accent/25 bg-accent/[0.06] p-2">
            <ChampPortrait slug={scout.slug} patch={patch} size="h-10 w-10" accent="accent" round title={scout.pick} />
            <div className="min-w-0">
              <div className="truncate font-display text-md font-bold text-accent-bright">{scout.pick}</div>
              <div className="line-clamp-2 text-xs leading-snug text-white/55">{scout.reason}</div>
            </div>
          </div>
        </div>
      )}
    </Section>
  );
}

/* ----------------------------------------------------------------- meta */
function MetaTable({ role, patch, pool, save, onOpen, onSync, syncing }) {
  const { rows, loading } = useChampionsByRole(role);
  const [page, setPage] = useState(0);
  const inPool = new Set(pool[role] || []);
  const addPool = (name, e) => {
    e.stopPropagation();
    if (inPool.has(name)) return;
    save({ ...pool, [role]: [...(pool[role] || []), name] });
  };

  // Fit exactly the rows the panel height allows (no inner scroll); the rest is
  // reachable by paging. The tier list is ranked, so paging through it reads
  // naturally and the panel always stays full.
  const capped = rows.slice(0, 40);
  const [listRef, perCol] = useFitCount({ rowRem: 2.3, min: 4, max: 40 });
  // On a wide/ultrawide window, fan the tier list into 2 columns so the extra
  // width fills with twice as many champions instead of stretching each row.
  const wide = useMediaQuery("(min-width: 1600px)");
  const cols = wide ? 2 : 1;
  const perPage = perCol * cols;
  const pages = Math.max(1, Math.ceil(capped.length / perPage));
  const curPage = Math.min(page, pages - 1);
  const start = curPage * perPage;
  const shown = capped.slice(start, start + perPage);

  const syncButton = (
    <Button variant="secondary" icon={RefreshCw} onClick={onSync} disabled={syncing}
            className={syncing ? "[&>svg]:animate-spin" : ""}
            title="Pull the tier list and builds from op.gg">
      {syncing ? "Syncing" : "Sync"}
    </Button>
  );

  return (
    <Panel title="PATCH META" icon={TrendingUp} accent="white"
           right={<div className="flex items-center gap-2">
             <Chip tone="muted">op.gg · {ROLE_LABELS[role]}</Chip>
             {syncButton}
           </div>} className="gap-2 min-w-0">
      {loading ? (
        <div className="flex flex-col gap-1 px-1 py-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-6 animate-pulse rounded bg-white/5" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState icon={TrendingUp} label="NO META DATA"
                    hint="Hit Sync above to pull the tier list from op.gg." />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* sticky header — one labelled group per body column so the WR/PR/Tier
              headers sit above BOTH columns on a wide (2-up) layout, not just the
              right one. Mirrors the body grid (same gap + columnGap). */}
          <div className="border-b border-line"
               style={cols > 1 ? {
                 display: "grid", columnGap: "1.25rem",
                 gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
               } : undefined}>
            {Array.from({ length: cols }).map((_, i) => (
              <div key={i}
                   className="grid grid-cols-[1.5rem_1fr_3.5rem_3.5rem_2.75rem_2rem] items-center gap-2 px-2 pb-1.5">
                <span className="t-label text-center">#</span>
                <span className="t-label">Champion</span>
                <span className="t-label text-right" title="Win rate">WR</span>
                <span className="t-label text-right" title="Pick rate">PR</span>
                <span className="t-label text-center">Tier</span>
                <span className="t-label text-center" title="Add to pool / open"> </span>
              </div>
            ))}
          </div>
          <div ref={listRef} className="-mr-1 min-h-0 flex-1 overflow-hidden pr-1"
               style={cols > 1 ? {
                 display: "grid", gridAutoFlow: "column", columnGap: "1.25rem",
                 gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
                 gridTemplateRows: `repeat(${perCol}, max-content)`,
               } : undefined}>
            {shown.map((c, i) => {
              const tier = TIER_STYLE[c.stats?.tier] || TIER_STYLE[3];
              const added = inPool.has(c.name);
              return (
                <div key={c.id} onClick={() => onOpen(c)}
                  role="button" tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(c); }
                  }}
                  className={`row row-hover grid cursor-pointer grid-cols-[1.5rem_1fr_3.5rem_3.5rem_2.75rem_2rem] items-center gap-2 px-2 py-1 even:bg-white/[0.015] focus:outline-none focus-visible:ring-1 focus-visible:ring-accent/70 ${added ? "row-pool" : ""}`}>
                  <span className="text-center font-mono text-xs tabular-nums text-white/35">{start + i + 1}</span>
                  <div className="flex min-w-0 items-center gap-2">
                    <ChampPortrait slug={c.slug} patch={patch} size="h-7 w-7" title={c.name} round />
                    <span className="truncate text-base font-semibold text-white/85">{c.name}</span>
                    {added && <Chip tone="accent">pool</Chip>}
                  </div>
                  <span className="text-right font-mono text-sm tabular-nums text-good">{c.stats?.win_rate != null ? `${c.stats.win_rate}%` : "—"}</span>
                  <span className="text-right font-mono text-sm tabular-nums text-white/50">{c.stats?.pick_rate != null ? `${c.stats.pick_rate}%` : "—"}</span>
                  <span className="flex justify-center">
                    <span className={`rounded border px-1 py-px text-2xs font-bold ${tier.cls}`}>{tier.label}</span>
                  </span>
                  <span className="flex justify-center">
                    <IconButton icon={added ? Star : Plus} active={added} onClick={(e) => addPool(c.name, e)}
                                title={added ? "in pool" : "add to pool"} className="!h-7 !w-7" />
                  </span>
                </div>
              );
            })}
          </div>
          {pages > 1 && (
            <div className="mt-1 flex shrink-0 items-center justify-center gap-3 border-t border-line/70 pt-1.5">
              <button onClick={() => setPage(Math.max(0, curPage - 1))} disabled={curPage === 0}
                title="Previous page"
                className="grid h-6 w-6 cursor-pointer place-items-center rounded border border-white/12 text-white/50 transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-default disabled:opacity-30">
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="font-mono text-xs tabular-nums text-white/45">
                {start + 1}–{start + shown.length} <span className="text-white/25">/ {capped.length}</span>
              </span>
              <button onClick={() => setPage(Math.min(pages - 1, curPage + 1))} disabled={curPage >= pages - 1}
                title="Next page"
                className="grid h-6 w-6 cursor-pointer place-items-center rounded border border-white/12 text-white/50 transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-default disabled:opacity-30">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------- matches */
function MatchesSection({ patch, matches, loading, className = "" }) {
  const [selected, setSelected] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [listRef, fit] = useFitCount({ rowRem: 2.9, gapRem: 0.125, min: 3, max: 10 });
  const shown = expanded ? matches : matches.slice(0, fit);

  return (
    <Section title="RECENT GAMES" icon={History} accent="white"
             right={<Chip tone="muted">click for AI review</Chip>} className={className}>
      {loading ? (
        <div className="flex flex-col gap-2 px-1 py-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-md bg-white/5" />
          ))}
        </div>
      ) : matches.length === 0 ? (
        <EmptyState icon={History} label="NO GAMES" hint="Recent Summoner's Rift games show here when the client is connected." />
      ) : (
        <div ref={listRef}
             className={`-mr-1 min-h-0 flex-1 space-y-0.5 pr-1 ${expanded ? "overflow-y-auto" : "overflow-hidden"}`}>
          {shown.map((m) => {
            const win = m.result === "Win";
            const k = m.kda || {};
            return (
              <ChampionRow
                key={m.id} slug={m.slug} patch={patch} name={m.champion}
                sub={ROLE_LABELS[m.role] || m.role} accent={win ? "accent" : "enemy"}
                onClick={() => setSelected(m)}
                title="Open the AI post-game review"
                right={
                  <div className="flex items-center gap-2.5">
                    <span className="font-mono text-sm tabular-nums text-white/60">{k.kills}/{k.deaths}/{k.assists}</span>
                    <WLPill win={win} />
                  </div>
                }
              />
            );
          })}
          <MoreToggle hidden={matches.length - fit} expanded={expanded} noun="game"
                      onToggle={() => setExpanded((v) => !v)} />
        </div>
      )}
      <AnimatePresence>
        {selected && (
          <MatchAnalysisModal match={selected} patch={patch} onClose={() => setSelected(null)} />
        )}
      </AnimatePresence>
    </Section>
  );
}

export default function HomeCockpit({ state, api }) {
  const { champions } = useStaticData();
  const { pool, save } = usePool();
  const stats = useChampionStats();
  const [role, setRole] = useState("bottom");
  const scout = useScout(role);
  const patch = state?.cache?.patch || "16.12.1";
  const [detail, setDetail] = useState(null);
  const poolSearchRef = useRef(null);

  const { matches, loading: matchesLoading } = useRecentMatches(10);
  const { coach } = useMacroCoach();
  const recentWr = matches.length
    ? matches.filter((m) => m.result === "Win").length / matches.length
    : null;

  const syncing = Boolean(state?.sync?.running);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <HeroStrip role={role} onRole={setRole} poolCount={(pool[role] || []).length}
                 recentWr={recentWr} builds={state?.cache?.builds ?? 0} patch={patch}
                 onPool={() => poolSearchRef.current?.focus()}
                 onSync={() => !syncing && api?.fullSync?.()} />

      <NextMatchBar goal={coach?.goal} priority={coach?.priorities?.[0]} scout={scout}
                    patch={patch} role={ROLE_LABELS[role]}
                    clientConnected={Boolean(state?.lcu?.connected)} />

      <MacroCoach />

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_1fr] gap-3">
        <MetaTable role={role} patch={patch} pool={pool} save={save} onOpen={setDetail}
                   onSync={() => api?.fullSync?.()} syncing={syncing} />
        <div className="surface flex min-h-0 flex-col divide-y divide-line">
          <PoolSection role={role} pool={pool} champions={champions} patch={patch}
                       stats={stats} scout={scout} save={save} searchRef={poolSearchRef}
                       className="flex-[1.15]" />
          <MatchesSection patch={patch} matches={matches} loading={matchesLoading} className="flex-1" />
        </div>
      </div>

      <AnimatePresence>
        {detail && (
          <ChampionDetailModal champion={detail} role={role} patch={patch} onClose={() => setDetail(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}
