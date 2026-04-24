// DeepVista catalog sync — opencode plugin.
//
// Wires the `session.created` hook to run `deepvista skill sync`, writing
// stubs into the opencode plugin's own skills directory so they surface as
// plugin-managed rather than user skills.
//
// opencode exposes `ctx.pluginDir` (or equivalent path) as the directory this
// plugin was loaded from. We target `${pluginDir}/skills/` when available;
// otherwise fall back to `~/.config/opencode/skills/` which opencode reads
// natively, and finally `~/.claude/skills/` for cross-agent compat.
//
// Install: either
//   1. `npm install -g @deepvista/opencode-plugin`, or
//   2. copy this dir into `~/.config/opencode/plugins/deepvista/`
// then add to `~/.config/opencode/opencode.json`:
//     { "plugin": ["@deepvista/opencode-plugin"] }
// and ensure `deepvista` is on PATH (`deepvista auth login`).

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

const SELF_DIR = dirname(fileURLToPath(import.meta.url));

function pickTarget(ctx) {
  // Prefer an opencode-provided plugin dir if one exists on the hook context.
  // The field name has shifted across opencode versions — try the known ones.
  const fromCtx =
    ctx?.pluginDir ||
    ctx?.plugin?.dir ||
    ctx?.plugin?.path ||
    ctx?.plugin_dir;
  if (fromCtx) return join(fromCtx, "skills");

  // Fallback 1: the module's own dir (when dropped into ~/.config/opencode/plugins/).
  if (SELF_DIR) return join(SELF_DIR, "skills");

  // Fallback 2: the user-level opencode skills dir, then ~/.claude/skills/.
  const xdg = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(xdg, "opencode", "skills");
}

function runSync(target, { force = false } = {}) {
  return new Promise((resolve) => {
    const args = [
      "skill",
      "sync",
      "--target",
      target,
      "--limit",
      process.env.DEEPVISTA_SYNC_LIMIT || "30",
      "--throttle-min",
      process.env.DEEPVISTA_SYNC_THROTTLE_MIN || "60",
      "--quiet",
    ];
    if (force || process.env.DEEPVISTA_FORCE_SYNC === "1") {
      args.push("--force");
    }
    const child = spawn("deepvista", args, {
      stdio: "ignore",
      detached: false,
      env: process.env,
    });
    child.on("error", () => resolve({ ok: false, reason: "spawn_failed" }));
    child.on("exit", (code) =>
      resolve({ ok: code === 0, exit_code: code ?? -1 }),
    );
  });
}

export default async function deepvistaPlugin() {
  return {
    "session.created": async (ctx) => {
      const target = pickTarget(ctx);
      try {
        await runSync(target);
      } catch {
        /* never break session creation */
      }
    },
  };
}
