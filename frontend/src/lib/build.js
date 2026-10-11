// Build-time settings from the root config.yaml (frontend/vite.config.js).

// A public deployment: debug features (e.g. the editor's JSON view) are hidden.
export const PUBLIC = typeof __PUBLIC__ !== "undefined" && __PUBLIC__;
