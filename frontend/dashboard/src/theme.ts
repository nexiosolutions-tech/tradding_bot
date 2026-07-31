// Raw color values mirroring index.css's :root palette — kept here as the single source
// of truth for the handful of places (Recharts props, lightweight-charts config) that
// need actual color strings instead of CSS custom properties. Canvas-based chart
// libraries don't resolve var(--x) the way DOM elements do, so these can't just
// reference the CSS variables directly; keep the two in sync when the palette changes.
export const theme = {
  border: "#e8e3d8",
  textMuted: "#8b8474",
  textSecondary: "#5c574a",
  surface: "#ffffff",
  accent: "#b45309",
} as const;
