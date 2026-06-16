import { useEffect, useState } from "react";
import { fetchChampionDetails, fetchChampionsByRole } from "../api.js";

/** All champions that can play a role, with per-role meta stats. */
export function useChampionData(role) {
  const [champions, setChampions] = useState([]);
  const [patch, setPatch] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const d = await fetchChampionsByRole(role);
        if (cancelled) return;
        setChampions(d.champions || []);
        setPatch(d.patch || "");
      } catch {
        if (!cancelled) setChampions([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => (cancelled = true);
  }, [role]);

  return { champions, patch, loading };
}

/** Counters / synergies / build for one champion in a role (detail popup). */
export function useChampionDetails(championId, role) {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!championId) return undefined;
    let cancelled = false;
    setLoading(true);
    setDetails(null);
    (async () => {
      try {
        const d = await fetchChampionDetails(championId, role);
        if (!cancelled) setDetails(d);
      } catch {
        if (!cancelled) setDetails({ error: true });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => (cancelled = true);
  }, [championId, role]);

  return { details, loading };
}
