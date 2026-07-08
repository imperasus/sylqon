import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import {
  Check, Cpu, Globe, KeyRound, Loader2, MonitorPlay, Settings as SettingsIcon, X,
} from "lucide-react";
import { useSettings } from "../api.js";

/* Dashboard Settings panel. Reads the effective settings from the backend
   (env/default overlaid with persisted user overrides), edits them grouped by
   theme, and PUTs the changed values back. Mirrors the portal + framer-motion
   modal pattern used by MatchAnalysisModal. Hungarian UI to match the app. */

const GROUPS = [
  { key: "region", label: "Régió & adat", icon: Globe },
  { key: "riot", label: "Riot API", icon: KeyRound },
  { key: "ai", label: "AI / Ollama", icon: Cpu },
  { key: "overlay", label: "Overlay & missziók", icon: MonitorPlay },
];

// Human labels + (for string fields) a dropdown option list. Anything not listed
// falls back to a plain text/number input driven by the setting's type.
const OPGG_REGIONS = ["na", "euw", "eune", "kr", "br", "jp", "oce", "las", "lan", "tr", "ru", "vn"];
const RIOT_PLATFORMS = ["euw1", "na1", "kr", "eun1", "br1", "jp1", "oce1", "la1", "la2", "tr1", "ru"];
const RIOT_MASS = ["europe", "americas", "asia", "sea"];

const FIELD = {
  opgg_region: { label: "OP.GG régió", options: OPGG_REGIONS, hint: "Build-meta lekérés régiója" },
  riot_api_region: { label: "Riot platform régió", options: RIOT_PLATFORMS, hint: "Spectator / League (live scout)" },
  riot_api_mass_region: { label: "Riot mass régió", options: RIOT_MASS, hint: "Match-V5 (meccstörténet)" },
  cache_ttl_seconds: { label: "Build-cache élettartam (mp)", hint: "Mennyi ideig friss egy cache-elt build" },
  auto_full_sync: { label: "Auto teljes szinkron", hint: "Patch-váltáskor automatikus op.gg sync" },

  riot_api_key: { label: "Riot API kulcs", hint: "Live scouthoz; lokálisan tárolva (mint a .env)" },
  riot_self_puuid: { label: "Saját PUUID", hint: "A kulcshoz tartozó fiók azonosítója" },
  riot_match_count: { label: "Scout meccsmennyiség", hint: "Játékosonként lekért meccsek száma" },

  ollama_url: { label: "Ollama URL" },
  ollama_model: { label: "Ollama modell" },
  ollama_timeout_seconds: { label: "Ollama timeout (mp)" },
  open_build_mode: { label: "Open-build mód", hint: "Teljes item-katalógusból javasol" },
  rag_items_mode: { label: "RAG itemek", hint: "Szemantikus item-keresés (open-build kell)" },
  rag_runes_mode: { label: "RAG runák", hint: "Szemantikus runa-keresés" },
  rag_kit_mode: { label: "RAG kit-grounding", hint: "Képesség fact-sheet a lane-tervhez" },
  rag_fusion_mode: { label: "RAG scout-fúzió", hint: "Ellenfél scout + kit a lane-tervbe" },

  overlay_auto: { label: "Overlay auto megjelenés", hint: "Meccs indulásakor magától felugrik / eltűnik" },
  overlay_max_missions: { label: "Max. egyszerre látható misszió" },
  live_poll_seconds: { label: "Overlay poll (mp)", hint: "Kisebb = gyorsabb, több CPU" },
  champion_mission_target: { label: "Misszió-queue / bajnok" },
};

const MISSION_TYPES = [
  ["no_death_for_duration", "Halál nélkül (idő)"],
  ["farm_cs_delta", "CS előny (farm)"],
  ["cs_per_min_threshold", "CS/perc cél"],
  ["objective_control", "Objektíva kontroll"],
  ["warding", "Wardozás"],
  ["roam_assist", "Roam / segítés"],
  ["gank_assist", "Gank segítés"],
];
const ALL_MISSION_IDS = MISSION_TYPES.map(([id]) => id);

const INPUT_CLS =
  "w-full rounded-md border border-white/15 bg-black/30 px-2 py-1 text-sm text-white/85 transition-colors focus:border-accent/50 focus:outline-none";

