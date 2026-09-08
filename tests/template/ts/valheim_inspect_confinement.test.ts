/**
 * Regression tests for the OMP `valheim_inspect` assembly-confinement
 * issue: lexical `path.resolve()` + string-prefix containment let a
 * symlink under `valheim_Data/Managed` (e.g. `escape.dll -> /tmp/outside.dll`)
 * reach `ilspycmd` even though its real filesystem target sits outside the
 * configured Managed directory.
 *
 * These tests exercise the actual template source
 * (`template/.omp/extensions/valheim-dev/index.ts`) end-to-end: they
 * register the real tools through a minimal fake `ExtensionAPI`/`zod`,
 * invoke `valheim_inspect`'s `execute()` directly, and stub `ilspycmd` on
 * PATH with a script that records its exact argv. Nothing here touches
 * `~/src/vibeheim` or a generated project; the template file is the
 * single source of truth every generated project's copy is rendered from.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import valheimDev, { isPathInside } from "../../../template/.omp/extensions/valheim-dev/index.ts";

// --- minimal fake ExtensionAPI: enough to register tools and call execute() directly ---

interface ToolExecuteResult {
  content: Array<{ type: string; text: string }>;
  details?: Record<string, unknown>;
}

type ToolExecute = (
  id: string,
  params: Record<string, unknown>,
  signal: AbortSignal | undefined,
  onUpdate: ((update: ToolExecuteResult) => void) | undefined,
  ctx: { cwd: string },
) => Promise<ToolExecuteResult>;

interface ToolDefinition {
  name: string;
  execute: ToolExecute;
}

// zod is used by the extension only to build a parameters schema at registration
// time (`z.object({ ... }).describe(...)`, etc.); these tests call `execute()`
// directly and never parse through it, so any chained call just needs to keep
// returning something chainable.
type ChainableZodStub = ((...args: unknown[]) => ChainableZodStub) & Record<string, (...args: unknown[]) => ChainableZodStub>;

function makeChainableZod(): ChainableZodStub {
  // Proxy requires a callable target object; it is never invoked directly,
  // only through the traps below, so a cast at this single mock boundary
  // stands in for the real zod builder's callable shape.
  const target = (() => {}) as unknown as ChainableZodStub;
  const handler: ProxyHandler<ChainableZodStub> = {
    get: () => (..._args: unknown[]) => makeChainableZod(),
    apply: () => makeChainableZod(),
  };
  return new Proxy(target, handler);
}

interface FakeExtensionApi {
  zod: ChainableZodStub;
  registerTool(def: ToolDefinition): void;
}

function registerTools(): Map<string, ToolDefinition> {
  const tools = new Map<string, ToolDefinition>();
  const fakePi: FakeExtensionApi = {
    zod: makeChainableZod(),
    registerTool(def) {
      tools.set(def.name, def);
    },
  };
  // `valheimDev` expects the real `@oh-my-pi/pi-coding-agent` ExtensionAPI, which
  // this repo does not depend on; the fake above implements exactly the surface
  // (`zod`, `registerTool`) the extension actually calls during registration.
  valheimDev(fakePi as unknown as Parameters<typeof valheimDev>[0]);
  return tools;
}

const inspectTool = registerTools().get("valheim_inspect");
if (!inspectTool) throw new Error("valheim_inspect was not registered by the extension");

// Called by every test below with the exact same execute() argument shape
// (positional signal/onUpdate slots this tool ignores); one named seam keeps
// that contract in one place instead of duplicated across every test.
function invokeInspect(cwd: string, params: { assembly: string; type: string; contains?: string }): Promise<ToolExecuteResult> {
  return inspectTool.execute("call-1", params, undefined, undefined, { cwd });
}

// --- fixture plumbing ---

const cleanupDirs: string[] = [];

function tempDir(prefix: string): string {
  const dir = mkdtempSync(path.join(tmpdir(), prefix));
  cleanupDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of cleanupDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

/** A game install with a mix of legitimate files and adversarial symlinks under Managed. */
function createGameFixture() {
  const gameRoot = tempDir("valheim-game-");
  const outsideRoot = tempDir("valheim-outside-");
  const managed = path.join(gameRoot, "valheim_Data", "Managed");
  const managedEvil = path.join(gameRoot, "valheim_Data", "Managed-evil");
  mkdirSync(path.join(managed, "nested"), { recursive: true });
  mkdirSync(managedEvil, { recursive: true });

  writeFileSync(path.join(managed, "legitimate.dll"), "LEGIT");
  writeFileSync(path.join(managed, "real.dll"), "REAL");
  writeFileSync(path.join(managed, "nested", "Nested.Legit.dll"), "NESTED");
  writeFileSync(path.join(managedEvil, "evil.dll"), "EVIL");
  writeFileSync(path.join(outsideRoot, "outside.dll"), "OUTSIDE");
  // Sibling one level above Managed, used by the ../outside.dll traversal test to prove
  // rejection is explicit rather than an accident of the target not existing.
  writeFileSync(path.join(gameRoot, "valheim_Data", "outside.dll"), "SIBLING-OUTSIDE");

  symlinkSync(path.join(outsideRoot, "outside.dll"), path.join(managed, "escape.dll"));
  symlinkSync("real.dll", path.join(managed, "alias.dll"));
  symlinkSync("/does/not/exist-marker.dll", path.join(managed, "broken.dll"));
  symlinkSync("loopB.dll", path.join(managed, "loopA.dll"));
  symlinkSync("loopA.dll", path.join(managed, "loopB.dll"));
  symlinkSync(path.join("..", "Managed-evil", "evil.dll"), path.join(managed, "prefixEscape.dll"));

  return { gameRoot, outsideRoot, managed, managedEvil };
}

