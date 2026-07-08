import { useEffect, useState } from "react";
import { Cpu, Loader2, RadioTower } from "lucide-react";

/** Installed desktop-app version (same value auto-update compares). Resolves via
 *  the Electron preload bridge; stays empty in a plain browser, so the badge is
 *  simply hidden there. */
function useAppVersion() {
  const [version, setVersion] = useState("");
  useEffect(() => {
    let alive = true;
    Promise.resolve(window.sylqon?.getVersion?.())
      .then((v) => { if (alive && v) setVersion(String(v)); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return version;
}

function Dot({ ok }) {
  return (
    <span title={ok ? "Connected" : "Disconnected"}
          className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-good" : "bg-white/25"}`} />
  );
}

function Stat({ icon: Icon, ok, label, title }) {
  return (
    <div className="flex items-center gap-1.5" title={title}>
      <Icon className={`h-4 w-4 ${ok ? "text-accent" : "text-white/30"}`} />
      <Dot ok={ok} />
      <span className="max-w-[7.5rem] truncate text-sm tracking-wide text-white/55">{label}</span>
    </div>
  );
}

const MODE_TAG = {
  home: { label: "HOME", dot: "bg-accent", text: "text-accent/80" },
  draft: { label: "LIVE DRAFT", dot: "bg-ally", text: "text-ally/85" },
  postlock: { label: "LOCKED", dot: "bg-good", text: "text-good/85" },
};

export default function StatusStrip({ state, mode, api }) {
  const lcu = state?.lcu || {};
  const ollama = state?.ollama || {};
  const sync = state?.sync || {};
  const patch = state?.cache?.patch || "—";
  const tag = MODE_TAG[mode] || MODE_TAG.home;
  const syncing = sync.running;
  const version = useAppVersion();

  return (
    <header className="flex h-8 shrink-0 items-center gap-3 border-b border-line px-3">
      <div className="flex items-center gap-2">
        <span className="font-display text-sm font-bold tracking-[0.12em] text-white/90">SYLQON</span>
        {version && (
          <button
            type="button"
            onClick={() => window.sylqonUpdater?.check?.()}
            className="font-mono text-2xs tracking-wide text-white/35 transition-colors hover:text-white/70"
            title="Installed app version — click to check for updates"
          >
            v{version}
          </button>
        )}
      </div>

      <div className="h-4 w-px bg-line" />

      <span className={`flex items-center gap-1.5 font-display text-xs font-semibold tracking-[0.08em] ${tag.text}`}
            title="Aktuális játékfázis (a megtekintett nézet ettől eltérhet)">
        <span className={`h-1.5 w-1.5 rounded-full ${tag.dot}`} />
        {tag.label}
      </span>

      {api && api.online === false && (
        <span
          className="rounded border border-bad/50 bg-bad/15 px-1.5 py-px font-display text-xs font-semibold tracking-[0.08em] text-bad"
          title={api.lastError?.message
            ? `A backend nem elérhető: ${api.lastError.message}`
            : "A backend (http://127.0.0.1:8077) nem válaszol"}
        >
          BACKEND OFFLINE
        </span>
      )}

      <div className="ml-auto flex items-center gap-3">
        {syncing && (
          <div
            className="flex items-center gap-1.5 font-mono text-xs tracking-wide text-accent/80"
            title={sync.detail || "Auto-syncing the champion universe from op.gg"}
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {sync.total ? `SYNC ${sync.done}/${sync.total}` : "SYNC…"}
          </div>
        )}
        <Stat icon={RadioTower} ok={lcu.connected} label={lcu.summoner || (lcu.connected ? "connected" : "no client")}
              title="League client connection" />
        <Stat icon={Cpu} ok={ollama.available} label={ollama.processing ? "thinking…" : (ollama.model || "Ollama")}
              title="Ollama LLM" />
        <span className="font-mono text-sm tracking-wide text-white/50">{patch}</span>
      </div>
    </header>
  );
}
