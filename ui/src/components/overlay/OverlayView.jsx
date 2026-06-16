import { Trophy, Zap } from "lucide-react";
import { ROLE_LABELS } from "../../assets.js";
import { useOverlayState } from "../../hooks/useOverlayState.js";
import MissionCard from "./MissionCard.jsx";

/* Minimal in-game overlay: 1–2 active missions + a slim progression footer.
   Designed to sit in a screen corner / OBS browser source. */
export default function OverlayView() {
  const { active, role, missions, profile, championProgress } = useOverlayState();

  return (
    <div className="w-[300px] select-none p-2 font-tech">
      <div className="mb-1.5 flex items-center gap-1.5 px-1">
        <Zap className="h-3.5 w-3.5 text-accent" />
        <span className="font-display text-[11px] font-bold tracking-[0.25em] text-white/70">
          SYLQON COACH
        </span>
        {role && (
          <span className="ml-auto text-[10px] font-bold tracking-widest text-white/35">
            {ROLE_LABELS[role] || role}
          </span>
        )}
      </div>

      {!active && missions.length === 0 ? (
        <div className="rounded-lg border border-white/10 bg-black/40 px-3 py-3 text-center text-[12px] text-white/40 backdrop-blur-sm">
          Waiting for a game…
        </div>
      ) : (
        <div className="flex flex-col gap-2">
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
