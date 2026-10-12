// Build-time settings from the root config.yaml (frontend/vite.config.js).

// A public deployment: debug features (e.g. the editor's JSON view) are hidden.
export const PUBLIC = typeof __PUBLIC__ !== "undefined" && __PUBLIC__;

// The grid editor's settings (config.yaml `editor`), with the defaults when the build has none.
const editor = typeof __EDITOR__ !== "undefined" ? __EDITOR__ : {};
export const EDITOR = {
  reference_grid: editor.reference_grid ?? { columns: 12, rows: 8 },
  reference_inventory: editor.reference_inventory ?? 4,
};
