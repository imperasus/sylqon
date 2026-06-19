import { useState } from "react";
import { useSylqon } from "./api.js";
import StatusBar from "./components/StatusBar.jsx";
import HomeCockpit from "./components/HomeCockpit.jsx";
import DraftCockpit from "./components/DraftCockpit.jsx";
import PostlockCockpit from "./components/PostlockCockpit.jsx";
import MatchAnalysisModal from "./components/MatchAnalysisModal.jsx";

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

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[1560px] flex-col gap-3 p-4">
        <StatusBar state={state} mode={mode} act={act} api={api} demoActive={demoActive} />

        <main className="relative min-h-0 flex-1">
          {mode === "home" && <HomeCockpit state={state} act={act} api={api} />}
          {mode === "draft" && <DraftCockpit state={state} />}
          {mode === "postlock" && <PostlockCockpit state={state} act={act} api={api} />}
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
