import { useEffect, useMemo, useState } from "react";

/**
 * Derives the list of build variants from the polled `state.build` and tracks
 * which one is active (shown in the main panels + imported in the client).
 *
 * The backend publishes `build.variants` (variant 0 = the auto-imported
 * primary). Clicking an alternative imports it via `injectVariant(index)`,
 * which overwrites the single "Sylqon Meta" set in the client.
 */
export function useBuildVariants(build, injectVariant) {
  const variants = useMemo(() => {
    if (build?.variants?.length) return build.variants;
    // Back-compat: no variants array yet — treat the optimized build as primary.
    if (build?.optimized) {
      return [{ ...build.optimized, priority: 0, primary: true, name: "Recommended" }];
    }
    return [];
  }, [build]);

  const [activeIndex, setActiveIndex] = useState(0);
  const [importing, setImporting] = useState(false);

  // Keep the active index in range as variants (re)load.
  useEffect(() => {
    if (activeIndex >= variants.length) setActiveIndex(0);
  }, [variants.length, activeIndex]);

  const importVariant = async (index) => {
    if (index === activeIndex || index < 0 || index >= variants.length) {
      setActiveIndex(index);
      return;
    }
    setActiveIndex(index); // optimistic: panels swap immediately
    setImporting(true);
    try {
      await injectVariant?.(index);
    } finally {
      setImporting(false);
    }
  };

  const active = variants[activeIndex] || variants[0] || null;
  return { variants, active, activeIndex, importVariant, importing };
}
