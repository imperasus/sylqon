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
