import { useState } from "react";
import { Play, Sparkles, Target } from "lucide-react";
import { ChampPortrait, Button, Chip } from "./shared.jsx";

/* Turns the coach's weakest dimension into one concrete number to hit this game.
   Deterministic (see analysis/macro_coach.derive_goal), so the CTA still says
   something useful when Ollama is offline. */
function goalText(goal) {
  if (!goal) return null;
  if (goal.target == null) {
    return `Lift ${goal.label.toLowerCase()} from ${goal.current_score} to ${goal.target_score}`;
  }
  // The raw average carries more precision than a coaching line should show —
  // match the target's precision so "6.345 → 7.8" reads as "6.3 → 7.8".
  const decimals = String(goal.target).split(".")[1]?.length ?? 0;
  const current = Number(goal.current).toFixed(decimals);
  const dir = goal.key === "survival" ? "Drop to" : "Hit";
  return `${dir} ${goal.target} ${goal.unit} (you average ${current})`;
}

/* The Home's single primary action. Everything above it reports on the past;
   this is the one element that points at the next game. */
export default function NextMatchBar({ goal, priority, scout, patch, clientConnected, role }) {
  const [launch, setLaunch] = useState(null); // null | "starting" | "not-found" | "error"
  const canLaunch = typeof window !== "undefined" && !!window.sylqon?.launchLeague;

  const start = async () => {
    setLaunch("starting");
    const res = await window.sylqon.launchLeague();
    setLaunch(res?.ok ? "starting" : res?.reason === "not-found" ? "not-found" : "error");
  };

  const target = goalText(goal);
  // Priority title is the LLM's framing of the same weakness; when it exists it
  // reads better than the raw dimension name.
  const headline = priority?.title || goal?.label || "Play your next game";

  return (
    <div className="surface edge-accent flex shrink-0 items-center gap-4 px-3 py-2">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Target className="h-5 w-5 shrink-0 text-accent" />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="t-label text-accent/70">THIS GAME</span>
            {goal && <Chip tone="muted">{goal.label}</Chip>}
          </div>
          <div className="truncate font-display text-md font-bold text-white/90">{headline}</div>
          <div className="truncate text-xs text-white/50">
            {target || "Play a few games and the coach will set you a concrete target."}
          </div>
        </div>
      </div>

      {scout?.pick && (
        <div className="flex shrink-0 items-center gap-2 border-l border-line pl-4"
             title={scout.reason || `Suggested ${role} pick from your pool`}>
          <ChampPortrait slug={scout.slug} patch={patch} size="h-10 w-10" accent="accent" round
                         title={scout.pick} />
          <div className="leading-tight">
            <div className="flex items-center gap-1">
              <Sparkles className="h-3 w-3 text-accent" />
              <span className="t-label text-white/40">SUGGESTED</span>
            </div>
            <div className="font-display text-sm font-bold text-accent-bright">{scout.pick}</div>
          </div>
        </div>
      )}

      <div className="flex shrink-0 flex-col items-end gap-0.5 border-l border-line pl-4">
        {clientConnected ? (
          <Chip tone="good">CLIENT READY</Chip>
        ) : canLaunch ? (
          <Button variant="primary" icon={Play} onClick={start} disabled={launch === "starting"}>
            {launch === "starting" ? "Starting…" : "Launch League"}
          </Button>
        ) : (
          <Chip tone="muted">Start League to play</Chip>
        )}
        {launch === "not-found" && (
          <span className="text-2xs text-amber">Riot Client not found — start it manually.</span>
        )}
        {launch === "error" && (
          <span className="text-2xs text-bad">Could not start the client.</span>
        )}
      </div>
    </div>
  );
}
