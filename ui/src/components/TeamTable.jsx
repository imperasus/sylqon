import { useState } from "react";
import { Users } from "lucide-react";
import { SectionTitle } from "./shared.jsx";

/* Shared dense team-table primitive: PlayersView (lobby scout) and LiveBoard
   (in-game) render one row per player on the same grid so the header and the
   rows always line up. The last column is view-specific (BUILD / POOL /
   THREATS), everything else is fixed:
   Role | Player | Rank | WR | KDA | Flags | <last> */
export const TEAM_GRID =
  "grid grid-cols-[2.25rem_minmax(7rem,1.25fr)_minmax(4rem,0.85fr)_3.25rem_3.75rem_minmax(3.5rem,0.7fr)_minmax(9rem,1.2fr)] items-center gap-x-2";

export function TeamTable({ title, side = "ally", lastCol = "BUILD", right, className = "", children }) {
  const edge = side === "enemy" ? "edge-enemy" : "edge-ally";
  const tone = side === "enemy" ? "enemy" : "ally";
  return (
    <div className={`surface ${edge} flex min-h-0 flex-col ${className}`}>
      <div className="border-b border-line/70 px-2.5 py-1.5">
        <SectionTitle accent={tone} icon={Users} right={right}>{title}</SectionTitle>
      </div>
      <div className={`${TEAM_GRID} border-b border-line/70 px-2.5 py-1`}>
        <span className="t-label">Role</span>
        <span className="t-label">Player</span>
        <span className="t-label">Rank</span>
        <span className="t-label text-right">WR</span>
        <span className="t-label text-right">KDA</span>
        <span className="t-label">Flags</span>
        <span className="t-label">{lastCol}</span>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {children}
      </div>
    </div>
  );
}

/* One player row. `premade` is a party color (left bar), `self` tints the row,
   `dim` grays a dead / hidden player.

   Passing `detail` makes the row expandable: the deep read that used to live
   only in a hover tooltip (champion pool, averages, matchup reasoning) opens
   inline instead. Hover tooltips are unreachable mid-game and by keyboard, so
   the row takes button semantics — Enter/Space toggle it, and `aria-expanded`
   tells a screen reader what it does. */
export function TeamRow({ premade, self, dim, title, detail, children }) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(detail);
  const toggle = () => setOpen((v) => !v);
  const onKeyDown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  };
  return (
    <div className={`border-b border-line/40 last:border-b-0 even:bg-white/[0.015]
      ${self ? "bg-accent/[0.05]" : ""} ${dim ? "opacity-70" : ""}`}>
      <div
        title={title}
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? open : undefined}
        onClick={expandable ? toggle : undefined}
        onKeyDown={expandable ? onKeyDown : undefined}
        className={`${TEAM_GRID} relative px-2.5 py-1
          ${expandable ? "cursor-pointer hover:bg-white/[0.03] focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent/70" : ""}`}
      >
        {premade && <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: premade }} />}
        {children}
      </div>
      {expandable && open && (
        <div className="border-t border-line/40 bg-black/25 px-2.5 py-2">{detail}</div>
      )}
    </div>
  );
}

/* Pulsing placeholder for a cell whose deep read is still streaming in. Keeps
   the board's shape stable instead of flashing "—" and then real numbers. */
export function Skeleton({ className = "w-10" }) {
  return <span className={`inline-block h-2.5 animate-pulse rounded bg-white/10 ${className}`} />;
}

/* Small typed cell helpers so the two views stay visually identical. */
export function RoleCell({ role }) {
  return <span className="text-2xs font-bold tracking-wide text-white/45">{role || "—"}</span>;
}

export function RankCell({ rank, sub }) {
  return (
    <div className="min-w-0 leading-tight">
      {rank
        ? <div className="truncate text-2xs font-bold text-amber/85">{rank}</div>
        : <div className="text-2xs text-white/30">Unranked</div>}
      {sub && <div className="truncate font-mono text-3xs text-white/35">{sub}</div>}
    </div>
  );
}

/* `pending` renders a skeleton instead of the value — used while a player's deep
   stats are still streaming in, so the row doesn't flash "—" then real numbers. */
export function NumCell({ value, tone = "text-white/70", sub, subTone = "text-white/35",
                          title, pending }) {
  if (pending) {
    return <div className="min-w-0 text-right" title="scouting…"><Skeleton className="w-8" /></div>;
  }
  return (
    <div className="min-w-0 text-right leading-tight" title={title}>
      <div className={`font-mono text-2xs font-bold tabular-nums ${tone}`}>{value ?? "—"}</div>
      {sub != null && <div className={`font-mono text-3xs tabular-nums ${subTone}`}>{sub}</div>}
    </div>
  );
}
