import { useState, useEffect, useRef } from "react";
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
            className={`flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1 text-sm font-bold tracking-wide transition-colors
              ${on ? "bg-accent/18 text-accent-bright" : "text-white/50 hover:bg-white/5 hover:text-white/80"}`}>
            <t.icon className="h-4 w-4" />
            {t.label}
            {t.live && <span className="h-2 w-2 rounded-full bg-bad pulse-soft" title="live game" />}
            {t.badge != null && (
              <span className="rounded-full bg-white/10 px-1.5 text-2xs font-mono text-white/60">{t.badge}</span>
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
  // A live game forces the in-game cockpit even if we never saw champ select
  // (e.g. the backend was started mid-game, or the lobby was cleared) — the live
  // board only needs live + scout state, not a captured lobby.
  if (state?.lcu?.phase === "InProgress" || state?.live?.active) return "postlock";
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

  // ------------------------------------------------------------------ debug
  const prevPhase = useRef(null);
  const prevLiveActive = useRef(null);
  const prevMode = useRef(null);
  const prevIsInGame = useRef(null);

  useEffect(() => {
    if (!state) return;
    const phase = state?.lcu?.phase ?? null;
    const liveActive = state?.live?.active ?? false;
    const liveGameTime = state?.live?.game_time ?? 0;

    if (phase !== prevPhase.current) {
      console.log(
        `%c[Sylqon] LCU phase: ${prevPhase.current ?? "(none)"} → ${phase}`,
        "color: #7dd3fc; font-weight: bold"
      );
      prevPhase.current = phase;
    }

    if (liveActive !== prevLiveActive.current) {
      console.log(
        `%c[Sylqon] live.active: ${prevLiveActive.current ?? "(none)"} → ${liveActive}` +
        (liveActive ? ` (game_time: ${liveGameTime.toFixed(1)}s)` : ""),
        liveActive ? "color: #4ade80; font-weight: bold" : "color: #f87171; font-weight: bold"
      );
      prevLiveActive.current = liveActive;
    }

    if (mode !== prevMode.current) {
      console.log(
        `%c[Sylqon] mode: ${prevMode.current ?? "(none)"} → ${mode}`,
        "color: #e879f9; font-weight: bold"
      );
      prevMode.current = mode;
    }

    if (isInGame !== prevIsInGame.current) {
      console.log(
        `%c[Sylqon] isInGame: ${prevIsInGame.current ?? "(none)"} → ${isInGame}` +
        ` (phase=${phase}, live.active=${liveActive})`,
        isInGame ? "color: #fbbf24; font-weight: bold" : "color: #94a3b8; font-weight: bold"
      );
      prevIsInGame.current = isInGame;
    }
  }, [state, mode, isInGame]);
  // ---------------------------------------------------------------- /debug

  // Auto-focus the live board when a game is in progress, so the dashboard lands
  // on it without a click. Only switches once per game — the user can still flip
  // back to Loadout and it won't yank them away again.
  const autoFocusedLive = useRef(false);
  useEffect(() => {
    if (isInGame && !autoFocusedLive.current) {
      setPostlockView("players");
      autoFocusedLive.current = true;
    } else if (!isInGame) {
      autoFocusedLive.current = false;
    }
  }, [isInGame]);

  return (
    <div className="app-shell relative h-screen w-screen overflow-hidden">
      <div className="flex h-full w-full flex-col gap-3 p-4">
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
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-md border border-accent/45 bg-bg-2/95 px-4 py-1.5 text-xs font-bold tracking-wide text-accent-bright">
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
