import { useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  Crown, History, Plus, Search, Sparkles, Star, TrendingUp, X,
} from "lucide-react";
import {
  fetchChampionsByRole, fetchRecentMatches, useChampionStats, usePool, useScout, useStaticData,
} from "../api.js";
import { pct, ROLE_LABELS, ROLE_ORDER, TIER_STYLE } from "../assets.js";
import {
  Button, ChampPortrait, ChampionRow, Chip, EmptyState, IconButton, Panel, StatBadge, WLPill,
} from "./shared.jsx";
import ChampionDetailModal from "./ChampionDetailModal.jsx";
import MatchAnalysisModal from "./MatchAnalysisModal.jsx";

function RoleTabs({ role, onRole }) {
  return (
    <div className="flex gap-1">
      {ROLE_ORDER.map((r) => (
        <button key={r} onClick={() => onRole(r)}
          className={`cursor-pointer rounded px-2.5 py-1 text-[12px] font-bold tracking-widest transition-colors
            ${role === r ? "bg-accent/15 text-accent-bright" : "text-white/40 hover:bg-white/5 hover:text-white/70"}`}>
          {ROLE_LABELS[r]}
        </button>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------- pool */
function PoolCard({ name, slug, patch, stat, onRemove }) {
  const wr = stat?.games >= 1 ? stat.win_rate : null;
  return (
    <div className="group row relative flex items-center gap-2.5 rounded-md border border-white/8 bg-white/[0.015] px-2 py-1.5">
      <ChampPortrait slug={slug} patch={patch} size="h-9 w-9" accent="accent" title={name} round />
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-[13px] font-semibold text-accent-bright/90">{name}</div>
        <div className="text-[11px] text-white/40">
          {stat?.games >= 1 ? `${stat.games} game${stat.games === 1 ? "" : "s"}` : "no games yet"}
        </div>
      </div>
      {wr != null
        ? <StatBadge label="WR" value={pct(wr)} tone={wr >= 0.5 ? "good" : "warn"} tip="Your win rate on this champion" />
        : <span className="text-[11px] text-white/20">—</span>}
      <button onClick={() => onRemove(name)}
        className="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-full border border-transparent text-white/25 opacity-0 transition-all hover:border-bad/50 hover:text-bad group-hover:opacity-100"
        title="Remove from pool">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function PoolPanel({ role, pool, champions, patch, stats, scout, save }) {
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

  return (
    <Panel title="YOUR POOL" icon={Star} right={<Chip tone="muted">{ROLE_LABELS[role]}</Chip>} className="gap-2.5 min-w-0">
      <div className="scroll-thin -mr-1 flex max-h-44 min-h-[72px] flex-col gap-1 overflow-y-auto pr-1">
        {current.length === 0
          ? <span className="px-1 text-[12px] text-white/30">No champions for {ROLE_LABELS[role]} — search below.</span>
          : current.map((name) => (
              <PoolCard key={name} name={name} slug={slugOf[name]} patch={patch} stat={stats[name]} onRemove={remove} />
            ))}
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute top-1/2 left-2 h-4 w-4 -translate-y-1/2 text-white/30" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search champion…"
            onKeyDown={(e) => { if (e.key === "Enter" && top) add(top.name); }}
            className="w-full rounded-md border border-white/10 bg-black/30 py-1.5 pr-2 pl-7 text-[13px] text-white/80 outline-none placeholder:text-white/25 focus:border-accent/40" />
          {matches.length > 0 && (
            <div className="absolute z-20 mt-1 w-full max-h-48 overflow-y-auto rounded-md border border-accent/30 bg-bg-2/98 shadow-xl">
              {matches.map((c) => (
                <button key={c.slug} onClick={() => add(c.name)}
                  className="flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left hover:bg-accent/10">
                  <ChampPortrait slug={c.slug} patch={patch} size="h-6 w-6" round />
                  <span className="text-[13px] text-white/80">{c.name}</span>
                  <Plus className="ml-auto h-4 w-4 text-accent/70" />
                </button>
              ))}
            </div>
          )}
        </div>
        <Button variant="primary" icon={Plus} disabled={!top} onClick={() => top && add(top.name)}>Add</Button>
      </div>

      {scout?.pick && (
        <div className="mt-auto border-t border-white/8 pt-2.5">
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-accent" />
            <span className="t-label text-accent/70">Meta Scout</span>
            <Chip tone="muted">{scout.source === "ollama" ? "AI" : "meta"}</Chip>
          </div>
          <div className="mt-2 flex items-center gap-2.5 rounded-md border border-accent/25 bg-accent/[0.06] p-2">
            <ChampPortrait slug={scout.slug} patch={patch} size="h-10 w-10" accent="accent" round title={scout.pick} />
            <div className="min-w-0">
              <div className="truncate font-display text-[14px] font-bold text-accent-bright">{scout.pick}</div>
              <div className="line-clamp-2 text-[11px] leading-snug text-white/55">{scout.reason}</div>
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- meta */
function MetaTable({ role, patch, pool, save, onOpen }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let cancelled = false;
    fetchChampionsByRole(role).then((r) => { if (!cancelled) setRows(r.champions || []); }).catch(() => {});
    return () => { cancelled = true; };
  }, [role]);
  const inPool = new Set(pool[role] || []);
  const addPool = (name, e) => {
    e.stopPropagation();
    if (inPool.has(name)) return;
    save({ ...pool, [role]: [...(pool[role] || []), name] });
  };

  return (
    <Panel title="PATCH META" icon={TrendingUp} accent="white"
           right={<Chip tone="muted">op.gg · {ROLE_LABELS[role]}</Chip>} className="gap-2 min-w-0">
      {rows.length === 0 ? (
        <EmptyState icon={TrendingUp} label="NO META DATA" hint="Hit SYNC to pull the tier list from op.gg." />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* sticky header */}
          <div className="grid grid-cols-[1.5rem_1fr_3.5rem_3.5rem_2.75rem_2rem] items-center gap-2 border-b border-white/10 px-2 pb-1.5">
            <span className="t-label text-center">#</span>
            <span className="t-label">Champion</span>
            <span className="t-label text-right" title="Win rate">WR</span>
            <span className="t-label text-right" title="Pick rate">PR</span>
            <span className="t-label text-center">Tier</span>
            <span className="t-label text-center" title="Add to pool / open"> </span>
          </div>
          <div className="scroll-thin -mr-1 flex-1 overflow-y-auto pr-1">
            {rows.slice(0, 40).map((c, i) => {
              const tier = TIER_STYLE[c.stats?.tier] || TIER_STYLE[3];
              const added = inPool.has(c.name);
              return (
                <div key={c.id} onClick={() => onOpen(c)}
                  className={`row row-hover grid cursor-pointer grid-cols-[1.5rem_1fr_3.5rem_3.5rem_2.75rem_2rem] items-center gap-2 px-2 py-1 even:bg-white/[0.015] ${added ? "row-pool" : ""}`}>
                  <span className="text-center font-mono text-[11px] tabular-nums text-white/35">{i + 1}</span>
                  <div className="flex min-w-0 items-center gap-2">
                    <ChampPortrait slug={c.slug} patch={patch} size="h-7 w-7" title={c.name} round />
                    <span className="truncate text-[13px] font-semibold text-white/85">{c.name}</span>
                    {added && <Chip tone="accent">pool</Chip>}
                  </div>
                  <span className="text-right font-mono text-[12px] tabular-nums text-good">{c.stats?.win_rate != null ? `${c.stats.win_rate}%` : "—"}</span>
                  <span className="text-right font-mono text-[12px] tabular-nums text-white/50">{c.stats?.pick_rate != null ? `${c.stats.pick_rate}%` : "—"}</span>
                  <span className="flex justify-center">
                    <span className={`rounded border px-1 py-px text-[10px] font-bold ${tier.cls}`}>{tier.label}</span>
                  </span>
                  <span className="flex justify-center">
                    <IconButton icon={added ? Star : Plus} active={added} onClick={(e) => addPool(c.name, e)}
                                title={added ? "in pool" : "add to pool"} className="!h-7 !w-7" />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------- matches */
function MatchesPanel({ patch }) {
  const [matches, setMatches] = useState([]);
  const [matchesLoading, setMatchesLoading] = useState(true);
  const [selected, setSelected] = useState(null);
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

  return (
    <Panel title="RECENT GAMES" icon={History} accent="white"
           right={<Chip tone="muted">click for AI review</Chip>} className="gap-1 min-w-0">
      {matchesLoading ? (
        <div className="flex flex-col gap-2 px-1 py-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 rounded-md bg-white/5 animate-pulse" />
          ))}
        </div>
      ) : matches.length === 0 ? (
        <EmptyState icon={History} label="NO GAMES" hint="Recent Summoner's Rift games show here when the client is connected." />
      ) : (
        <div className="scroll-thin -mr-1 flex-1 space-y-0.5 overflow-y-auto pr-1">
          {matches.slice(0, 8).map((m) => {
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
                    <span className="font-mono text-[12px] tabular-nums text-white/60">{k.kills}/{k.deaths}/{k.assists}</span>
                    <WLPill win={win} />
                  </div>
                }
              />
            );
          })}
        </div>
      )}
      <AnimatePresence>
        {selected && (
          <MatchAnalysisModal match={selected} patch={patch} onClose={() => setSelected(null)} />
        )}
      </AnimatePresence>
    </Panel>
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="frost flex items-center gap-3 px-3 py-1.5">
        <span className="t-label">Role</span>
        <RoleTabs role={role} onRole={setRole} />
        <span className="ml-auto flex items-center gap-1.5 text-[11px] tracking-widest text-white/35">
          <Crown className="h-4 w-4 text-accent/60" /> {state?.cache?.builds ?? 0} BUILDS
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1.1fr_2fr_1.1fr] gap-4">
        <PoolPanel role={role} pool={pool} champions={champions} patch={patch} stats={stats} scout={scout} save={save} />
        <MetaTable role={role} patch={patch} pool={pool} save={save} onOpen={setDetail} />
        <MatchesPanel patch={patch} />
      </div>

      <AnimatePresence>
        {detail && (
          <ChampionDetailModal champion={detail} role={role} patch={patch} onClose={() => setDetail(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}
