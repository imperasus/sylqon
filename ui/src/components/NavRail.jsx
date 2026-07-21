import { Home, Package, Play, Settings, Square, Swords, Users } from "lucide-react";
import BrandMark from "./BrandMark.jsx";
import { IconButton } from "./shared.jsx";

/* Global view switcher: jump between any page at any time. Smart-follow in
   App.jsx still auto-selects the phase-relevant view, but a manual click sticks
   until the next phase change. The Players item carries the live-game dot + the
   scouted-ally count. */
const NAV = [
  { key: "home", label: "Home", icon: Home },
  { key: "draft", label: "Draft", icon: Swords },
  { key: "loadout", label: "Loadout", icon: Package },
  { key: "players", label: "Players", icon: Users },
];

function RailItem({ item, on, onView, inGame, scouted }) {
  return (
    <button
      onClick={() => onView?.(item.key)}
      title={item.label}
      className={`relative grid h-10 w-10 cursor-pointer place-items-center rounded-md transition-colors
        ${on ? "bg-elev text-accent" : "text-white/40 hover:bg-white/5 hover:text-white/80"}`}
    >
      {on && <span className="absolute top-1.5 bottom-1.5 -left-1 w-0.5 rounded-full bg-accent" />}
      <item.icon className="h-4.5 w-4.5" />
      {item.key === "players" && inGame && (
        <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-bad pulse-soft" title="live game" />
      )}
      {item.key === "players" && scouted > 0 && (
        <span className="absolute -right-0.5 -bottom-0.5 rounded bg-white/10 px-1 font-mono text-3xs text-white/60">
          {scouted}
        </span>
      )}
    </button>
  );
}

export default function NavRail({ view, onView, scout, live, demoActive, onToggleDemo, onOpenSettings }) {
  const scouted = (scout?.players || []).filter((p) => !p.hidden && p.games_analyzed > 0).length;
  const inGame = !!live?.active;
  return (
    <nav className="flex h-full w-12 shrink-0 flex-col items-center gap-1 border-r border-line bg-bg-2 py-2.5">
      <div className="mb-2 grid h-10 w-10 place-items-center" title="Sylqon">
        <BrandMark className="h-5.5 w-5.5" />
      </div>
      {NAV.map((item) => (
        <RailItem key={item.key} item={item} on={item.key === view} onView={onView}
                  inGame={inGame} scouted={scouted} />
      ))}
      <div className="flex-1" />
      <IconButton
        icon={demoActive ? Square : Play}
        tone="amber"
        active={demoActive}
        title={demoActive ? "Stop demo" : "Start demo lobby"}
        onClick={onToggleDemo}
      />
      <IconButton icon={Settings} title="Settings" onClick={onOpenSettings} />
    </nav>
  );
}
