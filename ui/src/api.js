import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 1500;

async function post(path, body) {
  const res = await fetch(path, {
    method: body === null ? "DELETE" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

/** Polls the FastAPI bridge and exposes dashboard actions. */
export function useSylqon() {
  const [state, setState] = useState(null);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState("");
  const timer = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/state");
      setState(await res.json());
      setOnline(true);
    } catch {
      setOnline(false);
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
        return await post(path, body);
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
          fetch("/api/champions").then((r) => r.json()),
          fetch("/api/meta").then((r) => r.json()),
        ]);
        if (cancelled) return;
        setChampions(c.champions || []);
        setMeta(m || { positions: {} });
      } catch {
        /* degrade to empty */
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
      const r = await (await fetch("/api/pool")).json();
      setPool(r.pool || {});
      setBuildable(r.buildable || {});
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(async (nextPool) => {
    setSaving(true);
    setPool(nextPool); // optimistic
    try {
      const r = await fetch("/api/pool", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pool: nextPool }),
      });
      const j = await r.json();
      setPool(j.pool || nextPool);
    } finally {
      setSaving(false);
    }
  }, []);

  return { pool, buildable, saving, save, reload: load };
}

/** Per-champion personal win-rate + games from local match history.
 * Keyed by champion name; refreshed on a slow poll (history rarely changes). */
export function useChampionStats() {
  const [stats, setStats] = useState({});
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await (await fetch("/api/champion-stats")).json();
        if (!cancelled) setStats(r.stats || {});
      } catch {
        /* ignore */
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
        const r = await (await fetch(`/api/scout?role=${role}`)).json();
        if (cancelled) return;
        setScout(r);
        // If still heuristic, the AI may be refining in the background — peek again.
        if (r?.source === "heuristic" && r?.pick) {
          timer = setTimeout(load, 4000);
        }
      } catch {
        /* ignore */
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

/* --- v2 champion browser + match history (plain fetchers) ----------------- */
export async function fetchChampionsByRole(role) {
  return (await fetch(`/api/champions/role/${role}`)).json();
}
export async function fetchChampionDetails(id, role) {
  return (await fetch(`/api/champions/${id}/details?role=${role}`)).json();
}
export async function fetchRecentMatches(limit = 10) {
  return (await fetch(`/api/matches/recent?limit=${limit}`)).json();
}
export async function fetchMatchAnalysis(id) {
  return (await fetch(`/api/matches/${id}/analysis`)).json();
}
export async function fetchMacroCoach() {
  return (await fetch(`/api/coach`)).json();
}
export async function refreshMacroCoach() {
  return (await fetch(`/api/coach/refresh`, { method: "POST" })).json();
}
export async function fetchProBuilds(champion, role = "") {
  const q = new URLSearchParams({ champion, ...(role ? { role } : {}) });
  return (await fetch(`/api/pro-builds?${q}`)).json();
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
      } catch {
        /* icons degrade to placeholders */
      }
    })();
    return () => (cancelled = true);
  }, []);
  return icons;
}
