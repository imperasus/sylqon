import { useState, useEffect, useRef } from "react";
import { Package, Swords, Users } from "lucide-react";
import { useSylqon, debugEnabled } from "./api.js";
import NavRail from "./components/NavRail.jsx";
import StatusStrip from "./components/StatusStrip.jsx";
import HomeCockpit from "./components/HomeCockpit.jsx";
import DraftCockpit from "./components/DraftCockpit.jsx";
import PostlockCockpit from "./components/PostlockCockpit.jsx";
import PlayersView from "./components/PlayersView.jsx";
import LiveBoard from "./components/LiveBoard.jsx";
import MatchAnalysisModal from "./components/MatchAnalysisModal.jsx";
import SettingsModal from "./components/SettingsModal.jsx";
import { EmptyState } from "./components/shared.jsx";

/* The live phase still drives a "natural" view, but a global nav (NavRail)
   now lets the user jump to any page at any time. `deriveMode` feeds the phase
   badge; `naturalView` maps the phase onto the four nav items for smart-follow. */
function deriveMode(state) {
  // A live game forces the in-game cockpit even if we never saw champ select
  // (e.g. the backend was started mid-game, or the lobby was cleared).
  if (state?.lcu?.phase === "InProgress" || state?.live?.active) return "postlock";
  const lobby = state?.lobby;
  if (!lobby) return "home";
  const injected = state?.injection?.status === "ok";
  return lobby.all_locked || injected ? "postlock" : "draft";
}

/* The phase-relevant nav tab. Smart-follow selects this on every real phase
   change; a manual tab click overrides it until the next change. */
function naturalView(state) {
  if (!state) return "home";
  if (state?.lcu?.phase === "InProgress" || state?.live?.active) return "players";
  const lobby = state?.lobby;
  if (!lobby) return "home";
  const injected = state?.injection?.status === "ok";
  return lobby.all_locked || injected ? "loadout" : "draft";
}

export default function App() {
  const api = useSylqon();
  const { state } = api;
  const mode = deriveMode(state);
  const demoActive = !!state?.demo;

  // Currently displayed page. Driven by smart-follow below, overridable from the
  // global nav (NavRail → onView).
  const [view, setView] = useState("home");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [toast, setToast] = useState("");
  const act = async (fn) => {
    const res = await fn();
    // Surface both success details and action errors (previously errors from a
    // failed POST were swallowed and only the state silently refreshed).
    const msg = res?.detail || (res?.error ? `Hiba: ${res.error}` : "");
    if (msg) {
      setToast(msg);
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
  // Data API (port 2999) may take a few seconds to respond after the game starts.
  const isInGame = state?.lcu?.phase === "InProgress" || state?.live?.active;

  // ------------------------------------------------------------------ debug
  const prevPhase = useRef(null);
  const prevLiveActive = useRef(null);
  const prevMode = useRef(null);
  const prevIsInGame = useRef(null);

  useEffect(() => {
    if (!state || !debugEnabled()) return; // verbose state-log only with ?debug=1
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

  // Smart-follow: auto-switch to the phase-relevant view on every real phase
  // change, but keep a manual selection in place between changes (we only act on
  // the phase *edge*, so clicking another tab is never yanked away by a poll).
  const lastPhase = useRef(null);
  useEffect(() => {
    if (!state) return;
    const nv = naturalView(state);
    if (nv !== lastPhase.current) {
      lastPhase.current = nv;
      setView(nv);
    }
  }, [state]);

  const patch = state?.cache?.patch || "16.12.1";

  // Each page renders its live data when available, otherwise a calm empty state
  // (the views are now reachable out of phase, so they must not assume data).
  const renderView = () => {
    switch (view) {
      case "draft":
        return state?.lobby
          ? <DraftCockpit state={state} />
          : <EmptyState icon={Swords} label="NINCS DRAFT"
                        hint="A draft board akkor jelenik meg, amikor elindul a champion select." />;
      case "loadout":
        return (state?.build || state?.lobby?.my_champion)
          ? <PostlockCockpit state={state} act={act} api={api} />
          : <EmptyState icon={Package} label="NINCS LOADOUT"
                        hint="A végleges build a bajnok lockolása után jelenik meg." />;
      case "players":
        if (isInGame) return <LiveBoard scout={state?.scout} live={state.live} matchups={state?.matchups}
                                       callouts={state?.callouts} patch={patch} />;
        // The tab carries draft-derived intel (lane matchups, coaching callouts,
        // enemy picks) even before any player fingerprint resolves, so a live
        // lobby is enough to render it — PlayersView handles the thinner states.
        return (state?.scout?.players?.length || state?.lobby)
          ? <PlayersView state={state} />
          : <EmptyState icon={Users} label="NINCS LOBBY ADAT"
                        hint="A 10 játékos scoutja a lobby/meccs során töltődik fel." />;
      case "home":
      default:
        return <HomeCockpit state={state} act={act} api={api} />;
    }
  };

  return (
    <div className="app-shell relative flex h-screen w-screen overflow-hidden">
      <NavRail
        view={view} onView={setView} scout={state?.scout} live={state?.live}
        demoActive={demoActive}
        onToggleDemo={() => act?.(() => (demoActive ? api.stopDemo() : api.startDemo()))}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <StatusStrip state={state} mode={mode} api={api} />
        <main className="relative min-h-0 flex-1 p-3">
          {renderView()}
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
          patch={patch}
          onClose={() => setDismissedGame(pgMatch.game_id)}
        />
      )}

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
