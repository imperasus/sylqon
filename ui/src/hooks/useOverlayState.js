import { useEffect, useRef, useState } from "react";

const POLL_MS = 1500;

/* Polls the in-game overlay coach endpoint. Returns the active missions, the
   account progression, and the live stats that matter — refreshed ~1.5s. */
export function useOverlayState() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch("/api/overlay/state");
        const json = await res.json();
        if (!cancelled) { setData(json); setLoading(false); }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };
    tick();
    timer.current = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(timer.current); };
  }, []);

  return {
    loading,
    active: !!data?.active,
    role: data?.role || "",
    missions: data?.active_missions || [],
    alerts: data?.alerts || [],
    profile: data?.profile || null,
    championProgress: data?.champion_progress || null,
    progress: data?.progress || null,
    game: data?.game || {},
  };
}
