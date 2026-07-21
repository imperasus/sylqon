import { Award, Brain, Flame, Minus, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { useMacroCoach } from "../api.js";
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
    <span className={`flex items-center gap-0.5 ${cls}`}
          title={`Trend: ${trend?.delta > 0 ? "+" : ""}${trend?.delta ?? 0} points`}>
      <Icon className="h-3.5 w-3.5" />
    </span>
  );
}

/* The headline movement read: "63 → 68 (+5)". This is the difference between a
   snapshot and a progress report, so it gets its own line rather than a tooltip.
   Renders nothing when the older window is too thin to compare against. */
function DeltaBadge({ progress }) {
  if (!progress?.available || progress.overall_delta == null) return null;
  const d = progress.overall_delta;
  const tone = d > 0 ? "text-good" : d < 0 ? "text-bad" : "text-white/40";
  const sign = d > 0 ? "+" : "";
  return (
    <span className={`font-mono text-xs font-bold tabular-nums ${tone}`}
          title={`Compared with the ${progress.compared_games} games before these`}>
      {progress.previous_overall} → {progress.previous_overall + d} ({sign}{d})
    </span>
  );
}

function OverallRing({ value, progress }) {
  const v = Math.round(value ?? 0);
  const r = 26, c = 2 * Math.PI * r;
  const stroke = scoreColor(v);
  // Where the score sat over the previous window — a faint tick on the same
  // track, so the movement is visible on the ring itself, not just in text.
  const prev = progress?.available ? progress.previous_overall : null;
  return (
    <div className="relative grid shrink-0 place-items-center">
      <svg width="68" height="68" className="-rotate-90">
        <circle cx="34" cy="34" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
        {prev != null && (
          <circle cx="34" cy="34" r={r} fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="5"
                  strokeDasharray={`2 ${c}`} strokeDashoffset={-c * (prev / 100)} />
        )}
        <circle cx="34" cy="34" r={r} fill="none" stroke={stroke} strokeWidth="5" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} />
      </svg>
      <div className="absolute flex flex-col items-center leading-none">
        <span className="font-display text-xl font-extrabold" style={{ color: stroke }}>{v}</span>
        <span className="text-3xs tracking-[0.15em] text-white/40">FORM</span>
      </div>
    </div>
  );
}

function DimBar({ d, movement }) {
  const v = Math.max(0, Math.min(100, d.score ?? 0));
  const prev = movement?.previous_score;
  const delta = movement?.delta;
  return (
    <div className="flex items-center gap-2">
      <span className="w-[3.75rem] shrink-0 text-xs text-white/55">{d.label}</span>
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full" style={{ width: `${v}%`, background: scoreColor(v) }} />
        {prev != null && (
          <span className="absolute top-0 bottom-0 w-px bg-white/45"
                style={{ left: `${Math.max(0, Math.min(100, prev))}%` }}
                title={`Previous window: ${prev}`} />
        )}
      </div>
      <span className="w-12 shrink-0 text-right font-mono text-2xs tabular-nums text-white/45"
            title={`${d.value} ${d.unit}`}>{d.value}</span>
      {delta != null && delta !== 0 ? (
        <span className={`w-7 shrink-0 text-right font-mono text-2xs font-bold tabular-nums
                          ${delta > 0 ? "text-good" : "text-bad"}`}
              title={`${delta > 0 ? "+" : ""}${delta} vs the previous window`}>
          {delta > 0 ? "+" : ""}{delta}
        </span>
      ) : (
        <span className="w-7 shrink-0 text-right"><TrendArrow trend={d.trend} /></span>
      )}
    </div>
  );
}

function ResultPips({ results }) {
  if (!results?.length) return null;
  return (
    <div className="flex gap-0.5">
      {results.slice(0, 10).map((r, i) => (
        <span key={i} title={r === "W" ? "Win" : "Loss"}
              className={`h-3 w-3 rounded-sm text-[8px] font-extrabold leading-3 text-center
                ${r === "W" ? "bg-good/20 text-good" : "bg-bad/20 text-bad"}`}>{r}</span>
      ))}
    </div>
  );
}

