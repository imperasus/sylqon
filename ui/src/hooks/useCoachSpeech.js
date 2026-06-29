import { useEffect, useRef } from "react";
import {
  cancelSpeech,
  speak,
  speakablesFor,
  speechSupported,
} from "../components/overlay/speech.js";

/* Speaks overlay events aloud as they happen (new/completed missions, dragon-soul
   moments, objectives coming up). Edge-triggered off `snapshot` ({missions, game}),
   so nothing is re-announced on the ~1.5s poll unless it actually changed.

   - The first observed snapshot only primes the baseline (no burst of speech when
     the overlay mounts mid-game).
   - While `enabled` is false the baseline is kept current, so toggling voice back
     on never dumps a backlog — only future changes are spoken. */
export function useCoachSpeech(snapshot, enabled) {
  const prev = useRef(null);
  const primed = useRef(false);

  useEffect(() => {
    if (!speechSupported()) return;
    if (!enabled) {
      prev.current = snapshot; // stay in sync so re-enabling starts clean
      return;
    }
    if (!primed.current) {
      prev.current = snapshot;
      primed.current = true;
      return;
    }
    for (const item of speakablesFor(prev.current, snapshot)) {
      speak(item.text, { priority: item.priority });
    }
    prev.current = snapshot;
  }, [snapshot, enabled]);

  // Stop any in-flight speech when the overlay unmounts.
  useEffect(() => () => cancelSpeech(), []);
}
