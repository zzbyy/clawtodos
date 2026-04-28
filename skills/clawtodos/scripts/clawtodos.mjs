#!/usr/bin/env bun
/**
 * clawtodos skill — wraps the `todos` CLI for gbrain skill ecosystem.
 * Deterministic: same input always produces same output.
 * Exits non-zero on CLI errors (non-idempotent failures).
 */
import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const PATH = process.env.PATH ?? "";
const TODOS_BIN = findTodosBin();

function findTodosBin() {
  const candidates = [
    `${process.env.HOME}/Library/Python/3.9/bin/todos`,
    "/usr/local/bin/todos",
    "todos",
  ];
  for (const bin of candidates) {
    if (existsSync(bin)) return bin;
  }
  const out = spawnSync("sh", ["-c", "which todos 2>/dev/null || true"], {
    encoding: "utf8",
  });
  const found = (out.stdout ?? "").trim();
  return found || "todos";
}

function run(args) {
  const result = spawnSync(TODOS_BIN, args, {
    encoding: "utf8",
    shell: false,
    env: { ...process.env, PATH },
  });
  return {
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    code: result.status ?? 1,
  };
}

function main() {
  const [cmd, ...args] = process.argv.slice(2);

  if (!cmd) {
    const r = run([]);
    if (r.stderr) process.stderr.write(r.stderr);
    process.stdout.write(r.stdout);
    process.exit(r.code);
  }

  switch (cmd) {
    case "list": {
      const r = run(["list", ...args]);
      if (r.code !== 0 && !args.includes("--json")) {
        process.stderr.write(r.stderr);
        process.exit(r.code);
      }
      process.stdout.write(r.stdout);
      process.exit(0);
    }

    case "index": {
      const r = run(["index"]);
      if (r.code !== 0) {
        process.stderr.write(r.stderr);
        process.exit(r.code);
      }
      const idxPath = `${process.env.HOME}/.todos/INDEX.md`;
      try {
        const content = readFileSync(idxPath, "utf8");
        process.stdout.write(content);
      } catch {
        process.stdout.write(r.stdout);
      }
      process.exit(0);
    }

    case "approve":
    case "done":
    case "drop":
    case "start":
    case "defer":
    case "new":
    case "propose":
    case "add":
    // v3.1 coordination commands
    case "claim":
    case "release":
    case "handoff":
    case "render": {
      const r = run([cmd, ...args]);
      if (r.code !== 0) {
        process.stderr.write(r.stderr);
        process.exit(r.code);
      }
      process.stdout.write(r.stdout);
      process.exit(0);
    }

    case "snapshot": {
      const r = run(["snapshot"]);
      if (r.code !== 0) {
        process.stderr.write(r.stderr);
        process.exit(r.code);
      }
      process.stdout.write(r.stdout);
      process.exit(0);
    }

    case "doctor": {
      const r = run(["doctor"]);
      process.stdout.write(r.stdout);
      if (r.stderr) process.stderr.write(r.stderr);
      process.exit(r.code);
    }

    default:
      process.stderr.write(`unknown subcommand: ${cmd}\n`);
      process.exit(1);
  }
}

main();
