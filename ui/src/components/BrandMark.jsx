/* "Signal S" — three offset equalizer bars forming an S silhouette, one amber
   data-point dot. The same geometry is mirrored in the desktop icon
   (sylqon-desktop/scripts/gen-icon.mjs) and the favicon. */
export default function BrandMark({ className = "h-5 w-5", title = "Sylqon" }) {
  return (
    <svg viewBox="0 0 24 24" className={className} role="img" aria-label={title}>
      <title>{title}</title>
      <rect x="7" y="3" width="14" height="4" rx="1" fill="var(--color-accent)" />
      <rect x="3" y="10" width="18" height="4" rx="1" fill="var(--color-accent)" />
      <rect x="3" y="17" width="14" height="4" rx="1" fill="var(--color-accent)" />
      <circle cx="19.5" cy="19" r="2" fill="var(--color-amber)" />
    </svg>
  );
}
