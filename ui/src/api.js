import { useCallback, useEffect, useState } from "react";
import {
  QueryClient, useMutation, useQuery, useQueryClient,
} from "@tanstack/react-query";

// Champ select and a live game need a tight loop; an idle Home does not. One
// adaptive interval replaces the per-component `setInterval`s that used to poll
// the same backend independently.
const POLL_ACTIVE_MS = 1500;
const POLL_IDLE_MS = 4000;
const POLL_SLOW_MS = 30000;

/** Shared client. Server state is polled, so retries and refetch-on-focus only
 * add duplicate traffic — the next interval tick recovers anyway. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 1000,
    },
  },
});

/** True while the client is in champ select or a live game. */
function isLivePhase(state) {
  if (!state) return false;
  return Boolean(state.lobby || state.live?.active || state.lcu?.phase === "InProgress");
}

/** Debug toggle: `?debug=1` in the URL or `localStorage.sylqon_debug=1`.
 * Off by default; when on, the fetch layer logs verbose timing/detail. */
export function debugEnabled() {
  try {
    const q = new URLSearchParams(window.location.search);
    if (q.get("debug") === "1") return true;
    return window.localStorage.getItem("sylqon_debug") === "1";
  } catch {
    return false;
  }
}

/** Single place where fetch failures become visible. Previously every caller
 * swallowed errors silently (`catch {}`), so a broken endpoint left no trace in
 * the console. This always logs; degradation (returning empty/null) stays the
 * caller's choice. */
export function logApiError(where, err) {
  console.error(`[sylqon] ${where} failed:`, err?.message || err);
}

/** fetch + status check + JSON parse. Throws a contextual error on non-2xx so a
 * 4xx/5xx no longer slips through as if it were a valid body. */
