"use strict";
const fs = require("node:fs");
const path = require("node:path");
function redact(value, secrets = []) {
  let text = String(value);
  for (const secret of secrets.filter(Boolean))
    text = text.split(secret).join("[redacted]");
  return text
    .replace(/\bsk-[A-Za-z0-9_-]{6,}\b/g, "[redacted]")
    .replace(/(bearer\s+)[\w.\-]+/gi, "$1[redacted]")
    .replace(
      /(["']?(?:api[_-]?key|authorization|desktop[_-]?token)["']?\s*[:=]\s*)["']?[^\s,"'}]+["']?/gi,
      "$1[redacted]",
    );
}
class DesktopLog {
  constructor(directory, secrets = []) {
    this.directory = directory;
    this.secrets = secrets;
    this.file = path.join(directory, "desktop.log");
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  }
  write(event, details = {}) {
    try {
      if (
        fs.existsSync(this.file) &&
        fs.statSync(this.file).size > 1024 * 1024
      ) {
        for (let i = 2; i >= 1; i--) {
          const old = i === 1 ? this.file : `${this.file}.${i - 1}`;
          if (fs.existsSync(old)) fs.renameSync(old, `${this.file}.${i}`);
        }
      }
      fs.appendFileSync(
        this.file,
        redact(
          JSON.stringify({ time: new Date().toISOString(), event, ...details }),
          this.secrets,
        ) + "\n",
        { mode: 0o600 },
      );
    } catch {
      /* Diagnostics must not prevent safe shutdown. */
    }
  }
  entries() {
    try {
      return redact(
        fs.readFileSync(this.file, "utf8").slice(-250000),
        this.secrets,
      )
        .split("\n")
        .filter(Boolean)
        .slice(-400);
    } catch {
      return [];
    }
  }
}
module.exports = { DesktopLog, redact };
