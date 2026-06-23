import { useLayoutEffect, useState } from "react";

/* Measures a flex container and returns how many fixed-height rows fit inside it,
   so dense lists can render exactly what's visible — no inner scrollbar — and push
   the remainder behind a "+N more" / pager affordance.

   Row/gap heights are given in REM (the app is rem-based and rides the fluid root
   font-size), and converted to px against the live root size, so the fit stays
   correct at every window size.

   A *callback ref* (the first return value) is used instead of a plain ref so the
   ResizeObserver attaches correctly even when the measured element mounts later
   than the hook (e.g. a panel that first renders a loading/empty state, then swaps
   in the list once data arrives).

   Usage:
     const [listRef, fit] = useFitCount({ rowRem: 2.3, gapRem: 0, max: rows.length });
     <div ref={listRef} className="min-h-0 flex-1 overflow-hidden">
       {rows.slice(0, fit).map(...)}
     </div>
*/
export function useFitCount({ rowRem, gapRem = 0, min = 1, max = Infinity, safety = 0 }) {
  const [count, setCount] = useState(min);
  const [width, setWidth] = useState(0);
  const [node, setNode] = useState(null);

  useLayoutEffect(() => {
    if (!node) return;

    const measure = () => {
      const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      const h = node.clientHeight;
      const row = rowRem * rootPx;
      const gap = gapRem * rootPx;
      setWidth(node.clientWidth);
      if (h <= 0 || row <= 0) return;
      // (h + gap) / (row + gap): the last row carries no trailing gap. `safety`
      // holds back N rows so a sub-pixel mismeasure never reintroduces a scrollbar.
      const raw = Math.floor((h + gap) / (row + gap)) - safety;
      setCount(Math.max(min, Math.min(max, raw)));
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, [node, rowRem, gapRem, min, max, safety]);

  // width (px) is returned as a 3rd element so callers can also fan rows into
  // multiple columns on wide screens; existing [ref, count] destructures ignore it.
  return [setNode, count, width];
}

/* Reports a measured element's height in REM (against the live root font-size),
   for density decisions where rows aren't uniform — e.g. a fixed-count column
   (5 player cards) that adapts per-card detail to the space instead of scrolling.
   Returns a callback ref + the height in rem (0 until measured). */
export function useElementRem() {
  const [node, setNode] = useState(null);
  const [rem, setRem] = useState(0);

  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => {
      const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      setRem(node.clientHeight / rootPx);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);

  return [setNode, rem];
}

/* Reliable viewport media-query match (fires on every resize, unlike a per-node
   ResizeObserver). Used for coarse layout switches like fanning a list into two
   columns only on wide/ultrawide windows. */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches
  );
  useLayoutEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
