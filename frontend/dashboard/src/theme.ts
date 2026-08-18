// Raw color values mirroring index.css's :root palette — kept here as the single source
// of truth for the handful of places (Recharts props, lightweight-charts config) that
// need actual color strings instead of CSS custom properties. Canvas-based chart
// libraries don't resolve var(--x) the way DOM elements do, so these can't just
// reference the CSS variables directly; keep the two in sync when the palette changes.
export const theme = {
  border: "#262a31",
  textMuted: "#848e9c",
  textSecondary: "#b7bdc6",
  surface: "#181b20",
  accent: "#f0b90b",
  positive: "#0ecb81",
  negative: "#f6465d",
} as const;
