// DeepVista catalog sync — opencode plugin.
//
// Wires the `session.created` hook to run `deepvista skill sync`. Stubs land in
// ~/.claude/skills/ by default, which opencode reads natively alongside its
// own skills paths. Body content is fetched lazily at invocation time by the
// stub's `!`deepvista skill load <id>`` directive.
//
// Install:
//   1. `npm install -g @deepvista/opencode-plugin` (or drop this dir in
//      ~/.config/opencode/plugins/)
//   2. Add to opencode.json:
//        {
//          "plugin": ["@deepvista/opencode-plugin"]
//        }
//   3. Ensure the `deepvista` CLI is on PATH and you are logged in
//      (`deepvista auth login`).

import { spawn } from "node:child_process";

function runSync({ force = false } = {}) {
  return new Promise((resolve) => {
    const args = [
      "skill",
      "sync",
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
    "session.created": async () => {
      // Never throw — a failed sync must not break session creation.
      try {
        await runSync();
      } catch {
        /* swallow */
      }
    },
  };
}
