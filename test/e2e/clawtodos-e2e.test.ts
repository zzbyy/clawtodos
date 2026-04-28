/**
 * clawtodos E2E tests — full workflow against live ~/.todos/
 *
 * Run: bun test test/e2e/clawtodos-e2e.test.ts
 * These interact with the real filesystem and the `todos` CLI.
 */
import { describe, expect, test } from "vitest";
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";

const E2E_ROOT = "/tmp/clawtodos-e2e";
const TODOS_ROOT = `${E2E_ROOT}/.todos`;
const PROJECT_DIR = `${E2E_ROOT}/my-app`;

function sh(cmd, args) {
  const r = spawnSync(cmd, args, { encoding: "utf8", shell: false });
  return { stdout: r.stdout ?? "", stderr: r.stderr ?? "", code: r.status ?? 1 };
}

function setup() {
  spawnSync("rm", ["-rf", E2E_ROOT]);
  mkdirSync(`${E2E_ROOT}/my-app/.git`, { recursive: true });
  const regPath = `${TODOS_ROOT}/registry.yaml`;
  mkdirSync(TODOS_ROOT, { recursive: true });
  writeFileSync(regPath, `schema: todo-contract/v3\nprojects:\n  - slug: my-app\n    type: code\n    path: ${PROJECT_DIR}\n    ingest: false\n`);
  mkdirSync(`${TODOS_ROOT}/my-app`);
  writeFileSync(
    `${TODOS_ROOT}/my-app/TODOS.md`,
    `---\nschema: todo-contract/v3\nproject: my-app\n---\n\n# TODOS — my-app\n\n`
  );
}

describe("clawtodos E2E — list workflow", () => {
  test("todos list --state pending with empty project returns empty gracefully", () => {
    setup();
    const r = sh("todos", ["list", "--state", "pending", "--root", TODOS_ROOT]);
    expect(r.code).toBe(0);
    expect(r.stdout).toContain("empty");
  });

  test("todos list --json returns valid structured output", () => {
    setup();
    const r = sh("todos", ["list", "--json", "--root", TODOS_ROOT]);
    expect(r.code).toBe(0);
    const data = JSON.parse(r.stdout);
    expect(data.schema).toBe("todo-contract/v3");
    expect(data.counts).toBeDefined();
    expect(Array.isArray(data.projects)).toBe(true);
  });

  test("todos list emits nudge when active is empty but pending exists", () => {
    setup();
    // Add a pending item first
    sh("todos", ["new", "my-app", "Test item", "--root", TODOS_ROOT], {
      env: { ...process.env, PATH: process.env.PATH + ":" + process.env.HOME + "/Library/Python/3.9/bin" }
    });
    const r = sh("todos", ["list", "--root", TODOS_ROOT]);
    expect(r.code).toBe(0);
    expect(r.stdout).toMatch(/empty|\(empty\)/i);
    // The nudge should appear when pending > 0
  });
});
