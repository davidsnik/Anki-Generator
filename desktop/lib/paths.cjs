"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function absoluteDirectory(value, fallback) {
  if (!value) return fallback;
  if (!path.isAbsolute(value) || value.includes("\0"))
    throw new Error("Desktop directories must be absolute paths.");
  return path.resolve(value);
}
function xdgDirectory(value, fallback) {
  return typeof value === "string" &&
    path.isAbsolute(value) &&
    !value.includes("\0")
    ? path.resolve(value)
    : fallback;
}
function desktopPaths(env = process.env, home = os.homedir(), overrides = {}) {
  const data = absoluteDirectory(
    overrides.data,
    path.join(
      xdgDirectory(env.XDG_DATA_HOME, path.join(home, ".local/share")),
      "anki-generator",
    ),
  );
  const state = absoluteDirectory(
    overrides.state,
    path.join(
      xdgDirectory(env.XDG_STATE_HOME, path.join(home, ".local/state")),
      "anki-generator",
    ),
  );
  return {
    data,
    state,
    logs: path.join(state, "logs"),
    chromium: path.join(state, "electron"),
    cache: path.join(
      xdgDirectory(env.XDG_CACHE_HOME, path.join(home, ".cache")),
      "anki-generator",
      "chromium",
    ),
  };
}
function prepareDirectories(paths) {
  for (const directory of Object.values(paths))
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
}
function visibleBounds(saved, displays) {
  const width = Math.max(900, Math.min(Number(saved?.width) || 1320, 2560));
  const height = Math.max(640, Math.min(Number(saved?.height) || 900, 1800));
  const x = Number(saved?.x),
    y = Number(saved?.y);
  const visible =
    Number.isFinite(x) &&
    Number.isFinite(y) &&
    displays.some(
      ({ workArea: a }) =>
        x + 100 < a.x + a.width &&
        x + width - 100 > a.x &&
        y + 80 < a.y + a.height &&
        y + height - 80 > a.y,
    );
  return {
    width,
    height,
    ...(visible ? { x, y } : {}),
    maximized: saved?.maximized === true,
  };
}
module.exports = { desktopPaths, prepareDirectories, visibleBounds };
