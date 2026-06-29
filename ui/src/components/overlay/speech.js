/* Voice coaching for the in-game overlay.
 *
 * Riot-safe by construction: this uses ONLY the browser's Web Speech API
 * (window.speechSynthesis). It never reads game memory, injects code, or
 * simulates input — it just reads aloud information the overlay already shows
 * (missions, dragon-soul moments, objective timers) so the player can keep their
 * eyes on the game. Everything degrades silently where SpeechSynthesis is absent.
 */

export function speechSupported() {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Speak a phrase. `priority` cancels the queue first for urgent callouts. */
export function speak(text, { priority = false, rate = 1.05, volume = 1 } = {}) {
  if (!speechSupported() || !text) return;
  const synth = window.speechSynthesis;
  if (priority) synth.cancel(); // jump the queue for time-critical callouts
  const u = new SpeechSynthesisUtterance(text);
  u.rate = rate;
  u.volume = volume;
  u.lang = "en-US";
  synth.speak(u);
}

/** Stop anything currently being spoken / queued. */
export function cancelSpeech() {
  if (speechSupported()) window.speechSynthesis.cancel();
}

const SOUL_SPEECH = {
  ally_soul_point: "Soul point. Secure the next dragon.",
  enemy_soul_point: "Enemy soul point. Contest the next dragon.",
  ally_soul: "Dragon soul secured.",
  enemy_soul: "Enemy has soul. Play around Elder.",
};

/** True once an objective timer has reached / passed zero (i.e. it is up). */
const isUp = (t) => t != null && t <= 0;

/**
 * Pure diff: given the previous and current overlay snapshots, return the list
 * of phrases worth announcing on this tick. Kept side-effect-free so the
 * edge-detection logic is testable in isolation; the hook below performs the
 * actual speaking.
 *
 * A snapshot is `{ missions: [...], game: {...} }` (the shape useOverlayState
 * already exposes).
 */
export function speakablesFor(prev, next) {
  const out = [];
  if (!next) return out;

  const prevMissions = prev?.missions || [];
  const nextMissions = next.missions || [];
  const prevIds = new Set(prevMissions.map((m) => m.id));
  const prevById = new Map(prevMissions.map((m) => [m.id, m]));

  for (const m of nextMissions) {
    if (!prevIds.has(m.id)) {
      out.push({ text: `New mission. ${m.text}`, priority: false });
      continue;
    }
    const before = prevById.get(m.id);
    if (before && before.status !== "completed" && m.status === "completed") {
      out.push({ text: `Mission complete. ${m.text}`, priority: true });
    } else if (before && before.status !== "failed" && m.status === "failed") {
      out.push({ text: "Mission failed.", priority: false });
    }
  }

  // Dragon-soul state transitions — the highest-stakes macro moments.
  const soul = next.game?.soul?.status;
  if (soul && soul !== prev?.game?.soul?.status && SOUL_SPEECH[soul]) {
    out.push({ text: SOUL_SPEECH[soul], priority: true });
  }

  // Objective timers crossing into "up".
  const pt = prev?.game?.objective_timers || {};
  const nt = next.game?.objective_timers || {};
  if (!isUp(pt.dragon) && isUp(nt.dragon)) {
    out.push({ text: "Dragon is up.", priority: false });
  }
  if (!isUp(pt.baron) && isUp(nt.baron)) {
    out.push({ text: "Baron is up.", priority: false });
  }

  return out;
}
