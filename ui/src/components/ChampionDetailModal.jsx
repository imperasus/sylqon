import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Loader2, ShieldAlert, Sparkles, Swords, Trophy, X } from "lucide-react";
import { fetchProBuilds } from "../api.js";
import { itemUrl, TIER_STYLE } from "../assets.js";
import { useChampionDetails } from "../hooks/useChampionData.js";
import { ChampPortrait, ScorePill, SectionTitle } from "./shared.jsx";

/* Pro/esports builds for this champion+role (op.gg MCP, Claude-ingested). */
function ProBuilds({ champion, role, patch }) {
  const [builds, setBuilds] = useState([]);
  useEffect(() => {
    let cancelled = false;
    if (!champion) return;
    fetchProBuilds(champion, role)
      .then((r) => { if (!cancelled) setBuilds(r.pro_builds || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [champion, role]);

  return (
    <div className="md:col-span-2">
      <SectionTitle accent="gold" icon={Trophy}>PRO BUILDS</SectionTitle>
      {builds.length === 0 && (
        <div className="mt-2 px-1 text-[13px] text-white/30">
          No pro builds ingested yet — populate via the op.gg MCP (POST /api/pro-build).
        </div>
      )}
      <div className="mt-2 space-y-2">
        {builds.map((b, i) => (
          <div key={`${b.pro_name}-${i}`}
               className="rounded-lg border border-white/8 bg-white/[0.015] px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-[14px] font-bold text-gold-bright">{b.pro_name}</span>
              {b.team && <span className="rounded border border-white/15 px-1.5 py-px text-[11px] tracking-wider text-white/55">{b.team}</span>}
              {b.region && <span className="text-[11px] tracking-widest text-white/35">{b.region}</span>}
              {b.result && (
                <span className={`text-[11px] font-bold tracking-widest ${b.result === "Win" ? "text-good" : "text-bad"}`}>
                  {b.result.toUpperCase()}
                </span>
              )}
              {b.patch && <span className="ml-auto font-mono text-[11px] text-white/30">{b.patch}</span>}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {(b.build?.items || []).map((it, j) => (
                <img key={`${it.id}-${j}`} src={itemUrl(patch, it.id)} alt={it.name} title={it.name}
                     className="h-9 w-9 rounded-md ring-1 ring-white/12" draggable={false} />
              ))}
              {b.build?.skill_order?.length > 0 && (
                <span className="ml-1 font-mono text-[12px] tracking-wider text-white/55">
                  {b.build.skill_order.join(" › ")}
                </span>
              )}
              {b.build?.keystone && (
                <span className="ml-1 rounded border border-gold/30 bg-gold/10 px-1.5 py-0.5 text-[11px] text-gold-bright">
                  {b.build.keystone}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChampRow({ c, patch, right }) {
  return (
    <div className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-white/5">
      <ChampPortrait slug={c.slug} patch={patch} size="h-8 w-8" round />
      <span className="flex-1 truncate text-[14px] text-white/75">{c.name}</span>
      {right}
    </div>
  );
}

/** Popup: counters, synergies and the cached build/runes for a champion+role. */
export default function ChampionDetailModal({ champion, role, patch, onClose }) {
  const { details, loading } = useChampionDetails(champion?.id, role);
  if (!champion) return null;

  const stats = champion.stats || {};
  const tier = TIER_STYLE[stats.tier] || null;
  const build = details?.build;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/65 p-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="glass glow-gold relative flex max-h-[86vh] w-full max-w-3xl flex-col gap-4 overflow-hidden rounded-2xl border border-gold/30 p-5"
      >
        <button onClick={onClose}
                className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-md border border-white/15 text-white/50 hover:border-gold/40 hover:text-gold-bright">
          <X className="h-4 w-4" />
        </button>

        {/* header */}
        <div className="flex items-center gap-3">
          <ChampPortrait slug={champion.slug} patch={patch} size="h-14 w-14" accent="gold" round />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-display text-[20px] font-bold tracking-wider text-white">{champion.name}</span>
              {tier && (
                <span className={`rounded border px-1.5 py-px text-[12px] font-bold ${tier.cls} ${tier.glow}`}>
                  {tier.label}
                </span>
              )}
              <span className="text-[12px] uppercase tracking-widest text-white/35">{role}</span>
            </div>
            <div className="mt-1 flex gap-4 text-[13px] text-white/55">
              {stats.win_rate != null && <span>WR <b className="text-white/80">{stats.win_rate}%</b></span>}
              {stats.pick_rate != null && <span>PR <b className="text-white/80">{stats.pick_rate}%</b></span>}
            </div>
          </div>
        </div>

        {loading && (
          <div className="flex items-center gap-2 py-6 text-[14px] text-white/50">
            <Loader2 className="h-4 w-4 animate-spin text-gold" /> Loading op.gg data…
          </div>
        )}

        {!loading && details && !details.error && (
          <div className="scroll-thin grid min-h-0 gap-5 overflow-y-auto pr-1 md:grid-cols-2">
            {/* counters */}
            <div>
              <SectionTitle accent="enemy" icon={ShieldAlert}>COUNTERS</SectionTitle>
              <div className="mt-2 space-y-0.5">
                {details.counters?.length
                  ? details.counters.slice(0, 8).map((c) => (
                      <ChampRow key={`${c.name}-${c.role}`} c={c} patch={patch}
                                right={<ScorePill score={Math.round(c.advantage)} />} />
                    ))
                  : <div className="px-1 text-[13px] text-white/30">No counter data yet.</div>}
              </div>
            </div>

            {/* synergies */}
            <div>
              <SectionTitle accent="ally" icon={Sparkles}>SYNERGIES</SectionTitle>
              <div className="mt-2 space-y-0.5">
                {details.synergies?.length
                  ? details.synergies.slice(0, 8).map((s) => (
                      <ChampRow key={`${s.name}-${s.role}`} c={s} patch={patch}
                                right={<span className="font-mono text-[13px] text-good">{s.score}</span>} />
                    ))
                  : <div className="px-1 text-[13px] text-white/30">No synergy data yet.</div>}
              </div>
            </div>

            {/* build */}
            <div className="md:col-span-2">
              <SectionTitle accent="gold" icon={Swords}>RECOMMENDED BUILD</SectionTitle>
              {build ? (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {(build.items || []).map((it, i) => (
                    <img key={`${it.id}-${i}`} src={itemUrl(patch, it.id)} alt={it.name} title={it.name}
                         className="h-11 w-9 rounded-md ring-1 ring-white/12" draggable={false} />
                  ))}
                  {build.keystone && (
                    <span className="ml-2 rounded border border-gold/30 bg-gold/10 px-2 py-0.5 text-[12px] text-gold-bright">
                      {build.keystone}
                    </span>
                  )}
                </div>
              ) : (
                <div className="mt-2 px-1 text-[13px] text-white/30">No cached build for this role yet.</div>
              )}
            </div>

            <ProBuilds champion={champion.name} role={role} patch={patch} />
          </div>
        )}
      </motion.div>
    </div>
  );
}
