import { useState } from "react";
import { Crown, Flame, Trophy, Volume2, VolumeX, Zap } from "lucide-react";
import { ROLE_LABELS } from "../../assets.js";
import { useOverlayState } from "../../hooks/useOverlayState.js";
import { useCoachSpeech } from "../../hooks/useCoachSpeech.js";
import { speechSupported } from "./speech.js";
import MissionCard from "./MissionCard.jsx";

const VOICE_KEY = "sylqon.coach.voice";

const fmtClock = (s) => {
  const t = Math.max(0, Math.floor(s || 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};
const fmtTimer = (s) => (s != null && s <= 0 ? "UP" : fmtClock(s));

const CS_TONE = { ahead: "text-good", behind: "text-bad", "on-track": "text-white/70" };

/* Compact live readout: CS-vs-target, level diff, KDA — all from the read-only
   Live Client Data snapshot the coach already polls. */
const SPIKE_TONE = { ahead: "text-good", behind: "text-bad", even: "text-white/70" };

function Benchmark({ game }) {
  const b = game.cs_benchmark || {};
  const ld = game.level_diff || 0;
  const spike = game.item_spike || {};
  const hasSpike = !!spike.status;
  return (
    <div className={`grid ${hasSpike ? "grid-cols-4" : "grid-cols-3"} gap-1.5 rounded-lg border border-white/10 bg-black/45 px-2.5 py-1.5 text-xs backdrop-blur-sm`}>
      <div className="flex flex-col">
        <span className="text-3xs tracking-widest text-white/35">CS/MIN</span>
        <span className={CS_TONE[b.status] || "text-white/70"}>
          {game.cs_per_min ?? 0}<span className="text-white/30"> /{b.target ?? "—"}</span>
        </span>
      </div>
      <div className="flex flex-col">
        <span className="text-3xs tracking-widest text-white/35">LEVEL</span>
        <span className="text-white/80">
          {game.level || 0}
          {ld !== 0 && <span className={ld > 0 ? "text-good" : "text-bad"}> {ld > 0 ? "+" : ""}{ld}</span>}
        </span>
      </div>
      <div className="flex flex-col">
        <span className="text-3xs tracking-widest text-white/35">KDA</span>
        <span className="font-mono text-white/80">{game.kills ?? 0}/{game.deaths ?? 0}/{game.assists ?? 0}</span>
      </div>
      {hasSpike && (
        <div className="flex flex-col" title="Completed items vs your lane opponent">
          <span className="text-3xs tracking-widest text-white/35">ITEMS</span>
          <span className={`font-mono ${SPIKE_TONE[spike.status] || "text-white/70"}`}>
            {spike.mine}<span className="text-white/30">/{spike.opponent}</span>
          </span>
        </div>
      )}
    </div>
  );
}

const SOUL = {
  ally_soul_point: { text: "SOUL POINT — secure the next dragon", cls: "border-good/45 bg-good/10 text-good" },
  enemy_soul_point: { text: "ENEMY SOUL POINT — contest the next dragon", cls: "border-bad/45 bg-bad/10 text-bad" },
  ally_soul: { text: "DRAGON SOUL secured", cls: "border-good/45 bg-good/10 text-good" },
  enemy_soul: { text: "ENEMY HAS SOUL — play around Elder", cls: "border-bad/45 bg-bad/10 text-bad" },
};

/* A prominent one-line warning at the decisive dragon-soul moment. */
function SoulBanner({ soul }) {
  const s = SOUL[soul?.status];
  if (!s) return null;
  return (
    <div className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-2xs font-bold tracking-wide backdrop-blur-sm ${s.cls}`}>
      <Flame className="h-3.5 w-3.5 shrink-0" />
      <span>{s.text}</span>
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
          <div className="text-3xs tracking-widest text-white/35">DRAGON</div>
          <div className={`font-mono text-sm font-bold ${dragon <= 0 ? "text-good" : "text-white/85"}`}>{fmtTimer(dragon)}</div>
        </div>
      </div>
      <div className="flex flex-1 items-center gap-2 rounded-lg border border-white/10 bg-black/45 px-2.5 py-1.5 backdrop-blur-sm">
        <Crown className="h-4 w-4 shrink-0 text-violet-300" />
        <div className="leading-tight">
          <div className="text-3xs tracking-widest text-white/35">BARON</div>
          <div className={`font-mono text-sm font-bold ${baron <= 0 ? "text-good" : "text-white/85"}`}>{fmtTimer(baron)}</div>
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

  // Voice coaching (Web Speech API; Riot-safe — read-only audio). Off by default
  // so the overlay never surprises a stream/OBS scene with audio; the choice
  // persists across sessions.
  const [voiceOn, setVoiceOn] = useState(() => {
    try { return localStorage.getItem(VOICE_KEY) === "on"; } catch { return false; }
  });
  const toggleVoice = () => setVoiceOn((v) => {
    const next = !v;
    try { localStorage.setItem(VOICE_KEY, next ? "on" : "off"); } catch { /* ignore */ }
    return next;
  });
  useCoachSpeech({ missions, game }, voiceOn);

  return (
    <div className="w-[300px] select-none p-2 font-tech">
      <div className="mb-1.5 flex items-center gap-1.5 px-1">
        <Zap className="h-3.5 w-3.5 text-accent" />
        <span className="font-display text-xs font-bold tracking-[0.25em] text-white/70">
          SYLQON COACH
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {inGame
            ? <span className="font-mono text-2xs font-bold tracking-wide text-white/45">{fmtClock(game.game_time)}</span>
            : role && <span className="text-2xs font-bold tracking-widest text-white/35">{ROLE_LABELS[role] || role}</span>}
          {speechSupported() && (
            <button
              onClick={toggleVoice}
              title={voiceOn ? "Mute voice coaching" : "Enable voice coaching"}
              aria-label={voiceOn ? "Mute voice coaching" : "Enable voice coaching"}
              className="rounded p-0.5 text-white/45 transition-colors hover:text-white/80"
            >
              {voiceOn
                ? <Volume2 className="h-3.5 w-3.5 text-accent" />
                : <VolumeX className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>

      {!active && missions.length === 0 ? (
        <div className="rounded-lg border border-white/10 bg-black/40 px-3 py-3 text-center text-sm text-white/40 backdrop-blur-sm">
          Waiting for a game…
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {inGame && <SoulBanner soul={game.soul} />}
          {inGame && <Benchmark game={game} />}
          {inGame && <Objectives timers={game.objective_timers} />}
          {missions.map((m) => <MissionCard key={m.id} mission={m} />)}
        </div>
      )}

      {championProgress?.champion && (
        <div className="mt-2 rounded-lg border border-accent/20 bg-black/45 px-3 py-1.5 text-xs backdrop-blur-sm">
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
        <div className="mt-2 flex items-center gap-3 rounded-lg border border-white/10 bg-black/45 px-3 py-1.5 text-xs backdrop-blur-sm">
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
