import { useEffect, useState } from "react";
import { Brain, Minus, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { fetchMacroCoach, refreshMacroCoach } from "../api.js";
import { pct } from "../assets.js";
import { Chip, Panel } from "./shared.jsx";

/* score (0-100) -> flat stroke / text colour, shared by the ring and the bars. */
function scoreColor(v) {
  return v >= 70 ? "var(--color-good)" : v >= 50 ? "var(--color-accent)" : "var(--color-amber)";
}

function TrendArrow({ trend }) {
  const dir = trend?.dir || "flat";
  const Icon = dir === "up" ? TrendingUp : dir === "down" ? TrendingDown : Minus;
  const cls = dir === "up" ? "text-good" : dir === "down" ? "text-bad" : "text-white/35";
  return (
    <span className={`flex items-center gap-0.5 ${cls}`} title={`Trend: ${trend?.delta > 0 ? "+" : ""}${trend?.delta ?? 0} pont`}>
      <Icon className="h-3.5 w-3.5" />
    </span>
  );
}

function OverallRing({ value, trend }) {
  const v = Math.round(value ?? 0);
  const r = 26, c = 2 * Math.PI * r;
  const stroke = scoreColor(v);
  return (
    <div className="relative grid shrink-0 place-items-center">
      <svg width="68" height="68" className="-rotate-90">
        <circle cx="34" cy="34" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
        <circle cx="34" cy="34" r={r} fill="none" stroke={stroke} strokeWidth="5" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} />
      </svg>
      <div className="absolute flex flex-col items-center leading-none">
        <span className="font-display text-xl font-extrabold" style={{ color: stroke }}>{v}</span>
        <span className="text-3xs tracking-[0.15em] text-white/40">FORMA</span>
      </div>
    </div>
  );
}

function DimBar({ d }) {
  const v = Math.max(0, Math.min(100, d.score ?? 0));
  return (
    <div className="flex items-center gap-2">
      <span className="w-[3.75rem] shrink-0 text-xs text-white/55">{d.label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full" style={{ width: `${v}%`, background: scoreColor(v) }} />
      </div>
      <span className="w-12 shrink-0 text-right font-mono text-2xs tabular-nums text-white/45"
            title={`${d.value} ${d.unit}`}>{d.value}</span>
      <TrendArrow trend={d.trend} />
    </div>
  );
}

function ResultPips({ results }) {
  if (!results?.length) return null;
  return (
    <div className="flex gap-0.5">
      {results.slice(0, 10).map((r, i) => (
        <span key={i} title={r === "W" ? "Győzelem" : "Vereség"}
              className={`h-3 w-3 rounded-sm text-[8px] font-extrabold leading-3 text-center
                ${r === "W" ? "bg-good/20 text-good" : "bg-bad/20 text-bad"}`}>{r}</span>
      ))}
    </div>
  );
}

export default function MacroCoach() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => fetchMacroCoach()
      .then((r) => { if (!cancelled) setData(r); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    load();
    const t = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try { setData(await refreshMacroCoach()); } catch { /* ignore */ }
    finally { setRefreshing(false); }
  };

  const sc = data?.scorecard;
  const games = sc?.games_analyzed ?? 0;
  const header = (
    <div className="flex items-center gap-2">
      <Chip tone="muted">{games} meccs</Chip>
      <button onClick={refresh} disabled={refreshing || loading || sc?.insufficient}
              title="Prioritások újragenerálása"
              className="grid h-6 w-6 place-items-center rounded-md border border-white/12 text-white/45
                         transition-colors hover:border-accent/50 hover:text-accent
                         disabled:cursor-default disabled:opacity-40">
        <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
      </button>
    </div>
  );

  return (
    <Panel title="AI MACRO COACH" icon={Brain} accent="accent" right={header} className="shrink-0">
      {loading ? (
        <div className="flex h-[5.5rem] items-center gap-3">
          <div className="h-16 w-16 shrink-0 animate-pulse rounded-full bg-white/5" />
          <div className="flex-1 space-y-2"><div className="h-3 w-2/3 animate-pulse rounded bg-white/5" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-white/5" /></div>
        </div>
      ) : !sc || games === 0 ? (
        <div className="flex h-[5.5rem] flex-col items-center justify-center gap-1 text-white/35">
          <span className="font-display text-sm tracking-[0.18em]">NINCS ELÉG JÁTÉK</span>
          <span className="text-xs text-white/30">Csatlakoztasd a klienst — a coach a Summoner's Rift meccsekből épül.</span>
        </div>
      ) : (
        <div className="flex items-stretch gap-4">
          {/* overall */}
          <div className="flex shrink-0 flex-col items-center justify-center gap-1.5 px-1">
            <OverallRing value={sc.overall} trend={sc.overall_trend} />
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-sm font-bold tabular-nums text-white/70">{pct(sc.win_rate)}</span>
              <TrendArrow trend={sc.overall_trend} />
            </div>
            <ResultPips results={sc.recent_results} />
          </div>

          {/* priorities */}
          <div className="min-w-0 flex-1 border-l border-white/8 pl-4">
            <div className="t-label text-accent/70">A 3 DOLOG, AMIN JAVÍTS</div>
            {data.priorities_available && data.priorities?.length > 0 ? (
              <ol className="mt-1.5 space-y-1">
                {data.priorities.map((p, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="font-display text-sm font-extrabold text-accent/80">{i + 1}</span>
                    <span className="min-w-0">
                      <span className="text-sm font-bold text-white/85">{p.title}</span>
                      {p.detail && <span className="ml-1.5 text-xs leading-snug text-white/55 line-clamp-1">{p.detail}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-2 text-xs leading-snug text-white/40">
                {sc.insufficient
                  ? "Néhány meccs után a coach kiemeli a 3 legfontosabb fejlesztési pontot."
                  : "Az Ollama jelenleg offline — a pontszámok elérhetők, a prioritások nem generálhatók."}
              </p>
            )}
            {data.narrative && (
              <p className="mt-1.5 border-t border-white/8 pt-1.5 text-xs leading-snug text-white/50 line-clamp-2">{data.narrative}</p>
            )}
          </div>

          {/* dimensions */}
          <div className="flex w-[19rem] shrink-0 flex-col justify-center gap-1.5 border-l border-white/8 pl-4">
            {(sc.dimensions || []).map((d) => <DimBar key={d.key} d={d} />)}
          </div>
        </div>
      )}
    </Panel>
  );
}
