import { describe, expect, test } from "vitest";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

const SKILL = "skills/clawtodos/scripts/clawtodos.mjs";
const TODOS_BIN = `${process.env.HOME}/Library/Python/3.9/bin/todos`;

function runSkill(args) {
  const result = spawnSync("bun", ["run", SKILL, ...args], {
    encoding: "utf8",
    env: { ...process.env, PATH: process.env.PATH },
  });
  return { stdout: result.stdout ?? "", stderr: result.stderr ?? "", code: result.status ?? 1 };
}

test("clawtodos skill script exists and is executable", () => {
  expect(existsSync(SKILL)).toBe(true);
});

test("list subcommand returns output (empty active list with nudge)", () => {
  const r = runSkill(["list"]);
  expect(r.code).toBe(0);
  // Should mention pending when active is empty
  expect(r.stdout).toMatch(/pending|empty/i);
});

test("list --json returns valid JSON with schema and counts", () => {
  const r = runSkill(["list", "--json"]);
  expect(r.code).toBe(0);
  const data = JSON.parse(r.stdout);
  expect(data).toHaveProperty("schema", "todo-contract/v3");
  expect(data).toHaveProperty("counts");
  expect(data).toHaveProperty("projects");
  expect(Array.isArray(data.projects)).toBe(true);
});

test("list --state pending shows pending items", () => {
  const r = runSkill(["list", "--state", "pending"]);
  expect(r.code).toBe(0);
  expect(r.stdout).toMatch(/pending/i);
});

test("unknown subcommand exits non-zero", () => {
  const r = runSkill(["foobar"]);
  expect(r.code).not.toBe(0);
});

test("doctor subcommand runs successfully", () => {
  const r = runSkill(["doctor"]);
  // doctor exits 0 on healthy state
  expect(r.code).toBe(0);
  expect(r.stdout).toMatch(/ok|root/i);
});