export async function apiFetch(path, options) {
  const started = performance.now();
  const res = await fetch(path, options);
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} on ${path}`);
    err.status = res.status;
    err.path = path;
    throw err;
  }
  const data = await res.json();
  if (debugEnabled()) {
    console.debug(`[sylqon] ${options?.method || "GET"} ${path} -> ${res.status} (${Math.round(performance.now() - started)}ms)`);
  }
  return data;
}

async function post(path, body) {
  return apiFetch(path, {
    method: body === null ? "DELETE" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

/** Polls the FastAPI bridge and exposes dashboard actions. The poll rate follows
 * the client phase: tight during champ select / a live game, relaxed on an idle
 * Home so a parked dashboard is not hammering the backend. */
export function useSylqon() {
  const [busy, setBusy] = useState("");
  const [lastError, setLastError] = useState(null);
  const qc = useQueryClient();

  const { data: state = null, isSuccess, error } = useQuery({
    queryKey: ["state"],
    queryFn: () => apiFetch("/api/state"),
    refetchInterval: (query) =>
      isLivePhase(query.state.data) ? POLL_ACTIVE_MS : POLL_IDLE_MS,
    refetchIntervalInBackground: true,
  });

  // Distinguish "backend down / errored" from "no data yet" — the UI shows an
  // explicit offline banner instead of a bare empty state.
  useEffect(() => {
    if (error) {
      setLastError({ where: "state", message: error?.message || String(error) });
      logApiError("GET /api/state", error);
    }
  }, [error]);

  const refresh = useCallback(() => qc.invalidateQueries({ queryKey: ["state"] }), [qc]);

  const action = useCallback(
    async (name, path, body) => {
      setBusy(name);
      try {
        const res = await post(path, body);
        setLastError(null);
        return res;
      } catch (e) {
        // Action failures used to vanish in the `finally`; surface them.
        setLastError({ where: name, message: e?.message || String(e) });
        logApiError(`${name} ${path}`, e);
        return { error: e?.message || String(e) };
      } finally {
        setBusy("");
        refresh();
      }
    },
    [refresh]
  );

  return {
    state,
    online: isSuccess && !error,
    busy,
    lastError,
    refresh,
    inject: (variant) => action("inject", "/api/inject", { variant }),
    injectVariant: (index) => action("inject", "/api/inject/variant", { index }),
    startDemo: () => action("demo", "/api/demo", {}),
    stopDemo: () => action("demo", "/api/demo", null),
    fullSync: () => action("sync", "/api/sync/full", {}),
  };
}

/** Loads the static-ish dashboard data: champion list + op.gg meta report.
 * Fetched once on mount (they only change on a patch / catalog refresh). */
export function useStaticData() {
  const { data } = useQuery({
    queryKey: ["static"],
    queryFn: async () => {
      const [c, m, b] = await Promise.all([
        apiFetch("/api/champions"),
        apiFetch("/api/meta"),
        apiFetch("/api/benchmarks"),
      ]);
      return { champions: c.champions || [], meta: m || { positions: {} }, benchmarks: b || null };
    },
    staleTime: Infinity, // only changes on a patch / catalog refresh
  });
  return data || { champions: [], meta: { positions: {}, patch: "" }, benchmarks: null };
}

/** Champion-pool reads + writes (Dashboard editor). Writes are optimistic: the
 * cache updates before the PUT lands, and rolls back if it fails. */
export function usePool() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["pool"],
    queryFn: () => apiFetch("/api/pool"),
    staleTime: POLL_SLOW_MS,
  });

  const mutation = useMutation({
    mutationFn: (nextPool) =>
      apiFetch("/api/pool", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pool: nextPool }),
      }),
    onMutate: async (nextPool) => {
      await qc.cancelQueries({ queryKey: ["pool"] });
      const previous = qc.getQueryData(["pool"]);
      qc.setQueryData(["pool"], (old) => ({ ...(old || {}), pool: nextPool }));
      return { previous };
    },
    onError: (e, _next, ctx) => {
      qc.setQueryData(["pool"], ctx?.previous); // roll back, then surface it
      logApiError("usePool.save", e);
    },
    onSuccess: (j) => {
      if (j?.pool) qc.setQueryData(["pool"], j);
    },
  });

  return {
    pool: data?.pool || {},
    buildable: data?.buildable || {},
    saving: mutation.isPending,
    save: mutation.mutate,
    reload: () => qc.invalidateQueries({ queryKey: ["pool"] }),
  };
}

/** Dashboard Settings: lazy GET on open + PUT save. The backend returns the
 * effective values (env/default overlaid with persisted overrides) keyed by
 * setting name, each with { value, type, group, applies, secret } metadata. */
export function useSettings() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch("/api/settings");
      setSettings(r.settings || {});
    } catch (e) {
      logApiError("useSettings.load", e); // modal shows a degraded state
    } finally {
      setLoading(false);
    }
  }, []);

  const save = useCallback(async (patch) => {
    setSaving(true);
    try {
      const j = await apiFetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: patch }),
      });
      if (j.settings) setSettings(j.settings);
      return j.settings;
    } catch (e) {
      logApiError("useSettings.save", e);
      return undefined;
    } finally {
      setSaving(false);
    }
  }, []);

  return { settings, loading, saving, load, save };
}

/** Per-champion personal win-rate + games from local match history.
 * Keyed by champion name; refreshed on a slow poll (history rarely changes). */
export function useChampionStats() {
  const { data } = useQuery({
    queryKey: ["champion-stats"],
    queryFn: () => apiFetch("/api/champion-stats"),
    refetchInterval: POLL_SLOW_MS,
    staleTime: POLL_SLOW_MS,
  });
  return data?.stats || {};
}

/** "Ollama Meta Scout" recommendation for a role. Returns the heuristic result
 * instantly, then keeps polling until the Ollama-refined wording lands. */
export function useScout(role) {
  const { data } = useQuery({
    queryKey: ["scout", role],
    queryFn: () => apiFetch(`/api/scout?role=${role}`),
    // Still heuristic means the AI may be refining in the background — peek
    // again until it either upgrades or the pick disappears.
    refetchInterval: (query) =>
      query.state.data?.source === "heuristic" && query.state.data?.pick ? 4000 : false,
  });
  return data || null;
}

/** Account macro coach: scorecard, movement vs the previous window, the derived
 * next-match goal and account progression. One query, shared by every consumer
 * on the page — this used to be a second 30s `setInterval` inside MacroCoach. */
export function useMacroCoach() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["coach"],
    queryFn: () => apiFetch("/api/coach"),
    refetchInterval: POLL_SLOW_MS,
  });
  const refresh = useMutation({
    mutationFn: () => apiFetch("/api/coach/refresh", { method: "POST" }),
    onSuccess: (data) => qc.setQueryData(["coach"], data),
    onError: (e) => logApiError("POST /api/coach/refresh", e),
  });
  return {
    coach: query.data || null,
    loading: query.isLoading,
    refreshing: refresh.isPending,
    refresh: refresh.mutate,
  };
}

/** Recent Summoner's Rift games for the Home list + the hero-strip win rate. */
export function useRecentMatches(limit = 10) {
  const query = useQuery({
    queryKey: ["matches", limit],
    queryFn: () => apiFetch(`/api/matches/recent?limit=${limit}`),
    refetchInterval: POLL_SLOW_MS,
  });
  return { matches: query.data?.matches || [], loading: query.isLoading };
}

/** Tier list for a role. Keyed by role so switching back is instant (cached). */
export function useChampionsByRole(role) {
  const query = useQuery({
    queryKey: ["champions-by-role", role],
    queryFn: () => apiFetch(`/api/champions/role/${role}`),
    staleTime: POLL_SLOW_MS,
  });
  return { rows: query.data?.champions || [], loading: query.isLoading };
}

/* --- v2 champion browser + match history (plain fetchers) -----------------
 * These go through apiFetch so a non-2xx response throws (with context) instead
 * of parsing an error body as if it were valid data. Callers already `catch`. */
export async function fetchChampionsByRole(role) {
  return apiFetch(`/api/champions/role/${role}`);
}
export async function fetchChampionDetails(id, role) {
  return apiFetch(`/api/champions/${id}/details?role=${role}`);
}
export async function fetchMatchAnalysis(id) {
  return apiFetch(`/api/matches/${id}/analysis`);
}
export async function fetchProBuilds(champion, role = "") {
  const q = new URLSearchParams({ champion, ...(role ? { role } : {}) });
  return apiFetch(`/api/pro-builds?${q}`);
}

const CDRAGON =
  "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/";

/** Resolves rune perk + style ids to CommunityDragon icon URLs. */
export function usePerkIcons() {
  const [icons, setIcons] = useState({});
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const toUrl = (p) =>
          CDRAGON + p.toLowerCase().replace("/lol-game-data/assets/", "");
        const [perks, styles] = await Promise.all([
          fetch(CDRAGON + "v1/perks.json").then((r) => r.json()),
          fetch(CDRAGON + "v1/perkstyles.json").then((r) => r.json()),
        ]);
        const map = {};
        for (const p of perks) map[p.id] = { url: toUrl(p.iconPath), name: p.name };
        for (const s of styles.styles || [])
          map[s.id] = { url: toUrl(s.iconPath), name: s.name };
        if (!cancelled) setIcons(map);
      } catch (e) {
        logApiError("usePerkIcons", e); // icons degrade to placeholders
      }
    })();
    return () => (cancelled = true);
  }, []);
  return icons;
}
