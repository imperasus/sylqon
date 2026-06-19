import { EyeOff, Users } from "lucide-react";
import { ROLE_LABELS, pct } from "../assets.js";
import { Bar, ChampPortrait, Chip, Panel } from "./shared.jsx";

/* Playstyle tag → chip tone, so the read is glanceable. */
const TAG_TONE = {
  aggressive: "enemy",
  "carry-threat": "amber",
  "one-trick": "amber",
  "farm-focused": "accent",
  playmaker: "ally",
  calculated: "good",
  frontliner: "ally",
  "vision-control": "accent",
};

/* Recent-form streak as a short signed label (3W / 4L), else null. */
function streakLabel(streak) {
  if (!streak || Math.abs(streak) < 3) return null;
  return `${Math.abs(streak)}${streak > 0 ? "W" : "L"}`;
}

function ScoutCard({ p, patch }) {
  const roleLabel = ROLE_LABELS[p.position] || ROLE_LABELS[p.main_role] || "FLEX";

  if (p.hidden) {
    return (
      <div className="frost flex min-h-[44px] items-center gap-2 px-2.5 py-1.5 opacity-45">
        <EyeOff className="h-4 w-4 text-white/35" />
        <span className="truncate text-[12px] text-white/55">{p.name}</span>
        <span className="ml-auto text-[10px] font-bold tracking-widest text-white/30">{roleLabel} · HIDDEN</span>
      </div>
    );
  }

  const form = p.recent_form || {};
  const comfort = p.comfort;
  const streak = streakLabel(form.streak);
  const pool = (p.champion_pool || []).slice(0, 4);

  return (
    <div className={`frost ${p.is_self ? "frost-accent" : ""} flex flex-col gap-1.5 px-2.5 py-2`}>
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-bold tracking-widest text-ally/75">{roleLabel}</span>
        <span className="truncate text-[13px] font-bold text-white/90">{p.name}</span>
        {p.is_self && <span className="text-[9px] font-bold tracking-widest text-accent">YOU</span>}
        {comfort?.champion && (
          <span className="ml-auto flex items-center gap-1" title={`Mains ${comfort.champion} — ${pct(comfort.share)} of recent games, ${pct(comfort.win_rate)} WR`}>
            <ChampPortrait slug={comfort.slug} patch={patch} size="h-6 w-6" round title={comfort.champion} />
            <span className="text-[11px] text-white/55">{pct(comfort.share)}</span>
          </span>
        )}
      </div>

      {(p.playstyle_tags || []).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {p.playstyle_tags.map((t) => (
            <Chip key={t} tone={TAG_TONE[t] || "muted"}>{t}</Chip>
          ))}
        </div>
      )}

      {form.games > 0 && (
        <div className="flex items-center gap-2">
          <div className="flex-1"><Bar value={(form.win_rate || 0) * 100} tone={form.win_rate >= 0.5 ? "good" : "enemy"} /></div>
          <span className="shrink-0 font-mono text-[11px] tabular-nums text-white/55">
            {pct(form.win_rate)} <span className="text-white/30">/ {form.games}</span>
          </span>
          {streak && (
            <span className={`shrink-0 text-[10px] font-bold ${form.streak > 0 ? "text-good" : "text-bad"}`}>{streak}</span>
          )}
        </div>
      )}

      {pool.length > 0 && (
        <div className="flex items-center gap-1" title="Most-played recent champions">
          {pool.map((c) => (
            <ChampPortrait key={c.champion_id} slug={c.slug} patch={patch} size="h-6 w-6" title={`${c.champion} — ${c.games}g, ${pct(c.win_rate)} WR`} />
          ))}
        </div>
      )}
    </div>
  );
}

/* Pre-game lobby scouting: playstyle fingerprints of identifiable teammates.
   Renders nothing until a roster has been profiled. */
export default function LobbyScoutPanel({ scout, patch }) {
  const players = scout?.players || [];
  // Hide the local player; only show teammates worth scouting (or hidden cards).
  const cards = players.filter((p) => !p.is_self && (p.games_analyzed > 0 || p.hidden));
  if (cards.length === 0) return null;

  return (
    <Panel title="LOBBY SCOUT" icon={Users} accent="ally" className="gap-1.5">
      {cards.map((p, i) => (
        <ScoutCard key={p.name ? `${p.name}-${i}` : i} p={p} patch={patch} />
      ))}
    </Panel>
  );
}
