import { Bar } from "../shared.jsx";

const STATUS = {
  active: { label: "ACTIVE", cls: "text-accent/80" },
  completed: { label: "DONE", cls: "text-good" },
  failed: { label: "FAILED", cls: "text-bad" },
};

/* One compact mission card: text, progress, status, reward. Built for a small
   corner overlay (semi-transparent, minimal chrome). */
export default function MissionCard({ mission }) {
  const st = STATUS[mission.status] || STATUS.active;
  const tone = mission.status === "completed" ? "good"
    : mission.status === "failed" ? "enemy" : "accent";
  return (
    <div className="rounded-lg border border-white/10 bg-black/45 px-3 py-2 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-3 text-[13px] font-semibold leading-snug text-white/90">{mission.text}</span>
        <span className={`mt-0.5 shrink-0 text-[10px] font-bold tracking-widest ${st.cls}`}>{st.label}</span>
      </div>
      <div className="mt-1.5"><Bar value={(mission.progress || 0) * 100} tone={tone} /></div>
      <div className="mt-1 flex items-center justify-between text-[11px]">
        <span className="truncate text-white/45">{mission.detail}</span>
        <span className="ml-2 shrink-0 font-mono font-bold text-accent/70">+{mission.reward_points}</span>
      </div>
    </div>
  );
}