/* Account progression (level, points into level, streak, badges). The data has
   existed since the overlay shipped; surfacing it here is what makes the Home
   show accumulation between games rather than a standalone score. */
function ProgressionChip({ progression }) {
  if (!progression?.available) return null;
  const into = progression.points_into_level ?? 0;
  const streak = progression.streak ?? 0;
  const badges = progression.badges?.length ?? 0;
  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1.5" title={`${progression.total_points} mission points total`}>
        <span className="font-display text-xs font-bold tracking-wide text-accent-bright">
          LVL {progression.level}
        </span>
        <span className="h-1 w-10 overflow-hidden rounded-full bg-white/10">
          <span className="block h-full rounded-full bg-accent" style={{ width: `${into}%` }} />
        </span>
        <span className="font-mono text-2xs tabular-nums text-white/35">{into}/100</span>
      </span>
      {streak > 0 && (
        <span className="flex items-center gap-0.5 text-amber" title={`${streak} missions completed in a row`}>
          <Flame className="h-3.5 w-3.5" />
          <span className="font-mono text-2xs font-bold tabular-nums">{streak}</span>
        </span>
      )}
      {badges > 0 && (
        <span className="flex items-center gap-0.5 text-white/45"
              title={progression.badges.map((b) => b.label).join("\n")}>
          <Award className="h-3.5 w-3.5" />
          <span className="font-mono text-2xs font-bold tabular-nums">{badges}</span>
        </span>
      )}
    </div>
  );
}

export default function MacroCoach() {
  const { coach, loading, refreshing, refresh } = useMacroCoach();

  const sc = coach?.scorecard;
  const progress = coach?.progress;
  const games = sc?.games_analyzed ?? 0;
  const movement = progress?.dimensions || {};

  // Scores are graded against the player's own rank band, so name the band —
  // an ungraded "62/100" invites the wrong comparison.
  const band = coach?.rank_band?.replace(/_/g, " ");

  const header = (
    <div className="flex items-center gap-2.5">
      <ProgressionChip progression={coach?.progression} />
      {band && (
        <Chip tone={coach.rank_known ? "accent" : "muted"}
              title={coach.rank_known
                ? `Scored against ${band} benchmarks for your role`
                : `Rank unknown — scored against the default ${band} band`}>
          vs {band}
        </Chip>
      )}
      <Chip tone="muted">{games} games</Chip>
      <button onClick={() => refresh()} disabled={refreshing || loading || sc?.insufficient}
              title="Regenerate the priorities"
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
          <span className="font-display text-sm tracking-[0.18em]">NOT ENOUGH GAMES</span>
          <span className="text-xs text-white/30">Connect the client — the coach is built from your Summoner's Rift games.</span>
        </div>
      ) : (
        <div className="flex items-stretch gap-4">
          {/* overall */}
          <div className="flex shrink-0 flex-col items-center justify-center gap-1.5 px-1">
            <OverallRing value={sc.overall} progress={progress} />
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-sm font-bold tabular-nums text-white/70">{pct(sc.win_rate)}</span>
              <TrendArrow trend={sc.overall_trend} />
            </div>
            <DeltaBadge progress={progress} />
            <ResultPips results={sc.recent_results} />
          </div>

          {/* priorities */}
          <div className="min-w-0 flex-1 border-l border-white/8 pl-4">
            <div className="t-label text-accent/70">THE 3 THINGS TO FIX</div>
            {coach.priorities_available && coach.priorities?.length > 0 ? (
              <ol className="mt-1.5 space-y-1">
                {coach.priorities.map((p, i) => (
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
                  ? "After a few more games the coach will name your 3 biggest improvement areas."
                  : "Ollama is offline — the scores are available, the priorities cannot be generated."}
              </p>
            )}
            {coach.narrative && (
              <p className="mt-1.5 border-t border-white/8 pt-1.5 text-xs leading-snug text-white/50 line-clamp-2">{coach.narrative}</p>
            )}
          </div>

          {/* dimensions */}
          <div className="flex w-[21rem] shrink-0 flex-col justify-center gap-1.5 border-l border-white/8 pl-4">
            {(sc.dimensions || []).map((d) => (
              <DimBar key={d.key} d={d} movement={movement[d.key]} />
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
