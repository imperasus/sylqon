const DD = "https://ddragon.leagueoflegends.com/cdn";

export const splashUrl = (slug) => `${DD}/img/champion/splash/${slug}_0.jpg`;
export const loadingUrl = (slug) => `${DD}/img/champion/loading/${slug}_0.jpg`;
export const squareUrl = (patch, slug) => `${DD}/${patch}/img/champion/${slug}.png`;
export const itemUrl = (patch, id) => `${DD}/${patch}/img/item/${id}.png`;
export const abilityIconUrl = (patch, imageFull) => `${DD}/${patch}/img/spell/${imageFull}`;
export const passiveIconUrl = (patch, imageFull) => `${DD}/${patch}/img/passive/${imageFull}`;

const SPELL_FILES = {
  Flash: "SummonerFlash",
  Heal: "SummonerHeal",
  Ghost: "SummonerHaste",
  Cleanse: "SummonerBoost",
  Exhaust: "SummonerExhaust",
  Barrier: "SummonerBarrier",
  Ignite: "SummonerDot",
  Teleport: "SummonerTeleport",
  Smite: "SummonerSmite",
};
export const spellUrl = (patch, name) =>
  `${DD}/${patch}/img/spell/${SPELL_FILES[name] || "SummonerFlash"}.png`;

export const ROLE_ORDER = ["top", "jungle", "middle", "bottom", "utility"];
export const ROLE_LABELS = {
  top: "TOP",
  jungle: "JNG",
  middle: "MID",
  bottom: "BOT",
  utility: "SUP",
};
export const ROLE_NAMES = {
  top: "Top",
  jungle: "Jungle",
  middle: "Mid",
  bottom: "Bot (ADC)",
  utility: "Support",
};

export const THREAT_LABELS = {
  heavy_cc: "Heavy CC",
  suppression: "Suppression",
  burst_ad: "AD Burst",
  burst_ap: "AP Burst",
  heavy_healing: "High Sustain",
  poke: "Poke",
  tank: "Fortified",
};

export const DAMAGE_COLORS = {
  AD: "text-amber border-amber/40",
  AP: "text-mana border-mana/40",
  Mixed: "text-arcane border-arcane/40",
};

/* op.gg meta tiers — 0/1 are S/S+, fade down to 5. Flat chips on the Graphite
   Volt palette (no neon glow); the elite tiers just carry a stronger accent. */
export const TIER_STYLE = {
  0: { label: "S+", cls: "bg-tier1/20 text-tier1 border-tier1/55", glow: "" },
  1: { label: "S", cls: "bg-tier1/14 text-tier1 border-tier1/40", glow: "" },
  2: { label: "A", cls: "bg-tier2/14 text-tier2 border-tier2/40", glow: "" },
  3: { label: "B", cls: "bg-white/8 text-white/60 border-white/15", glow: "" },
  4: { label: "C", cls: "bg-white/5 text-white/40 border-white/10", glow: "" },
  5: { label: "D", cls: "bg-white/5 text-white/30 border-white/10", glow: "" },
};

export const pct = (x) => `${Math.round((x || 0) * 100)}%`;

/* --- Win-rate confidence gating -------------------------------------------
   A raw win rate over a handful of games is mostly noise: 6/10 and 4/10 are
   statistically indistinguishable from a coin flip. To avoid painting a player
   "good" (green) or "bad" (red) on thin evidence, a WR is only colored when the
   Wilson score interval around it excludes 50%. Small samples produce wide
   intervals that straddle 50%, so they stay neutral — honest, not decorative. */
export const WILSON_Z = 1.645;    // ~90% two-sided: a "lean", not a hard claim
export const WR_SAMPLE_FLOOR = 20; // below this, flag the WR as a small sample

/* Wilson score interval [lo, hi] for `wins` out of `n` games. */
export function wilsonInterval(wins, n, z = WILSON_Z) {
  if (!n || n <= 0) return null;
  const p = wins / n;
  const z2 = z * z;
  const denom = 1 + z2 / n;
  const center = (p + z2 / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denom;
  return [center - half, center + half];
}

/* Tailwind text tone for a win rate, gated by confidence. `wr` is a 0..1 rate,
   `n` the game count it was measured over. Neutral until the interval clears
   50% one way — so a 60%-over-10-games WR reads plainly, not as "good". */
export function wrTone(wr, n) {
  if (wr == null || !n) return "text-white/35";
  const ci = wilsonInterval(Math.round(wr * n), n);
  if (!ci) return "text-white/35";
  const [lo, hi] = ci;
  if (lo > 0.5) return "text-good";
  if (hi < 0.5) return "text-bad";
  return "text-white/45";  // real rate, but not distinguishable from a coin flip
}

/* " · small sample" suffix for a WR tooltip when the game count is too thin to
   trust, else "". Keeps the qualifier text in one place. */
export const sampleNote = (n) => ((n || 0) < WR_SAMPLE_FLOOR ? " · small sample" : "");

/* Champion-pool entry label. Entries measured from recent games cite games + win
   rate; mastery-only entries (champions the player owns but hasn't played in the
   scouted window) cite mastery and say so, rather than rendering a fabricated
   "0g 0%" that reads as a terrible record. */
export function poolEntryLabel(c) {
  if (!c) return "";
  const name = c.champion || "?";
  if (c.games) {
    return `${name} · ${c.games}g${c.win_rate != null ? ` ${pct(c.win_rate)}` : ""}`;
  }
  if (c.mastery_points != null) {
    const k = (c.mastery_points / 1000).toFixed(0);
    return `${name} · mastery M${c.mastery_level || "?"} ${k}k — not in recent games`;
  }
  return name;
}

/* How far above their OWN baseline a player's recent-window deaths must sit
   before a losing streak reads as tilt rather than ordinary variance. A 3-loss
   streak alone happens by chance often enough that it proves nothing. */
export const DEATH_TILT_MARGIN = 0.5;

/* Evidence test behind the tilt read: recent-window deaths up versus the
   player's own long-run average. Returns false when either figure is missing. */
export function dyingMoreThanUsual(p) {
  const recent = p?.recent_form?.avg_deaths;
  const base = p?.avg_kda?.deaths;
  return recent != null && base != null && recent > base + DEATH_TILT_MARGIN;
}

/* Rank-adaptive performance benchmark lookup. `benchmarks` is the /api/benchmarks
   payload ({ table, tier_to_band, default_band }). Returns the metric target for
   a role at the player's rank band — or the default (middle) band when the rank
   is unknown, so an unranked player still gets a sane, non-punishing bar.
   Returns null only when the table itself hasn't loaded. */
export function benchTarget(benchmarks, role, tier, metric) {
  const table = benchmarks?.table;
  if (!table) return null;
  const band = benchmarks.tier_to_band?.[(tier || "").toUpperCase()] || benchmarks.default_band;
  const row = table[band]?.[role] || table[benchmarks.default_band]?.[role];
  return row?.[metric] ?? null;
}
