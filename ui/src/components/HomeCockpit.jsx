import { useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  ChevronLeft, ChevronRight, History, Plus, Search, Sparkles, Star, TrendingUp, X,
} from "lucide-react";
import {
  fetchChampionsByRole, fetchRecentMatches, useChampionStats, usePool, useScout, useStaticData,
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

/* ------------------------------------------------------------------ hero */
function KPI({ label, tone = "text-white/90", title, children }) {
  return (
    <div className="flex min-w-0 flex-col justify-center gap-1 px-4" title={title}>
      <span className="t-label">{label}</span>
      <span className={`font-mono text-lg leading-none font-semibold tabular-nums ${tone}`}>{children}</span>
    </div>
  );
}

/* One flat strip of headline numbers — the "analytics dashboard" signature.
   The role selector lives here too: it drives the pool, meta and scout below. */
function HeroStrip({ role, onRole, poolCount, recentWr, builds, patch }) {
  const roleItems = ROLE_ORDER.map((r) => ({ key: r, label: ROLE_LABELS[r] }));
  return (
    <div className="frost flex shrink-0 items-stretch divide-x divide-line px-1 py-2">
      <div className="flex flex-col justify-center gap-1 px-3">
        <span className="t-label">Role</span>
        <Tabs items={roleItems} active={role} onSelect={onRole} />
      </div>
      <KPI label="Pool" title="Bajnokok a szerep-poolodban">{poolCount}</KPI>
      <KPI label="Recent WR"
           tone={recentWr == null ? "text-white/30" : recentWr >= 0.5 ? "text-good" : "text-bad"}
           title="Win rate az utolsó lekért meccseken">
        {recentWr == null ? "—" : pct(recentWr)}
      </KPI>
      <KPI label="Builds" title="Cache-elt buildek">{builds}</KPI>
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

function PoolSection({ role, pool, champions, patch, stats, scout, save, className = "" }) {
  const [query, setQuery] = useState("");
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
  // Pool grows with the column; show what fits (no scroll), flag the overflow.
  const [listRef, fit] = useFitCount({ rowRem: 3.0, gapRem: 0.25, min: 1, max: current.length || 1 });

  return (
    <Section title="YOUR POOL" icon={Star} right={<Chip tone="muted">{ROLE_LABELS[role]}</Chip>} className={className}>
      <div ref={listRef} className="-mr-1 flex min-h-0 flex-1 flex-col gap-1 overflow-hidden pr-1">
        {current.length === 0
          ? <span className="px-1 text-sm text-white/30">No champions for {ROLE_LABELS[role]} — search below.</span>
          : current.slice(0, fit).map((name) => (
              <PoolCard key={name} name={name} slug={slugOf[name]} patch={patch} stat={stats[name]} onRemove={remove} />
            ))}
        {current.length > fit && (
          <div className="pt-0.5 text-center text-2xs tracking-wide text-white/30">
            +{current.length - fit} more in pool
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute top-1/2 left-2 h-4 w-4 -translate-y-1/2 text-white/30" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search champion…"
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
function MetaTable({ role, patch, pool, save, onOpen }) {
  const [rows, setRows] = useState([]);
  const [page, setPage] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setPage(0);
    fetchChampionsByRole(role).then((r) => { if (!cancelled) setRows(r.champions || []); }).catch(() => {});
    return () => { cancelled = true; };
  }, [role]);
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

  return (
    <Panel title="PATCH META" icon={TrendingUp} accent="white"
           right={<Chip tone="muted">op.gg · {ROLE_LABELS[role]}</Chip>} className="gap-2 min-w-0">
      {rows.length === 0 ? (
        <EmptyState icon={TrendingUp} label="NO META DATA" hint="Hit SYNC to pull the tier list from op.gg." />
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
                  className={`row row-hover grid cursor-pointer grid-cols-[1.5rem_1fr_3.5rem_3.5rem_2.75rem_2rem] items-center gap-2 px-2 py-1 even:bg-white/[0.015] ${added ? "row-pool" : ""}`}>
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
                className="grid h-6 w-6 cursor-pointer place-items-center rounded border border-white/12 text-white/50 transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-default disabled:opacity-30">
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="font-mono text-xs tabular-nums text-white/45">
                {start + 1}–{start + shown.length} <span className="text-white/25">/ {capped.length}</span>
              </span>
              <button onClick={() => setPage(Math.min(pages - 1, curPage + 1))} disabled={curPage >= pages - 1}
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
  const [listRef, fit] = useFitCount({ rowRem: 2.9, gapRem: 0.125, min: 3, max: 10 });

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
        <div ref={listRef} className="-mr-1 min-h-0 flex-1 space-y-0.5 overflow-hidden pr-1">
          {matches.slice(0, fit).map((m) => {
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
          {matches.length > fit && (
            <div className="pt-0.5 text-center text-2xs tracking-wide text-white/30">
              +{matches.length - fit} older game{matches.length - fit === 1 ? "" : "s"}
            </div>
          )}
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

export default function HomeCockpit({ state }) {
  const { champions } = useStaticData();
  const { pool, save } = usePool();
  const stats = useChampionStats();
  const [role, setRole] = useState("bottom");
  const scout = useScout(role);
  const patch = state?.cache?.patch || "16.12.1";
  const [detail, setDetail] = useState(null);

  // Matches are fetched here (not in the section) so the hero strip can show the
  // recent win rate headline from the same payload.
  const [matches, setMatches] = useState([]);
  const [matchesLoading, setMatchesLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    const load = () => fetchRecentMatches(10)
      .then((r) => { if (!cancelled) setMatches(r.matches || []); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setMatchesLoading(false); });
    load();
    const t = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);
  const recentWr = matches.length
    ? matches.filter((m) => m.result === "Win").length / matches.length
    : null;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <HeroStrip role={role} onRole={setRole} poolCount={(pool[role] || []).length}
                 recentWr={recentWr} builds={state?.cache?.builds ?? 0} patch={patch} />

      <MacroCoach />

      <div className="grid min-h-0 flex-1 grid-cols-[1.6fr_1fr] gap-3">
        <MetaTable role={role} patch={patch} pool={pool} save={save} onOpen={setDetail} />
        <div className="frost flex min-h-0 flex-col divide-y divide-line">
          <PoolSection role={role} pool={pool} champions={champions} patch={patch}
                       stats={stats} scout={scout} save={save} className="flex-[1.15]" />
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
