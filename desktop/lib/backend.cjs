"use strict";
const { EventEmitter } = require("node:events");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const { backendOrigin, token } = require("./security.cjs");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function startupCancelled() {
  const error = new Error(
    "Desktop startup was cancelled by a lifecycle request.",
  );
  error.code = "STARTUP_CANCELLED";
  return error;
}
const startupErrors = {
  configuration: "The desktop launch configuration is invalid.",
  storage:
    "The user data or state directory is unavailable. Check its permissions and available space.",
  database:
    "The database could not open or migrate. Existing data was retained; another application instance may own this workspace.",
  resources:
    "Bundled application resources are missing. Reinstall the desktop application.",
  bind: "A private local listening socket could not be allocated.",
  runtime: "The local processing service could not start.",
  timeout:
    "The local processing service did not pass its health check in time.",
};

function request(
  origin,
  secret,
  route,
  {
    method = "GET",
    body,
    csrf,
    timeout = 8000,
    maximum = 20 * 1024 * 1024,
    binary = false,
  } = {},
) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const req = http.request(
      new URL(route, origin),
      {
        method,
        headers: {
          "X-Desktop-Token": secret,
          ...(csrf ? { "X-CSRF-Token": csrf } : {}),
          ...(payload
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(payload),
              }
            : {}),
        },
      },
      (res) => {
        const chunks = [];
        let bytes = 0;
        res.on("data", (chunk) => {
          bytes += chunk.length;
          if (bytes > maximum)
            req.destroy(
              new Error("Desktop response exceeded its safety limit."),
            );
          else chunks.push(chunk);
        });
        res.on("end", () => {
          const buffer = Buffer.concat(chunks);
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(
              new Error(`The local backend returned HTTP ${res.statusCode}.`),
            );
            return;
          }
          try {
            resolve(binary ? buffer : JSON.parse(buffer.toString("utf8")));
          } catch {
            reject(
              new Error("The local backend returned an invalid response."),
            );
          }
        });
        res.on("error", reject);
      },
    );
    req.setTimeout(timeout, () =>
      req.destroy(new Error("The local backend did not respond in time.")),
    );
    req.on("error", reject);
    req.end(payload);
  });
}
class BackendSupervisor extends EventEmitter {
  constructor(options) {
    super();
    this.options = options;
    this.child = null;
    this.origin = null;
    this.secret = null;
    this.ready = null;
    this.status = "idle";
    this.intentional = false;
    this.generation = 0;
  }
  state(status, message, details = "") {
    this.status = status;
    this.emit("state", { status, message, details });
  }
  async start() {
    if (this.child)
      throw new Error("The previous backend must stop before it can restart.");
    const generation = ++this.generation;
    this.intentional = false;
    this.origin = null;
    this.ready = null;
    this.secret = token();
    const temporary = await fs.mkdtemp(
      path.join(os.tmpdir(), "anki-generator-start-"),
    );
    await fs.chmod(temporary, 0o700);
    if (generation !== this.generation || this.intentional) {
      await fs.rm(temporary, { recursive: true, force: true });
      throw startupCancelled();
    }
    const startup = path.join(temporary, "ready.json");
    this.state("starting", "Starting your private workspace…");
    if (generation !== this.generation || this.intentional) {
      await fs.rm(temporary, { recursive: true, force: true });
      throw startupCancelled();
    }
    const args = [
      ...(this.options.args || []),
      "--data-directory",
      this.options.paths.data,
      "--state-directory",
      this.options.paths.state,
      "--startup-file",
      startup,
      "--parent-pid",
      String(process.pid),
    ];
    let spawnError;
    const child = (this.options.spawn || spawn)(this.options.command, args, {
      cwd: this.options.paths.state,
      env: {
        ...process.env,
        ...this.options.env,
        ANKI_GENERATOR_DESKTOP_TOKEN: this.secret,
      },
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32",
      windowsHide: true,
    });
    this.child = child;
    this.options.log?.write("backend-spawned", { pid: child.pid });
    child.once("error", (error) => {
      spawnError = error;
      if (this.child === child) this.child = null;
    });
    for (const stream of ["stdout", "stderr"])
      child[stream]?.on("data", (chunk) => {
        this.options.log?.write("backend-output", {
          stream,
          bytes: chunk.length,
        });
      });
    child.once("exit", (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      this.origin = null;
      this.options.log?.write("backend-exit", {
        code,
        signal,
        intentional: this.intentional,
      });
      // Startup failure owns its actionable error. A later child exit must not
      // replace it with the generic recovery message for a previously ready app.
      if (
        !this.intentional &&
        generation === this.generation &&
        this.status === "ready"
      )
        this.state(
          "failed",
          "The local processing service stopped unexpectedly.",
          "Your saved courses and completed checkpoints remain available. Restart the service to recover interrupted tasks.",
        );
      this.emit("exit", { code, signal, intentional: this.intentional });
    });
    const deadline = Date.now() + (this.options.startupTimeout || 120000);
    try {
      while (Date.now() < deadline) {
        if (generation !== this.generation || this.intentional)
          throw startupCancelled();
        if (spawnError)
          throw new Error(
            `The bundled processing service could not start (${spawnError.code || "launch error"}).`,
          );
        let info;
        try {
          info = JSON.parse(await fs.readFile(startup, "utf8"));
        } catch (error) {
          if (error.code !== "ENOENT" && !(error instanceof SyntaxError))
            throw error;
        }
        if (info?.status === "error")
          throw new Error(startupErrors[info.code] || startupErrors.runtime);
        if (spawnError)
          throw new Error(
            `The bundled processing service could not start (${spawnError.code || "launch error"}).`,
          );
        if (!this.child)
          throw new Error(
            "The processing service exited before its workspace was ready.",
          );
        if (info) {
          const origin = backendOrigin(
            info.origin || `http://${info.host}:${info.port}`,
          );
          if (
            info.status !== "ready" ||
            info.host !== "127.0.0.1" ||
            info.pid !== child.pid ||
            Number(info.port) !== Number(new URL(origin).port)
          )
            throw new Error(
              "The processing service published an invalid startup record.",
            );
          const health = await request(origin, this.secret, "/api/health", {
            timeout: 4000,
            maximum: 65536,
          });
          if (health.status !== "ok")
            throw new Error(
              "The processing service did not pass its readiness check.",
            );
          if (generation !== this.generation || this.intentional)
            throw startupCancelled();
          if (this.child !== child)
            throw new Error("The processing service stopped during startup.");
          this.origin = origin;
          this.ready = { ...info, origin, health };
          this.state("ready", "Your workspace is ready.");
          this.emit("ready", this.ready);
          return this.ready;
        }
        await wait(100);
      }
      throw new Error(
        "The local processing service is taking longer than expected to start. Inspect diagnostics and retry.",
      );
    } catch (error) {
      if (
        error.code === "STARTUP_CANCELLED" ||
        generation !== this.generation ||
        this.intentional
      )
        throw startupCancelled();
      this.options.log?.write("backend-startup-failed", {
        message: error.message,
      });
      this.state(
        "failed",
        error.message,
        "Inspect or export diagnostics, check that your data directory is writable, then retry.",
      );
      throw error;
    } finally {
      await fs.rm(temporary, { recursive: true, force: true }).catch(() => {});
    }
  }
  async call(route, options) {
    if (!this.origin || !this.secret)
      throw new Error("The local processing service is not ready.");
    return request(this.origin, this.secret, route, options);
  }
  async csrf() {
    return (await this.call("/api/bootstrap", { maximum: 8 * 1024 * 1024 }))
      .csrf_token;
  }
  async stop({ timeout = 215000, force = false } = {}) {
    this.generation += 1;
    this.intentional = true;
    const child = this.child;
    if (!child) return true;
    this.state(
      "stopping",
      "Finishing current operations and saving checkpoints…",
    );
    if (force) {
      this.signal(child, "SIGKILL");
    } else {
      this.signal(child, "SIGTERM");
    }
    const deadline = Date.now() + timeout;
    while (this.child === child && Date.now() < deadline) await wait(100);
    return this.child !== child;
  }
  signal(child, signal) {
    try {
      if (signal === "SIGKILL" && process.platform !== "win32" && child.pid)
        process.kill(-child.pid, signal);
      else child.kill(signal);
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }
  async waitForExit(milliseconds = 215000) {
    const child = this.child;
    if (!child) return true;
    const end = Date.now() + milliseconds;
    while (this.child === child && Date.now() < end) await wait(100);
    return !this.child;
  }
}
module.exports = { BackendSupervisor, request };
