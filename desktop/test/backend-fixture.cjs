"use strict";
// Explicit test child, never packaged or available to the production launcher.
const http = require("node:http");
const fs = require("node:fs");
const args = process.argv.slice(2);
const get = (key) => args[args.indexOf(key) + 1];
const mode = process.env.FIXTURE_MODE || "ready";
const startup = get("--startup-file");
if (mode === "database-delayed-exit") {
  fs.writeFileSync(
    startup,
    JSON.stringify({ status: "error", pid: process.pid, code: "database" }),
    { mode: 0o600 },
  );
  // Reproduce the frozen backend reporting its error before process teardown.
  setTimeout(() => process.exit(2), 500);
  return;
}
if (mode === "storage") {
  fs.writeFileSync(
    startup,
    JSON.stringify({ status: "error", pid: process.pid, code: "storage" }),
    { mode: 0o600 },
  );
  process.exit(2);
}
const server = http.createServer((req, res) => {
  if (
    req.headers["x-desktop-token"] !== process.env.ANKI_GENERATOR_DESKTOP_TOKEN
  ) {
    res.writeHead(403);
    res.end("{}");
    return;
  }
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ status: "ok", version: "fixture" }));
});
server.listen(0, "127.0.0.1", () => {
  const port = server.address().port;
  if (mode === "gated-ready") return;
  fs.writeFileSync(
    startup,
    JSON.stringify({
      status: "ready",
      host: mode === "remote" ? "0.0.0.0" : "127.0.0.1",
      port,
      origin:
        mode === "remote"
          ? `http://example.com:${port}`
          : `http://127.0.0.1:${port}`,
      pid: mode === "wrong-pid" ? 1 : process.pid,
      version: "fixture",
    }),
    { mode: 0o600 },
  );
});
process.on("SIGTERM", () => {
  if (mode !== "slow-stop") server.close(() => process.exit(0));
});