function setupProject(valheimInstall: string): { projectRoot: string } {
  const projectRoot = tempDir("valheim-project-");
  writeFileSync(path.join(projectRoot, "suite.config.json"), "{}");
  mkdirSync(path.join(projectRoot, ".valheim"), { recursive: true });
  writeFileSync(
    path.join(projectRoot, ".valheim", "dev.json"),
    JSON.stringify({
      schemaVersion: 1,
      developmentOnly: true,
      valheimInstall,
      clientPluginDir: path.join(projectRoot, "client"),
      serverPluginDir: path.join(projectRoot, "server"),
    }),
  );
  return { projectRoot };
}

/** Stubs `ilspycmd` on PATH with a script that logs its exact argv, one call per block. */
function stubIlspycmd(): { binDir: string; readCalls(): string[][] } {
  const binDir = tempDir("valheim-ilspy-bin-");
  const log = path.join(binDir, "calls.log");
  writeFileSync(log, "");
  const scriptPath = path.join(binDir, "ilspycmd");
  writeFileSync(
    scriptPath,
    `#!/usr/bin/env bash\nfor a in "$@"; do printf '%s\\n' "$a" >> ${JSON.stringify(log)}; done\nprintf -- '---\\n' >> ${JSON.stringify(log)}\necho "decompiled output"\n`,
  );
  chmodSync(scriptPath, 0o755);
  return {
    binDir,
    readCalls(): string[][] {
      const raw = readFileSync(log, "utf8");
      const blocks = raw.split("---\n").filter((block) => block.trim() !== "");
      return blocks.map((block) => block.split("\n").filter((line) => line !== ""));
    },
  };
}

async function withStubbedPath<T>(binDir: string, fn: () => Promise<T>): Promise<T> {
  const original = process.env.PATH ?? "";
  process.env.PATH = `${binDir}:${original}`;
  try {
    return await fn();
  } finally {
    process.env.PATH = original;
  }
}

// --- item 1: reproduce the original lexical-containment bypass pattern ---

describe("original bypass reproduction", () => {
  test("lexical path.resolve()/startsWith() accepts an escaping symlink that realpath reveals is outside Managed", () => {
    const { managed, outsideRoot } = createGameFixture();
    const managedRootLexical = `${path.resolve(managed)}${path.sep}`;
    const lexicalAssembly = path.resolve(managed, "escape.dll");

    // The original vulnerable predicate: lexical prefix containment says "inside".
    expect(lexicalAssembly.startsWith(managedRootLexical)).toBe(true);

    // But the real filesystem target is a different directory entirely.
    const canonicalAssembly = realpathSync(lexicalAssembly);
    const canonicalManagedRoot = realpathSync(managed);
    expect(isPathInside(canonicalManagedRoot, canonicalAssembly)).toBe(false);
    expect(canonicalAssembly).toBe(realpathSync(path.join(outsideRoot, "outside.dll")));
  });

  test("the hardened valheim_inspect tool rejects that same escape end-to-end", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "escape.dll", type: "Foo" })),
    ).rejects.toThrow(/outside the configured Valheim Managed directory/);
    expect(stub.readCalls().length).toBe(0);
  });
});

// --- isPathInside: separator-aware containment semantics (item 5) ---

describe("isPathInside", () => {
  test("does not reject a legitimate filename that merely starts with two dots", () => {
    const root = "/managed";
    expect(isPathInside(root, "/managed/..foo.dll")).toBe(true);
  });

  test("rejects the root itself", () => {
    expect(isPathInside("/managed", "/managed")).toBe(false);
  });

  test("rejects a real parent-directory escape", () => {
    expect(isPathInside("/managed", "/outside.dll")).toBe(false);
    expect(isPathInside("/a/managed", "/a/managed-evil/evil.dll")).toBe(false);
  });

  test("accepts a nested descendant", () => {
    expect(isPathInside("/managed", "/managed/nested/x.dll")).toBe(true);
  });
});

// --- end-to-end regression matrix (item 25) ---

