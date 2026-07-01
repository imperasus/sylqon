import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 1500;

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

/** Polls the FastAPI bridge and exposes dashboard actions. */
export function useSylqon() {
  const [state, setState] = useState(null);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState("");
  const [lastError, setLastError] = useState(null);
  const timer = useRef(null);

  const refresh = useCallback(async () => {
    try {
      setState(await apiFetch("/api/state"));
      setOnline(true);
    } catch (e) {
      // Distinguish "backend down / errored" from "no data yet" — the UI can
      // now show an explicit offline banner instead of a bare empty state.
      setOnline(false);
      setLastError({ where: "state", message: e?.message || String(e) });
      logApiError("GET /api/state", e);
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer.current);
  }, [refresh]);

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
    online,
    busy,
    lastError,
    inject: (variant) => action("inject", "/api/inject", { variant }),
    injectVariant: (index) => action("inject", "/api/inject/variant", { index }),
    startDemo: () => action("demo", "/api/demo", {}),
    stopDemo: () => action("demo", "/api/demo", null),
  };
}

/** Loads the static-ish dashboard data: champion list + op.gg meta report.
 * Fetched once on mount (they only change on a patch / catalog refresh). */
export function useStaticData() {
  const [champions, setChampions] = useState([]);
  const [meta, setMeta] = useState({ positions: {}, patch: "" });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [c, m] = await Promise.all([
          apiFetch("/api/champions"),
          apiFetch("/api/meta"),
        ]);
        if (cancelled) return;
        setChampions(c.champions || []);
        setMeta(m || { positions: {} });
      } catch (e) {
        logApiError("useStaticData", e); // degrade to empty, but visibly
      }
    })();
    return () => (cancelled = true);
  }, []);
  return { champions, meta };
}

/** Champion-pool reads + writes (Dashboard editor). */
export function usePool() {
  const [pool, setPool] = useState({});
  const [buildable, setBuildable] = useState({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch("/api/pool");
      setPool(r.pool || {});
      setBuildable(r.buildable || {});
    } catch (e) {
      logApiError("usePool.load", e);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(async (nextPool) => {
    setSaving(true);
    setPool(nextPool); // optimistic
    try {
      const j = await apiFetch("/api/pool", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pool: nextPool }),
      });
      setPool(j.pool || nextPool);
    } catch (e) {
      logApiError("usePool.save", e); // keep optimistic value; surface the failure
    } finally {
      setSaving(false);
    }
  }, []);

  return { pool, buildable, saving, save, reload: load };
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
  const [stats, setStats] = useState({});
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await apiFetch("/api/champion-stats");
        if (!cancelled) setStats(r.stats || {});
      } catch (e) {
        logApiError("useChampionStats", e);
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);
  return stats;
}

/** "Ollama Meta Scout" recommendation for a role. Returns the heuristic result
 * instantly, then re-fetches once so the Ollama-refined wording can land. */
export function useScout(role) {
  const [scout, setScout] = useState(null);
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const load = async () => {
      try {
        const r = await apiFetch(`/api/scout?role=${role}`);
        if (cancelled) return;
        setScout(r);
        // If still heuristic, the AI may be refining in the background — peek again.
        if (r?.source === "heuristic" && r?.pick) {
          timer = setTimeout(load, 4000);
        }
      } catch (e) {
        logApiError("useScout", e);
      }
    };
    setScout(null);
    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [role]);
  return scout;
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
export async function fetchRecentMatches(limit = 10) {
  return apiFetch(`/api/matches/recent?limit=${limit}`);
}
export async function fetchMatchAnalysis(id) {
  return apiFetch(`/api/matches/${id}/analysis`);
}
export async function fetchMacroCoach() {
  return apiFetch(`/api/coach`);
}
export async function refreshMacroCoach() {
  return apiFetch(`/api/coach/refresh`, { method: "POST" });
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
