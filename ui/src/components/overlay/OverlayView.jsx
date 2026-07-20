import { useState } from "react";
import {
  AlertTriangle, Coins, Crown, Eye, Flame, Skull, Swords, Sword, Target,
  Trophy, Volume2, VolumeX, Zap,
} from "lucide-react";
import { ROLE_LABELS } from "../../assets.js";
import { useOverlayState } from "../../hooks/useOverlayState.js";
import { useCoachSpeech } from "../../hooks/useCoachSpeech.js";
import { speechSupported } from "./speech.js";
import BrandMark from "../BrandMark.jsx";
import MissionCard from "./MissionCard.jsx";

const VOICE_KEY = "sylqon.coach.voice";

const fmtClock = (s) => {
  const t = Math.max(0, Math.floor(s || 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};
// Objective timers are estimated from on-screen kill events + standard respawn
// rules, so a leading "≈" marks them as an estimate, not a server feed.
const fmtTimer = (s) => (s != null && s <= 0 ? "UP" : `≈${fmtClock(s)}`);

const CS_TONE = { ahead: "text-good", behind: "text-bad", "on-track": "text-white/70" };

/* Compact live readout: CS-vs-target, level diff, KDA — all from the read-only
   Live Client Data snapshot the coach already polls. */
const SPIKE_TONE = { ahead: "text-good", behind: "text-bad", even: "text-white/70" };

/* A colour-independent shape for each status, so ahead/behind reads the same for
   colourblind users (never colour alone). */
const STATUS_SYM = { ahead: "▲", behind: "▼", "on-track": "·", even: "·" };
const sym = (s) => STATUS_SYM[s] || "";

function Benchmark({ game }) {
  const b = game.cs_benchmark || {};
  const ld = game.level_diff || 0;
  const spike = game.item_spike || {};
  const hasSpike = !!spike.status;
  return (
    <div className={`grid ${hasSpike ? "grid-cols-4" : "grid-cols-3"} gap-1.5 rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5 text-xs`}>
      <div className="flex flex-col">
        <span className="text-3xs tracking-widest text-white/35">CS/MIN</span>
        <span className={CS_TONE[b.status] || "text-white/70"}>
          {sym(b.status) && <span className="mr-0.5">{sym(b.status)}</span>}
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
            {sym(spike.status) && <span className="mr-0.5 font-sans">{sym(spike.status)}</span>}
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

/* State-reactive coaching alerts (Phase 3): an edge-triggered call + its "why".
   Tone drives the colour; the category picks the icon. */
const ALERT_TONE = {
  good: "border-good/45 bg-good/10 text-good",
  bad: "border-bad/50 bg-bad/12 text-bad",
  info: "border-accent/40 bg-accent/10 text-accent",
};
const ALERT_ICON = {
  low_hp: AlertTriangle,
  enemy_down: Swords,
  ult_spike: Zap,
  item_spike: Sword,
  recall_gold: Coins,
  objective_setup: Eye,
  death_review: Skull,
  matchup_plan: Target,
};

function AlertBanner({ alert }) {
  const Icon = ALERT_ICON[alert.category] || Flame;
  return (
    <div className={`flex items-start gap-1.5 rounded-lg border px-2.5 py-1.5 ${ALERT_TONE[alert.tone] || ALERT_TONE.info}`}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="leading-tight">
        <div className="text-2xs font-bold tracking-wide">{alert.text}</div>
        {alert.rationale && (
          <div className="mt-0.5 text-3xs font-normal text-white/55">{alert.rationale}</div>
        )}
      </div>
    </div>
  );
}

/* A prominent one-line warning at the decisive dragon-soul moment. The rift
   terrain names the soul element, so the call is specific ("INFERNAL SOUL POINT"). */
function SoulBanner({ soul }) {
  const s = SOUL[soul?.status];
  if (!s) return null;
  const el = soul?.type ? `${soul.type.toUpperCase()} ` : "";
  return (
    <div className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-2xs font-bold tracking-wide ${s.cls}`}>
      <Flame className="h-3.5 w-3.5 shrink-0" />
      <span>{el}{s.text}</span>
    </div>
  );
}

function Objectives({ timers }) {
  const dragon = timers?.dragon;
  const baron = timers?.baron;
  if (dragon == null && baron == null) return null;
  return (
    <div className="flex gap-1.5">
      <div className="flex flex-1 items-center gap-2 rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5">
        <Flame className="h-4 w-4 shrink-0 text-mana" />
        <div className="leading-tight">
          <div className="text-3xs tracking-widest text-white/35">DRAGON</div>
          <div className={`font-mono text-sm font-bold ${dragon <= 0 ? "text-good" : "text-white/85"}`}>{fmtTimer(dragon)}</div>
        </div>
      </div>
      <div className="flex flex-1 items-center gap-2 rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5">
        <Crown className="h-4 w-4 shrink-0 text-arcane" />
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
const TREND = {
  improving: { sym: "▲", cls: "text-good" },
  up: { sym: "▲", cls: "text-good" },
  declining: { sym: "▼", cls: "text-bad" },
  down: { sym: "▼", cls: "text-bad" },
};

/* A slim consistency row: current streak, this-game tally, and recent trend —
   the "am I improving" read a flat point total can't give. */
function ProgressRow({ progress }) {
  if (!progress) return null;
  const { streak = 0, session, recent, trend } = progress;
  const t = TREND[recent?.trend];
  const csT = TREND[trend?.direction];
  const hasSession = (session?.completed || 0) + (session?.failed || 0) > 0;
  if (!streak && !hasSession && !t && !csT) return null;
  return (
    <div className="mt-2 flex items-center gap-3 rounded-lg border border-white/10 bg-black/60 px-3 py-1.5 text-xs">
      {streak > 0 && (
        <span className="flex items-center gap-1 font-bold text-amber" title="Completed-mission streak">
          <Flame className="h-3.5 w-3.5" /> {streak}
        </span>
      )}
      {hasSession && (
        <span className="font-mono text-white/55" title="This game: completed · points">
          {session.completed}✓ · +{session.points}
        </span>
      )}
      <span className="ml-auto flex items-center gap-2 text-white/50">
        {t && recent?.total >= 6 && (
          <span className={t.cls} title={`Recent completion ${Math.round((recent.completion_rate || 0) * 100)}%`}>
            {t.sym} form
          </span>
        )}
        {csT && (
          <span className={csT.cls} title={`CS/min ${trend.from} → ${trend.to}`}>
            {csT.sym} {trend.to} cs/m
          </span>
        )}
      </span>
    </div>
  );
}

export default function OverlayView() {
  const { active, role, missions, alerts, profile, championProgress, progress, game } = useOverlayState();
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
  useCoachSpeech({ missions, alerts, game }, voiceOn);

  return (
    <div className="w-[300px] select-none p-2 font-tech">
      <div className="mb-1.5 flex items-center gap-1.5 px-1">
        <BrandMark className="h-3.5 w-3.5" />
        <span className="font-display text-xs font-bold tracking-[0.1em] text-white/70">
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
        <div className="rounded-lg border border-white/10 bg-black/55 px-3 py-3 text-center text-sm text-white/40">
          Waiting for a game…
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {inGame && alerts.map((a) => <AlertBanner key={a.id} alert={a} />)}
          {inGame && <SoulBanner soul={game.soul} />}
          {inGame && <Benchmark game={game} />}
          {inGame && <Objectives timers={game.objective_timers} />}
          {missions.map((m) => <MissionCard key={m.id} mission={m} />)}
        </div>
      )}

      {championProgress?.champion && (
        <div className="mt-2 rounded-lg border border-accent/20 bg-black/60 px-3 py-1.5 text-xs">
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

      <ProgressRow progress={progress} />

      {profile && (
        <div className="mt-2 flex items-center gap-3 rounded-lg border border-white/10 bg-black/60 px-3 py-1.5 text-xs">
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
