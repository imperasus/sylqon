import { useEffect, useRef, useState } from "react";

/* Smooths the champ-select countdown between /api/state polls (~1.5s): tracks a
   local deadline off the server's last-known remaining_ms and free-runs a fast
   interval so the number ticks roughly every 200ms instead of jumping once per
   poll. Resyncs automatically whenever a new poll reports a fresh remaining_ms,
   so server-side drift (or a champ-select phase change) self-corrects.

   `clock` is the raw `{ phase, remaining_ms, total_ms }` from state.draft_clock,
   or null/undefined outside champ select. Returns `{ seconds, fraction, urgency,
   phase }` — fraction is 0..1 of time left in the phase, urgency is "calm" |
   "warn" | "danger" for color-coding the countdown. */
export function useDraftClock(clock) {
  const [msLeft, setMsLeft] = useState(0);
  const deadlineRef = useRef(null);
  const totalRef = useRef(1);

  useEffect(() => {
    if (!clock) {
      deadlineRef.current = null;
      setMsLeft(0);
      return;
    }
    deadlineRef.current = performance.now() + clock.remaining_ms;
    totalRef.current = clock.total_ms || clock.remaining_ms || 1;
    const tick = () => setMsLeft(Math.max(0, deadlineRef.current - performance.now()));
    tick();
    const id = setInterval(tick, 200);
    return () => clearInterval(id);
  }, [clock?.remaining_ms, clock?.total_ms, clock?.phase]);

  const fraction = Math.max(0, Math.min(1, msLeft / totalRef.current));
  const seconds = Math.ceil(msLeft / 1000);
  const urgency = !clock ? "calm" : seconds <= 5 ? "danger" : seconds <= 15 ? "warn" : "calm";
  return { seconds, fraction, urgency, phase: clock?.phase || "" };
}
