"use strict";
const crypto = require("node:crypto");
const path = require("node:path");
function backendOrigin(value) {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    !url.port ||
    Number(url.port) < 1 ||
    Number(url.port) > 65535 ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error(
      "The backend did not publish a valid private loopback address.",
    );
  return url.origin;
}
function sameOrigin(value, origin) {
  try {
    return new URL(value).origin === origin;
  } catch {
    return false;
  }
}
function externalLink(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
function injectToken(url, headers, origin, token) {
  const result = Object.fromEntries(
    Object.entries(headers).filter(
      ([name]) => name.toLowerCase() !== "x-desktop-token",
    ),
  );
  if (origin && sameOrigin(url, origin)) result["X-Desktop-Token"] = token;
  return result;
}
function trustedFrame(event, window, origins) {
  return (
    !!window &&
    !window.isDestroyed() &&
    event.sender === window.webContents &&
    event.senderFrame === window.webContents.mainFrame &&
    origins.has(event.senderFrame?.origin)
  );
}
function safeFilename(value) {
  return (
    String(value || "download")
      .replace(/[\\/\x00-\x1f\x7f]/g, "_")
      .slice(0, 180) || "download"
  );
}
function downloadOpenable(file) {
  const allowed = new Set([
    ".apkg",
    ".json",
    ".csv",
    ".zip",
    ".pdf",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
  ]);
  return (
    allowed.has(path.extname(file.filename).toLowerCase()) &&
    allowed.has(path.extname(file.path).toLowerCase())
  );
}
function token() {
  return crypto.randomBytes(32).toString("base64url");
}
module.exports = {
  backendOrigin,
  sameOrigin,
  externalLink,
  injectToken,
  trustedFrame,
  safeFilename,
  downloadOpenable,
  token,
};
