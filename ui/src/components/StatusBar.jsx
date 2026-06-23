import { useEffect, useState } from "react";
import { Cpu, Loader2, Play, RadioTower, Square, Zap } from "lucide-react";
import { Button } from "./shared.jsx";

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
  home: { label: "HOME", tone: "text-accent/80 border-accent/35" },
  draft: { label: "LIVE DRAFT", tone: "text-ally/85 border-ally/40" },
  postlock: { label: "LOCKED", tone: "text-good/85 border-good/40" },
};

export default function StatusBar({ state, mode, act, api, demoActive }) {
  const lcu = state?.lcu || {};
  const ollama = state?.ollama || {};
  const sync = state?.sync || {};
  const patch = state?.cache?.patch || "—";
  const tag = MODE_TAG[mode] || MODE_TAG.home;
  const syncing = sync.running;
  const version = useAppVersion();

  return (
    <header className="frost edge-accent flex items-center gap-3 px-3 py-1.5">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-accent" />
        <span className="font-display text-md font-bold tracking-[0.28em] text-white/90">SYLQON</span>
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
      <span className={`rounded border px-1.5 py-px font-display text-xs font-bold tracking-[0.2em] ${tag.tone}`}>
        {tag.label}
      </span>

      <div className="mx-1 h-4 w-px bg-white/10" />

      <Stat icon={RadioTower} ok={lcu.connected} label={lcu.summoner || (lcu.connected ? "connected" : "no client")}
            title="League client connection" />
      <Stat icon={Cpu} ok={ollama.available} label={ollama.processing ? "thinking…" : (ollama.model || "Ollama")}
            title="Ollama LLM" />
      <span className="font-mono text-sm tracking-wide text-white/50">{patch}</span>

      <div className="ml-auto flex items-center gap-2">
        {syncing && (
          <div
            className="flex items-center gap-1.5 rounded border border-accent/35 px-2 py-1 font-display text-sm font-bold tracking-[0.18em] text-accent/80"
            title={sync.detail || "Auto-syncing the champion universe from op.gg"}
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            {sync.total ? `SYNC ${sync.done}/${sync.total}` : "SYNC…"}
          </div>
        )}
        <Button
          variant={demoActive ? "danger" : "ghost"}
          icon={demoActive ? Square : Play}
          onClick={() => act?.(() => (demoActive ? api.stopDemo() : api.startDemo()))}
          title="Toggle a synthetic lobby to preview the cockpit"
        >
          {demoActive ? "STOP" : "DEMO"}
        </Button>
      </div>
    </header>
  );
}
