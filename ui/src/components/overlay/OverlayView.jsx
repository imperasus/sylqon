import { Crown, Flame, Trophy, Zap } from "lucide-react";
import { ROLE_LABELS } from "../../assets.js";
import { useOverlayState } from "../../hooks/useOverlayState.js";
import MissionCard from "./MissionCard.jsx";

const fmtClock = (s) => {
  const t = Math.max(0, Math.floor(s || 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};
const fmtTimer = (s) => (s != null && s <= 0 ? "UP" : fmtClock(s));

const CS_TONE = { ahead: "text-good", behind: "text-bad", "on-track": "text-white/70" };

/* Compact live readout: CS-vs-target, level diff, KDA — all from the read-only
   Live Client Data snapshot the coach already polls. */
function Benchmark({ game }) {
  const b = game.cs_benchmark || {};
  const ld = game.level_diff || 0;
  return (
    <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-white/10 bg-black/45 px-2.5 py-1.5 text-[11px] backdrop-blur-sm">
      <div className="flex flex-col">
        <span className="text-[9px] tracking-widest text-white/35">CS/MIN</span>
        <span className={CS_TONE[b.status] || "text-white/70"}>
          {game.cs_per_min ?? 0}<span className="text-white/30"> /{b.target ?? "—"}</span>
        </span>
      </div>
      <div className="flex flex-col">
        <span className="text-[9px] tracking-widest text-white/35">LEVEL</span>
        <span className="text-white/80">
          {game.level || 0}
          {ld !== 0 && <span className={ld > 0 ? "text-good" : "text-bad"}> {ld > 0 ? "+" : ""}{ld}</span>}
        </span>
      </div>
      <div className="flex flex-col">
        <span className="text-[9px] tracking-widest text-white/35">KDA</span>
        <span className="font-mono text-white/80">{game.kills ?? 0}/{game.deaths ?? 0}/{game.assists ?? 0}</span>
      </div>
    </div>
  );
}

function Objectives({ timers }) {
  const dragon = timers?.dragon;
  const baron = timers?.baron;
  if (dragon == null && baron == null) return null;
  return (
    <div className="flex gap-1.5">
      <div className="flex flex-1 items-center gap-2 rounded-lg border border-white/10 bg-black/45 px-2.5 py-1.5 backdrop-blur-sm">
        <Flame className="h-4 w-4 shrink-0 text-mana" />
        <div className="leading-tight">
          <div className="text-[9px] tracking-widest text-white/35">DRAGON</div>
          <div className={`font-mono text-[12px] font-bold ${dragon <= 0 ? "text-good" : "text-white/85"}`}>{fmtTimer(dragon)}</div>
        </div>
      </div>
      <div className="flex flex-1 items-center gap-2 rounded-lg border border-white/10 bg-black/45 px-2.5 py-1.5 backdrop-blur-sm">
        <Crown className="h-4 w-4 shrink-0 text-violet-300" />
        <div className="leading-tight">
          <div className="text-[9px] tracking-widest text-white/35">BARON</div>
          <div className={`font-mono text-[12px] font-bold ${baron <= 0 ? "text-good" : "text-white/85"}`}>{fmtTimer(baron)}</div>
        </div>
      </div>
    </div>
  );
}

/* Minimal in-game overlay: live readout + 1–2 active missions + a slim
   progression footer. Designed to sit in a screen corner / OBS browser source. */
export default function OverlayView() {
  const { active, role, missions, profile, championProgress, game } = useOverlayState();
  const inGame = active && (game?.game_time || 0) > 0;

  return (
    <div className="w-[300px] select-none p-2 font-tech">
      <div className="mb-1.5 flex items-center gap-1.5 px-1">
        <Zap className="h-3.5 w-3.5 text-accent" />
        <span className="font-display text-[11px] font-bold tracking-[0.25em] text-white/70">
          SYLQON COACH
        </span>
        {inGame
          ? <span className="ml-auto font-mono text-[10px] font-bold tracking-wide text-white/45">{fmtClock(game.game_time)}</span>
          : role && <span className="ml-auto text-[10px] font-bold tracking-widest text-white/35">{ROLE_LABELS[role] || role}</span>}
      </div>

      {!active && missions.length === 0 ? (
        <div className="rounded-lg border border-white/10 bg-black/40 px-3 py-3 text-center text-[12px] text-white/40 backdrop-blur-sm">
          Waiting for a game…
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {inGame && <Benchmark game={game} />}
          {inGame && <Objectives timers={game.objective_timers} />}
          {missions.map((m) => <MissionCard key={m.id} mission={m} />)}
        </div>
      )}

      {championProgress?.champion && (
        <div className="mt-2 rounded-lg border border-accent/20 bg-black/45 px-3 py-1.5 text-[11px] backdrop-blur-sm">
          <div className="flex items-center gap-2 font-bold text-white/85">
            <span className="truncate">{championProgress.champion}</span>
            <span className="ml-auto flex items-center gap-1 text-accent">
              <Zap className="h-3 w-3" /> Lv {championProgress.level}
            </span>
          </div>
          {/* progress into the current champion level (0–99 of 100 pts) */}
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-accent/70"
                 style={{ width: `${championProgress.points_into_level}%` }} />
          </div>
        </div>
      )}

      {profile && (
        <div className="mt-2 flex items-center gap-3 rounded-lg border border-white/10 bg-black/45 px-3 py-1.5 text-[11px] backdrop-blur-sm">
          <span className="flex items-center gap-1 font-bold text-white/80">
            <Trophy className="h-3.5 w-3.5 text-amber" /> Lv {profile.level}
          </span>
          <span className="font-mono text-white/50">{profile.total_points} pts</span>
          {profile.badges?.length > 0 && (
            <span className="ml-auto truncate text-accent/75" title={profile.badges.map((b) => b.label).join(", ")}>
              {profile.badges[profile.badges.length - 1].label}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
