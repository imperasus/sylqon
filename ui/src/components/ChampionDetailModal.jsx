import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  ChartLine, Lightbulb, Loader2, Package, ShieldAlert, Sparkles, Swords, Trophy, X, Zap,
} from "lucide-react";
import { fetchProBuilds } from "../api.js";
import { abilityIconUrl, itemUrl, passiveIconUrl, ROLE_LABELS, TIER_STYLE } from "../assets.js";
import { useChampionAbilities, useChampionDetails } from "../hooks/useChampionData.js";
import { ChampPortrait, Chip, ScorePill, SectionTitle } from "./shared.jsx";

const ABILITY_KEYS = ["Q", "W", "E", "R"];
const RANK_STYLE = [
  "ring-accent text-accent",
  "ring-white/40 text-white/60",
  "ring-white/20 text-white/35",
];

function AbilitiesBar({ slug, patch, skillOrder = [] }) {
  const abilities = useChampionAbilities(slug, patch);
  if (!abilities) return null;

  const rankOf = (key) => skillOrder.indexOf(key); // -1 if not ranked (R)
  const all = [
    { key: "P", name: abilities.passive.name, img: passiveIconUrl(patch, abilities.passive.image.full) },
    ...abilities.spells.map((s, i) => ({
      key: ABILITY_KEYS[i], name: s.name, img: abilityIconUrl(patch, s.image.full),
    })),
  ];

  return (
    <div className="md:col-span-2">
      <div className="flex items-center justify-between">
        <SectionTitle accent="accent" icon={Zap}>ABILITIES</SectionTitle>
        {skillOrder.length > 0 && (
          <span className="text-[11px] tracking-wider text-white/40">
            MAX ORDER — R &rsaquo; {skillOrder.join(" › ")}
          </span>
        )}
      </div>
      <div className="mt-2 flex gap-3">
        {all.map(({ key, name, img }) => {
          const rank = rankOf(key);
          return (
            <div key={key} className="flex flex-col items-center gap-1" title={name}>
              <div className={`relative rounded-md ring-1 ${rank >= 0 ? RANK_STYLE[rank].split(" ")[0] : "ring-white/12"}`}>
                <img src={img} alt={name} className="h-10 w-10 rounded-md" draggable={false} />
                {rank >= 0 && (
                  <span className={`absolute -bottom-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-bg-2 text-[9px] font-bold ring-1 ${RANK_STYLE[rank]}`}>
                    {rank + 1}
                  </span>
                )}
              </div>
              <span className="text-[9px] font-bold tracking-widest text-white/40">{key}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* Power curve + playstyle, derived from the champion's class tags. A heuristic
   read (not per-patch data), but a useful at-a-glance "when is this champ strong". */
function powerCurve(tags = []) {
  const t = new Set(tags);
  if (t.has("Marksman")) return [0.35, 0.65, 1.0];
  if (t.has("Assassin")) return [0.6, 1.0, 0.72];
  if (t.has("Mage")) return [0.5, 0.85, 0.92];
  if (t.has("Tank")) return [0.62, 0.85, 0.8];
  if (t.has("Fighter")) return [0.72, 0.92, 0.72];
  if (t.has("Support")) return [0.6, 0.8, 0.85];
  return [0.6, 0.82, 0.82];
}
function curveSummary([e, , l]) {
  if (l >= 0.95) return "Hyper-scaling — weak early, dominant late.";
  if (e >= 0.7 && l < 0.8) return "Early/mid power — close before it scales.";
  return "Balanced curve — flexible across the game.";
}
const TAG_TIP = {
  Marksman: "Farm safely early, hit your 2–3 item spike, then carry fights from max range.",
  Assassin: "Roam for picks and snowball — isolate squishies and chain resets off kills.",
  Mage: "Control the wave and zone with range; look for picks once your full combo is up.",
  Tank: "Front-line engages onto the enemy carries, then peel; build their main damage type.",
  Fighter: "Trade in short windows, then split-push side lanes on your item spikes.",
  Support: "Own vision and wave tracking; enable your carry and rotate to objectives.",
};
function playstyleTip(tags = []) {
  for (const t of tags) if (TAG_TIP[t]) return TAG_TIP[t];
  return "Play to your strengths and group for objectives.";
}

function PowerCurve({ tags }) {
  const c = powerCurve(tags);
  const pts = c.map((v, i) => `${i * 130},${Math.round(52 - v * 44)}`).join(" ");
  return (
    <div>
      <SectionTitle accent="accent" icon={ChartLine}>POWER CURVE</SectionTitle>
      <svg viewBox="0 0 260 62" className="mt-2 w-full" style={{ height: 58 }}>
        <line x1="0" y1="52" x2="260" y2="52" stroke="rgba(255,255,255,0.1)" />
        <polyline points={pts} fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinejoin="round" />
        {c.map((v, i) => (
          <circle key={i} cx={i * 130} cy={Math.round(52 - v * 44)} r="3" fill="var(--color-accent-bright)" />
        ))}
        <text x="0" y="61" fill="rgba(255,255,255,0.35)" fontSize="7">EARLY</text>
        <text x="118" y="61" fill="rgba(255,255,255,0.35)" fontSize="7">MID</text>
        <text x="234" y="61" fill="rgba(255,255,255,0.35)" fontSize="7">LATE</text>
      </svg>
      <p className="mt-1 text-[12px] text-white/55">{curveSummary(c)}</p>
    </div>
  );
}

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

  if (builds.length === 0) return null;
  return (
    <div>
      <SectionTitle accent="gold" icon={Trophy}>PRO BUILDS</SectionTitle>
      <div className="mt-2 space-y-2">
        {builds.map((b, i) => (
          <div key={`${b.pro_name}-${i}`} className="rounded-lg border border-white/8 bg-white/[0.015] px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-[14px] font-bold text-gold-bright">{b.pro_name}</span>
              {b.team && <span className="rounded border border-white/15 px-1.5 py-px text-[11px] tracking-wider text-white/55">{b.team}</span>}
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
                     className="h-9 w-9 rounded-md ring-1 ring-white/12" draggable={false} loading="lazy" />
              ))}
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
      <ChampPortrait slug={c.slug} patch={patch} size="h-7 w-7" round />
      <span className="flex-1 truncate text-[13px] text-white/75">{c.name}</span>
      {right}
    </div>
  );
}

function MatchList({ title, accent, icon, rows, patch, render, empty }) {
  return (
    <div>
      <SectionTitle accent={accent} icon={icon}>{title}</SectionTitle>
      <div className="mt-2 space-y-0.5">
        {rows.length
          ? rows.map((c) => <ChampRow key={`${c.name}-${c.role}`} c={c} patch={patch} right={render(c)} />)
          : <div className="px-1 text-[13px] text-white/30">{empty}</div>}
      </div>
    </div>
  );
}

/* A compact ordered item strip for one build phase. */
function ItemPhase({ label, items, patch, small }) {
  const list = (items || []).filter(Boolean);
  if (!list.length) return null;
  const box = small ? "h-8 w-8" : "h-9 w-9";
  return (
    <div>
      <div className="t-label mb-1 text-white/45">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {list.map((it, i) => (
          <img key={`${it.id ?? it}-${i}`} src={itemUrl(patch, it.id ?? it)} alt={it.name || ""} title={it.name || ""}
               className={`${box} rounded-md ring-1 ring-white/12`} draggable={false} />
        ))}
      </div>
    </div>
  );
}

function BuildPath({ build, patch }) {
  if (!build) return <div className="mt-2 px-1 text-[13px] text-white/30">No cached build for this role yet.</div>;
  const core = build.core_items?.length ? build.core_items : (build.items || []).slice(0, 3);
  const boots = build.boots ? [build.boots] : [];
  const sit = (build.situational_pool || []).slice(0, 4);
  return (
    <div className="mt-2 flex flex-wrap items-start gap-x-5 gap-y-2">
      <ItemPhase label="START" items={build.starting_items} patch={patch} small />
      <ItemPhase label="CORE" items={[...boots, ...core]} patch={patch} />
      <ItemPhase label="SITUATIONAL" items={sit} patch={patch} small />
      {build.keystone && (
        <div>
          <div className="t-label mb-1 text-white/45">RUNES</div>
          <span className="rounded border border-gold/30 bg-gold/10 px-2 py-1 text-[12px] text-gold-bright">{build.keystone}</span>
        </div>
      )}
    </div>
  );
}

/** Popup: power curve, matchups, the cached build path and pro builds. */
export default function ChampionDetailModal({ champion, role, patch, onClose }) {
  const { details, loading } = useChampionDetails(champion?.id, role);
  if (!champion) return null;

  const stats = champion.stats || {};
  const tier = TIER_STYLE[stats.tier] || null;
  const tags = details?.champion?.tags || [];
  const counters = details?.counters || [];
  const hardest = counters.filter((c) => (c.advantage ?? 0) < 0).slice(0, 5);
  const easiest = counters.filter((c) => (c.advantage ?? 0) > 0)
    .sort((a, b) => (b.advantage ?? 0) - (a.advantage ?? 0)).slice(0, 5);
  const duos = (details?.synergies || []).slice(0, 5);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/65 p-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96, y: 8 }}
        onClick={(e) => e.stopPropagation()}
        className="glass glow-gold relative flex max-h-[88vh] w-full max-w-3xl flex-col gap-4 overflow-hidden rounded-2xl border border-gold/30 p-5"
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
              <span className="truncate font-display text-[20px] font-bold tracking-wider text-white">{champion.name}</span>
              {tier && <span className={`rounded border px-1.5 py-px text-[12px] font-bold ${tier.cls} ${tier.glow}`}>{tier.label}</span>}
              <span className="text-[12px] uppercase tracking-widest text-white/35">{ROLE_LABELS[role] || role}</span>
            </div>
            <div className="mt-1 flex items-center gap-3 text-[13px] text-white/55">
              {stats.win_rate != null && <span>WR <b className="text-white/80">{stats.win_rate}%</b></span>}
              {stats.pick_rate != null && <span>PR <b className="text-white/80">{stats.pick_rate}%</b></span>}
              {tags.map((t) => <Chip key={t} tone="muted">{t}</Chip>)}
            </div>
          </div>
        </div>

        {loading && (
          <div className="flex items-center gap-2 py-6 text-[14px] text-white/50">
            <Loader2 className="h-4 w-4 animate-spin text-gold" /> Loading op.gg data…
          </div>
        )}

        {!loading && details && !details.error && (
          <div className="scroll-thin grid min-h-0 gap-x-5 gap-y-4 overflow-y-auto pr-1 md:grid-cols-2">
            <AbilitiesBar slug={champion.slug} patch={patch} skillOrder={details.build?.skill_order || []} />

            {/* left: power curve + playstyle */}
            <div className="flex flex-col gap-4">
              <PowerCurve tags={tags} />
              <div>
                <SectionTitle accent="accent" icon={Lightbulb}>PLAYSTYLE</SectionTitle>
                <p className="mt-2 t-body text-white/70">{playstyleTip(tags)}</p>
              </div>
            </div>

            {/* right: matchups */}
            <div className="flex flex-col gap-4">
              <MatchList title="HARDEST COUNTERS" accent="enemy" icon={ShieldAlert} rows={hardest} patch={patch}
                         render={(c) => <ScorePill score={Math.round(c.advantage)} />} empty="No counter data yet." />
              <MatchList title="EASIEST MATCHUPS" accent="good" icon={Swords} rows={easiest} patch={patch}
                         render={(c) => <ScorePill score={Math.round(c.advantage)} />} empty="No favourable matchups recorded." />
              <MatchList title="BEST DUO PARTNERS" accent="ally" icon={Sparkles} rows={duos} patch={patch}
                         render={(c) => <span className="font-mono text-[13px] text-good">{c.score}</span>} empty="No synergy data yet." />
            </div>

            {/* build path */}
            <div className="md:col-span-2">
              <SectionTitle accent="gold" icon={Package}>BUILD PATH</SectionTitle>
              <BuildPath build={details.build} patch={patch} />
            </div>

            <div className="md:col-span-2"><ProBuilds champion={champion.name} role={role} patch={patch} /></div>
          </div>
        )}
      </motion.div>
    </div>
  );
}