describe("valheim_inspect regression matrix", () => {
  test("accepts a normal in-root DLL and invokes ilspycmd exactly once with the canonical path", async () => {
    const { gameRoot, managed } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    const expected = realpathSync(path.join(managed, "legitimate.dll"));

    const result = await withStubbedPath(stub.binDir, () =>
      invokeInspect(projectRoot, { assembly: "legitimate.dll", type: "Foo.Bar" }),
    );

    const calls = stub.readCalls();
    expect(calls.length).toBe(1);
    expect(calls[0]).toEqual(["-t", "Foo.Bar", expected]);
    expect(result.details?.assembly).toBe(expected);
  });

  test("accepts a nested legitimate DLL", async () => {
    const { gameRoot, managed } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    const expected = realpathSync(path.join(managed, "nested", "Nested.Legit.dll"));

    await withStubbedPath(stub.binDir, () =>
      invokeInspect(projectRoot, { assembly: path.join("nested", "Nested.Legit.dll"), type: "Foo" }),
    );

    const calls = stub.readCalls();
    expect(calls.length).toBe(1);
    expect(calls[0][2]).toBe(expected);
  });

  test("accepts an in-root symlink whose canonical target stays inside Managed (item 9, allowed case)", async () => {
    const { gameRoot, managed } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    const expected = realpathSync(path.join(managed, "real.dll"));

    await withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "alias.dll", type: "Foo" }));

    const calls = stub.readCalls();
    expect(calls.length).toBe(1);
    expect(calls[0][2]).toBe(expected);
  });

  test("rejects an in-root symlink that escapes outside Managed (item 9, rejected case)", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "escape.dll", type: "Foo" })),
    ).rejects.toThrow(/outside the configured Valheim Managed directory/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects an in-root symlink to a sibling Managed-evil directory (prefix collision + escape)", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "prefixEscape.dll", type: "Foo" })),
    ).rejects.toThrow(/outside the configured Valheim Managed directory/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects relative traversal ../outside.dll even though a file exists at that exact traversed location", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "../outside.dll", type: "Foo" })),
    ).rejects.toThrow(/may not escape valheim_Data\/Managed/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects relative traversal ../../outside.dll", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "../../outside.dll", type: "Foo" })),
    ).rejects.toThrow(/may not escape valheim_Data\/Managed/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects an absolute outside path", async () => {
    const { gameRoot, outsideRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () =>
        invokeInspect(projectRoot, { assembly: path.join(outsideRoot, "outside.dll"), type: "Foo" }),
      ),
    ).rejects.toThrow(/must be a relative path/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects a broken symlink with a controlled error, not a raw realpath crash", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "broken.dll", type: "Foo" })),
    ).rejects.toThrow(/not found or unresolvable/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects a symlink loop with a controlled error", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "loopA.dll", type: "Foo" })),
    ).rejects.toThrow(/not found or unresolvable/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects the Managed root itself", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: ".", type: "Foo" })),
    ).rejects.toThrow(/not the Managed directory itself/);
    expect(stub.readCalls().length).toBe(0);
  });

  test("rejects a directory under Managed", async () => {
    const { gameRoot } = createGameFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "nested", type: "Foo" })),
    ).rejects.toThrow(/not a regular file/);
    expect(stub.readCalls().length).toBe(0);
  });
});

// --- symlinked Managed root (item 10): both sides of the comparison must be canonicalized ---

describe("symlinked Managed root", () => {
  function createSymlinkedRootFixture() {
    const gameRoot = tempDir("valheim-game-linkroot-");
    const realManaged = tempDir("valheim-real-managed-");
    const outsideRoot = tempDir("valheim-outside-linkroot-");
    mkdirSync(path.join(gameRoot, "valheim_Data"), { recursive: true });
    writeFileSync(path.join(realManaged, "legit.dll"), "LEGIT");
    writeFileSync(path.join(outsideRoot, "outside.dll"), "OUTSIDE");
    symlinkSync(path.join(outsideRoot, "outside.dll"), path.join(realManaged, "escape.dll"));
    symlinkSync(realManaged, path.join(gameRoot, "valheim_Data", "Managed"));
    return { gameRoot, realManaged, outsideRoot };
  }

  test("resolves a genuinely contained assembly through the symlinked root", async () => {
    const { gameRoot, realManaged } = createSymlinkedRootFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    const expected = realpathSync(path.join(realManaged, "legit.dll"));

    await withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "legit.dll", type: "Foo" }));

    const calls = stub.readCalls();
    expect(calls.length).toBe(1);
    expect(calls[0][2]).toBe(expected);
  });

  test("still rejects an escaping symlink reached through the symlinked root", async () => {
    const { gameRoot } = createSymlinkedRootFixture();
    const { projectRoot } = setupProject(gameRoot);
    const stub = stubIlspycmd();
    await expect(
      withStubbedPath(stub.binDir, () => invokeInspect(projectRoot, { assembly: "escape.dll", type: "Foo" })),
    ).rejects.toThrow(/outside the configured Valheim Managed directory/);
    expect(stub.readCalls().length).toBe(0);
  });
});