function Toggle({ on, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      className={`relative h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors
        ${on ? "border-accent/60 bg-accent/30" : "border-white/15 bg-white/5"}`}
      role="switch"
      aria-checked={on}
    >
      <span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all ${on ? "left-4 bg-accent-bright" : "left-0.5 bg-white/50"}`} />
    </button>
  );
}

function RestartTag() {
  return (
    <span className="rounded bg-amber/15 px-1 py-px text-3xs font-bold tracking-wider text-amber" title="Újraindítás után lép életbe">
      RESTART
    </span>
  );
}

/* One labelled setting row. Renders by type, with selects for known string
   fields and a masked password input for secrets. */
function Field({ name, spec, value, onChange }) {
  const meta = FIELD[name] || { label: name };
  const restart = spec.applies === "restart";

  let control;
  if (spec.type === "bool") {
    control = <Toggle on={!!value} onChange={onChange} />;
  } else if (spec.secret) {
    control = (
      <input
        type="password"
        className={INPUT_CLS}
        placeholder={spec.value ? "•••••••• (beállítva)" : "nincs beállítva"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
      />
    );
  } else if (meta.options) {
    control = (
      <select className={INPUT_CLS} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {meta.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  } else if (spec.type === "int" || spec.type === "float") {
    control = (
      <input
        type="number"
        step={spec.type === "float" ? "0.1" : "1"}
        className={INPUT_CLS}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  } else {
    control = <input type="text" className={INPUT_CLS} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }

  const inline = spec.type === "bool";
  return (
    <div className={inline ? "flex items-center justify-between gap-3 py-1" : "flex flex-col gap-1 py-1"}>
      <div className="flex items-center gap-1.5">
        <span className="text-sm font-semibold text-white/80">{meta.label}</span>
        {restart && <RestartTag />}
      </div>
      {inline ? control : <div>{control}</div>}
      {meta.hint && !inline && <span className="text-xs text-white/35">{meta.hint}</span>}
      {meta.hint && inline && <span className="sr-only">{meta.hint}</span>}
    </div>
  );
}

export default function SettingsModal({ onClose }) {
  const { settings, loading, saving, load, save } = useSettings();
  const [form, setForm] = useState({});
  const [missions, setMissions] = useState(null); // Set<string> | null

  useEffect(() => { load(); }, [load]);

  // Dismiss on Escape.
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Seed the editable form once the effective settings arrive.
  useEffect(() => {
    if (!settings) return;
    const f = {};
    for (const [key, spec] of Object.entries(settings)) {
      if (spec.type === "strset") continue;
      f[key] = spec.secret ? "" : spec.value;
    }
    setForm(f);
    const enabled = settings.mission_types_enabled?.value || [];
    setMissions(enabled.length ? new Set(enabled) : new Set(ALL_MISSION_IDS));
  }, [settings]);

  const setField = (key, val) => setForm((p) => ({ ...p, [key]: val }));
  const toggleMission = (id) =>
    setMissions((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const onSave = async () => {
    const patch = { ...form };
    if (missions) patch.mission_types_enabled = Array.from(missions);
    await save(patch);
    onClose();
  };

  const entriesFor = (group) =>
    Object.entries(settings || {}).filter(([, s]) => s.group === group && s.type !== "strset");

  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/65 p-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
        transition={{ duration: 0.18 }}
        onClick={(e) => e.stopPropagation()}
        className="surface-modal relative flex max-h-[90svh] w-[min(94vw,46rem)] flex-col gap-4 overflow-hidden rounded-2xl p-5"
      >
        <button onClick={onClose}
                className="absolute right-3 top-3 grid h-8 w-8 cursor-pointer place-items-center rounded-md border border-white/15 text-white/50 hover:border-accent/40 hover:text-accent-bright">
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-2">
          <SettingsIcon className="h-5 w-5 text-accent" />
          <span className="font-display text-lg font-bold tracking-[0.08em] text-white/90">BEÁLLÍTÁSOK</span>
        </div>

        {loading && !settings && (
          <div className="flex items-center gap-2 py-10 text-md text-white/50">
            <Loader2 className="h-4 w-4 animate-spin text-accent" /> Beállítások betöltése…
          </div>
        )}

        {settings && (
          <div className="flex min-h-0 flex-col gap-5 overflow-y-auto pr-1">
            {GROUPS.map((g) => (
              <section key={g.key} className="flex flex-col gap-1">
                <div className="mb-1 flex items-center gap-1.5 font-display text-sm font-bold tracking-[0.08em] text-accent/85">
                  <g.icon className="h-4 w-4" />
                  {g.label}
                </div>
                <div className="grid gap-x-5 gap-y-1 sm:grid-cols-2">
                  {entriesFor(g.key).map(([key, spec]) => (
                    <Field key={key} name={key} spec={spec} value={form[key]} onChange={(v) => setField(key, v)} />
                  ))}
                </div>

                {/* Mission-type checkboxes + hotkey discoverability live in the overlay group. */}
                {g.key === "overlay" && (
                  <>
                    <div className="mt-2 flex flex-col gap-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-semibold text-white/80">Aktív misszió-típusok</span>
                        {settings.mission_types_enabled?.applies === "restart" && <RestartTag />}
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                        {MISSION_TYPES.map(([id, label]) => {
                          const on = missions?.has(id);
                          return (
                            <button key={id} type="button" onClick={() => toggleMission(id)}
                                    className="flex cursor-pointer items-center gap-2 py-0.5 text-left">
                              <span className={`grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors
                                ${on ? "border-accent/60 bg-accent/25 text-accent-bright" : "border-white/20 text-transparent"}`}>
                                <Check className="h-3 w-3" />
                              </span>
                              <span className={`text-sm ${on ? "text-white/80" : "text-white/45"}`}>{label}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div className="mt-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-white/45">
                      Overlay ki/be: <span className="font-mono text-white/70">F10</span> · átkattinthatóság:
                      {" "}<span className="font-mono text-white/70">F9</span> — játék közben sem kell alt-tab.
                    </div>
                  </>
                )}
              </section>
            ))}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-white/10 pt-3">
          <button onClick={onClose}
                  className="cursor-pointer rounded-md border border-white/15 px-3 py-1 text-xs font-bold uppercase tracking-widest text-white/55 transition-colors hover:bg-white/8 hover:text-white/85">
            Mégse
          </button>
          <button onClick={onSave} disabled={saving || !settings}
                  className={`inline-flex items-center gap-1.5 rounded-md border border-transparent bg-accent px-3 py-1 text-xs font-bold uppercase tracking-widest text-bg transition-colors hover:bg-accent-bright
                    ${saving || !settings ? "cursor-default opacity-50" : "cursor-pointer"}`}>
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Mentés
          </button>
        </div>
      </motion.div>
    </div>,
    document.body,
  );
}
