import { useState } from "react";
import { Swords, Users } from "lucide-react";
import { useSylqon } from "./api.js";
import StatusBar from "./components/StatusBar.jsx";
import HomeCockpit from "./components/HomeCockpit.jsx";
import DraftCockpit from "./components/DraftCockpit.jsx";
import PostlockCockpit from "./components/PostlockCockpit.jsx";
import PlayersView from "./components/PlayersView.jsx";
import LiveBoard from "./components/LiveBoard.jsx";
import MatchAnalysisModal from "./components/MatchAnalysisModal.jsx";

/* Loadout ↔ Players toggle for the post-lock / in-game phase. The Players view
   surfaces the lobby scout pre-game, then becomes the full 10-player live board
   once the game loads (a live dot flags that it's showing live data). */
function PostlockTabs({ view, onChange, scout, live }) {
  const scouted = (scout?.players || []).filter((p) => !p.hidden && p.games_analyzed > 0).length;
  const inGame = !!live?.active;
  const tabs = [
    { key: "loadout", label: "Loadout", icon: Swords },
    { key: "players", label: "Players", icon: Users, badge: scouted || null, live: inGame },
  ];
  return (
    <div className="frost flex w-fit items-center gap-1 px-1.5 py-1">
      {tabs.map((t) => {
        const on = t.key === view;
        return (
          <button key={t.key} onClick={() => onChange(t.key)}
            className={`flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1 text-[12px] font-bold tracking-wide transition-colors
              ${on ? "bg-accent/18 text-accent-bright" : "text-white/50 hover:bg-white/5 hover:text-white/80"}`}>
            <t.icon className="h-4 w-4" />
            {t.label}
            {t.live && <span className="h-2 w-2 rounded-full bg-bad pulse-soft" title="live game" />}
            {t.badge != null && (
              <span className="rounded-full bg-white/10 px-1.5 text-[10px] font-mono text-white/60">{t.badge}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* Single-screen cockpit: the body is driven purely by the live phase — no tabs.
   Idle → Home, champ select → Draft, locked/injected → Postlock. */
function deriveMode(state) {
  const lobby = state?.lobby;
  if (!lobby) return "home";
  const injected = state?.injection?.status === "ok";
  return lobby.all_locked || injected ? "postlock" : "draft";
}

export default function App() {
  const api = useSylqon();
  const { state } = api;
  const mode = deriveMode(state);
  const demoActive = !!state?.demo;
  const [postlockView, setPostlockView] = useState("loadout");

  const [toast, setToast] = useState("");
  const act = async (fn) => {
    const res = await fn();
    if (res?.detail) {
      setToast(res.detail);
      setTimeout(() => setToast(""), 3500);
    }
    return res;
  };

  // Auto post-game review: pop the analysis modal once per finished game. The
  // backend generates + caches it on the end-of-game event; here we just surface
  // it, and remember the dismissed game so it doesn't reopen on the next poll.
  const postGame = state?.post_game?.active ? state.post_game : null;
  const pgMatch = postGame?.match;
  const [dismissedGame, setDismissedGame] = useState(null);
  const showPostGame = pgMatch?.id != null && pgMatch.game_id !== dismissedGame;

  // Show the LiveBoard as soon as the LCU phase is InProgress — the Live Client
  // Data API (port 2999) may take a few seconds to respond after the game starts,
  // so relying solely on live.active would delay the switch unnecessarily.
  const isInGame = state?.lcu?.phase === "InProgress" || state?.live?.active;

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[1280px] flex-col gap-3 p-4">
        <StatusBar state={state} mode={mode} act={act} api={api} demoActive={demoActive} />

        <main className="relative min-h-0 flex-1">
          {mode === "home" && <HomeCockpit state={state} act={act} api={api} />}
          {mode === "draft" && <DraftCockpit state={state} />}
          {mode === "postlock" && (
            <div className="flex h-full min-h-0 flex-col gap-2.5">
              <PostlockTabs view={postlockView} onChange={setPostlockView} scout={state?.scout} live={state?.live} />
              <div className="min-h-0 flex-1">
                {postlockView === "loadout"
                  ? <PostlockCockpit state={state} act={act} api={api} />
                  : isInGame
                    ? <LiveBoard scout={state?.scout} live={state.live} patch={state?.cache?.patch || "16.12.1"} />
                    : <PlayersView state={state} />}
              </div>
            </div>
          )}
        </main>
      </div>

      {toast && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-md border border-accent/45 bg-bg-2/95 px-4 py-1.5 text-[11px] font-bold tracking-wide text-accent-bright">
          {toast}
        </div>
      )}

      {showPostGame && (
        <MatchAnalysisModal
          match={pgMatch}
          patch={state?.cache?.patch || "16.12.1"}
          onClose={() => setDismissedGame(pgMatch.game_id)}
        />
      )}
    </div>
  );
}
