import { useEffect, useState } from "react";
import { AlertTriangle, Lightbulb, Loader2, ThumbsUp, X } from "lucide-react";
import { fetchMatchAnalysis } from "../api.js";
import { ROLE_LABELS } from "../assets.js";
import { ChampPortrait, SectionTitle, WLPill } from "./shared.jsx";

/* Post-game AI review for one recent game: summary + strengths + mistakes +
   tips (Hungarian). Generated + cached on the backend on first open. */
export default function MatchAnalysisModal({ match, patch, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!match) return;
    let cancelled = false;
    setLoading(true);
    fetchMatchAnalysis(match.id)
      .then((r) => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setData({ error: "request failed" }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [match?.id]);

  if (!match) return null;
  const win = match.result === "Win";
  const k = match.kda || {};
  const unavailable = data && (data.available === false || data.error);

  const Block = ({ icon, accent, title, items, mark, markCls }) =>
    (items || []).length > 0 ? (
      <div>
        <SectionTitle accent={accent} icon={icon}>{title}</SectionTitle>
        <ul className="mt-2 space-y-1.5">
          {items.map((s, i) => (
            <li key={i} className="flex gap-2 t-body text-white/75">
              <span className={`shrink-0 font-bold ${markCls}`}>{mark}</span>
              <span>{s}</span>
            </li>
          ))}
        </ul>
      </div>
    ) : null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/65 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           className="glass glow-gold relative flex max-h-[86vh] w-full max-w-2xl flex-col gap-4 overflow-hidden rounded-2xl border border-accent/30 p-5">
        <button onClick={onClose}
                className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-md border border-white/15 text-white/50 hover:border-accent/40 hover:text-accent-bright">
          <X className="h-4 w-4" />
        </button>

        {/* header */}
        <div className="flex items-center gap-3">
          <ChampPortrait slug={match.slug} patch={patch} size="h-14 w-14" accent={win ? "accent" : "enemy"} round />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-display text-[20px] font-bold tracking-wider text-white">{match.champion}</span>
              <WLPill win={win} />
              <span className="text-[12px] uppercase tracking-widest text-white/35">{ROLE_LABELS[match.role] || match.role}</span>
            </div>
            <div className="mt-1 font-mono text-[13px] text-white/60">
              {k.kills ?? 0}/{k.deaths ?? 0}/{k.assists ?? 0}
            </div>
          </div>
        </div>

        {loading && (
          <div className="flex items-center gap-2 py-6 text-[14px] text-white/50">
            <Loader2 className="h-4 w-4 animate-spin text-accent" /> AI elemzés készítése…
          </div>
        )}

        {!loading && unavailable && (
          <div className="py-6 text-[13px] text-white/45">
            {data.error
              ? "Az elemzés nem érhető el ehhez a meccshez."
              : (data.detail || "Az Ollama jelenleg offline; az elemzés nem generálható.")}
          </div>
        )}

        {!loading && data && !unavailable && (
          <div className="scroll-thin flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
            {data.summary && <p className="t-body text-white/85">{data.summary}</p>}
            <Block icon={ThumbsUp} accent="ally" title="ERŐSSÉGEK" items={data.strengths} mark="+" markCls="text-good" />
            <Block icon={AlertTriangle} accent="enemy" title="HIBÁK" items={data.weaknesses} mark="–" markCls="text-bad" />
            <Block icon={Lightbulb} accent="accent" title="JAVASLATOK" items={data.tips} mark="›" markCls="text-accent" />
          </div>
        )}
      </div>
    </div>
  );
}
