import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

const MAX_BUFFER = 16 * 1024 * 1024;

type BuildConfiguration = "Debug" | "Release";

type DevConfig = {
  schemaVersion: 1;
  developmentOnly: boolean;
  valheimInstall: string;
  clientPluginDir: string;
  serverPluginDir: string;
  dockerComposeFile?: string | null;
  dockerService?: string | null;
  serverLogFile?: string | null;
  solution?: string;
  configuration?: BuildConfiguration;
};

type SuiteConfig = {
  suiteName: string;
  suiteVersion: string;
  jotunnVersion: string;
  bepInExPackVersion: string;
};

async function findProjectRoot(start: string): Promise<string> {
  let current = path.resolve(start);
  while (true) {
    try {
      await fs.access(path.join(current, "suite.config.json"));
      return current;
    } catch {
      const parent = path.dirname(current);
      if (parent === current) {
        throw new Error(`Could not find suite.config.json from ${start} or any parent directory`);
      }
      current = parent;
    }
  }
}

async function readJsonObject<T>(file: string): Promise<T> {
  let raw: string;
  try {
    raw = await fs.readFile(file, "utf8");
  } catch (error) {
    throw new Error(`Cannot read ${file}: ${String(error)}`);
  }
  try {
    const value = JSON.parse(raw) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("root value is not an object");
    }
    return value as T;
  } catch (error) {
    throw new Error(`Invalid JSON in ${file}: ${String(error)}`);
  }
}

function validateDevConfig(cfg: DevConfig, configPath: string): void {
  if (cfg.schemaVersion !== 1) throw new Error(`${configPath}: schemaVersion must be 1`);
  if (cfg.developmentOnly !== true) throw new Error(`${configPath}: developmentOnly must be true`);
  for (const key of ["valheimInstall", "clientPluginDir", "serverPluginDir"] as const) {
    const value = cfg[key];
    if (typeof value !== "string" || !value.trim() || !path.isAbsolute(value)) {
      throw new Error(`${configPath}: ${key} must be a non-empty absolute WSL/Linux path`);
    }
  }
  if (cfg.configuration && cfg.configuration !== "Debug" && cfg.configuration !== "Release") {
    throw new Error(`${configPath}: configuration must be Debug or Release`);
  }
  for (const key of ["dockerComposeFile", "serverLogFile"] as const) {
    const value = cfg[key];
    if (value != null && (typeof value !== "string" || !value.trim() || !path.isAbsolute(value))) {
      throw new Error(`${configPath}: ${key} must be null or an absolute WSL/Linux path`);
    }
  }
}

async function loadDevConfig(root: string): Promise<DevConfig> {
  const configPath = path.join(root, ".valheim", "dev.json");
  const cfg = await readJsonObject<DevConfig>(configPath);
  validateDevConfig(cfg, configPath);
  return cfg;
}

async function loadSuiteConfig(root: string): Promise<SuiteConfig> {
  return readJsonObject<SuiteConfig>(path.join(root, "suite.config.json"));
}

async function fileExists(value: string): Promise<boolean> {
  try {
    await fs.access(value);
    return true;
  } catch {
    return false;
  }
}

async function findFileRecursive(root: string, filename: string): Promise<string | null> {
  if (!(await fileExists(root))) return null;
  const queue = [root];
  while (queue.length) {
    const current = queue.shift()!;
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isFile() && entry.name.toLowerCase() === filename.toLowerCase()) return full;
      if (entry.isDirectory()) queue.push(full);
    }
  }
  return null;
}

async function sha256(file: string): Promise<string> {
  const data = await fs.readFile(file);
  return createHash("sha256").update(data).digest("hex");
}

async function run(command: string, args: string[], cwd: string, signal?: AbortSignal): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    execFile(
      command,
      args,
      { cwd, windowsHide: true, maxBuffer: MAX_BUFFER, signal },
      (error, stdout, stderr) => {
        const output = `${stdout ?? ""}${stderr ?? ""}`.trim();
        if (error) {
          reject(new Error(output ? `${error.message}\n${output}` : error.message));
          return;
        }
        resolve(output);
      },
    );
  });
}

function ensureRelativeManagedPath(value: string): string {
  if (!value.trim()) throw new Error("assembly path must not be empty");
  if (path.isAbsolute(value)) throw new Error("assembly must be a relative path under valheim_Data/Managed");
  const normalized = path.normalize(value);
  if (normalized === ".." || normalized.startsWith(`..${path.sep}`)) {
    throw new Error("assembly path may not escape valheim_Data/Managed");
  }
  return normalized;
}

async function tailFile(file: string, lineCount: number): Promise<string> {
  const raw = await fs.readFile(file, "utf8");
  return raw.split(/\r?\n/).slice(-lineCount).join("\n").trim();
}

export default function valheimDev(pi: ExtensionAPI) {
  const z = pi.zod;

  pi.registerTool({
    name: "valheim_preflight",
    label: "Valheim Preflight",
    description: "Run the repository's canonical WSL/local-environment preflight checks without modifying the game or server.",
    approval: "exec",
    parameters: z.object({
      portable: z.boolean().optional().describe("Skip machine-specific Valheim/server checks"),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const args = ["scripts/preflight.py", "--json"];
      if (params.portable) args.push("--portable");
      const output = await run("python3", args, root, signal);
      return { content: [{ type: "text", text: output }], details: JSON.parse(output) };
    },
  });

  pi.registerTool({
    name: "valheim_game_info",
    label: "Valheim Game Info",
    description: "Report configured Valheim development paths and the presence/hash of key local game/modding files without modifying anything.",
    approval: "read",
    parameters: z.object({}),
    async execute(_id, _params, signal, _onUpdate, ctx) {
      if (signal?.aborted) return { content: [{ type: "text", text: "Cancelled" }] };
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      const suite = await loadSuiteConfig(root);
      const install = path.resolve(cfg.valheimInstall);
      const managed = path.join(install, "valheim_Data", "Managed");
      const assembly = path.join(managed, "Assembly-CSharp.dll");
      const bepinEx = path.join(install, "BepInEx", "core", "BepInEx.dll");
      const jotunn = await findFileRecursive(path.join(install, "BepInEx", "plugins"), "Jotunn.dll");
      const assemblyExists = await fileExists(assembly);
      const checks = {
        suiteName: suite.suiteName,
        suiteVersion: suite.suiteVersion,
        pinnedJotunnVersion: suite.jotunnVersion,
        pinnedBepInExPackVersion: suite.bepInExPackVersion,
        developmentOnly: cfg.developmentOnly,
        valheimInstall: install,
        assemblyCSharp: assemblyExists ? assembly : null,
        assemblyCSharpSha256: assemblyExists ? await sha256(assembly) : null,
        bepinEx: (await fileExists(bepinEx)) ? bepinEx : null,
        jotunn,
        clientPluginDir: cfg.clientPluginDir,
        serverPluginDir: cfg.serverPluginDir,
        dockerComposeFile: cfg.dockerComposeFile ?? null,
        dockerService: cfg.dockerService ?? null,
        serverLogFile: cfg.serverLogFile ?? null,
      };
      return { content: [{ type: "text", text: JSON.stringify(checks, null, 2) }], details: checks };
    },
  });

  pi.registerTool({
    name: "valheim_build",
    label: "Build {{SUITE_NAME}}",
    description: "Run the canonical build script for the configured solution.",
    approval: "exec",
    parameters: z.object({
      configuration: z.enum(["Debug", "Release"]).optional(),
    }),
    async execute(_id, params, signal, onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      const configuration = params.configuration ?? cfg.configuration ?? "Debug";
      onUpdate?.({ content: [{ type: "text", text: `Building ${configuration}...` }] });
      const output = await run("bash", ["scripts/build.sh", configuration], root, signal);
      return { content: [{ type: "text", text: output || "Build completed." }], details: { configuration } };
    },
  });

  pi.registerTool({
    name: "valheim_inspect",
    label: "Inspect Valheim Assembly",
    description: "Decompile a type from an assembly located under the configured Valheim valheim_Data/Managed directory using ilspycmd. Read-only.",
    approval: "exec",
    parameters: z.object({
      assembly: z.string().describe("Relative managed-assembly path, for example Assembly-CSharp.dll"),
      type: z.string().describe("Fully qualified type name to decompile"),
      contains: z.string().optional().describe("Optional text to select context around matching lines"),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      const managed = path.join(path.resolve(cfg.valheimInstall), "valheim_Data", "Managed");
      const relative = ensureRelativeManagedPath(params.assembly);
      const assembly = path.resolve(managed, relative);
      const managedRoot = path.resolve(managed) + path.sep;
      if (!assembly.startsWith(managedRoot)) throw new Error("resolved assembly path escapes valheim_Data/Managed");
      if (!(await fileExists(assembly))) throw new Error(`Assembly not found: ${assembly}`);
      let output = await run("ilspycmd", ["-t", params.type, assembly], root, signal);
      if (params.contains) {
        const needle = params.contains.toLowerCase();
        const lines = output.split(/\r?\n/);
        const hits = lines.flatMap((line, index) => line.toLowerCase().includes(needle) ? [index] : []);
        if (hits.length) {
          const selected = new Set<number>();
          for (const hit of hits) {
            for (let i = Math.max(0, hit - 12); i <= Math.min(lines.length - 1, hit + 24); i++) selected.add(i);
          }
          output = [...selected].sort((a, b) => a - b).map(i => `${i + 1}: ${lines[i]}`).join("\n");
        }
      }
      return { content: [{ type: "text", text: output }], details: { assembly, type: params.type } };
    },
  });

  pi.registerTool({
    name: "valheim_deploy",
    label: "Deploy {{SUITE_NAME}} Dev Build",
    description: "Deploy the exact metadata-defined client or server DLL set through the repository's canonical deployment script.",
    approval: "write",
    parameters: z.object({
      target: z.enum(["client", "server"]),
      confirm: z.boolean().describe("Must be true"),
      configuration: z.enum(["Debug", "Release"]).optional(),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      if (cfg.developmentOnly !== true) throw new Error("deployment blocked: developmentOnly must be true");
      if (params.confirm !== true) throw new Error("deployment blocked: confirm must be true");
      const configuration = params.configuration ?? cfg.configuration ?? "Debug";
      const output = await run(
        "python3",
        ["scripts/deploy.py", "--target", params.target, "--configuration", configuration],
        root,
        signal,
      );
      return { content: [{ type: "text", text: output }], details: { target: params.target, configuration } };
    },
  });

  pi.registerTool({
    name: "valheim_logs",
    label: "Valheim Server Logs",
    description: "Read a bounded tail from the configured development server log source. Uses either a log file or docker compose logs, never an arbitrary configured command.",
    approval: "exec",
    parameters: z.object({
      tail: z.number().int().min(10).max(2000).optional().describe("Number of lines, default 250"),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      const tail = params.tail ?? 250;
      let output: string;
      let source: string;
      if (cfg.serverLogFile) {
        output = await tailFile(cfg.serverLogFile, tail);
        source = cfg.serverLogFile;
      } else if (cfg.dockerComposeFile && cfg.dockerService) {
        output = await run(
          "docker",
          ["compose", "-f", cfg.dockerComposeFile, "logs", "--tail", String(tail), cfg.dockerService],
          root,
          signal,
        );
        source = `${cfg.dockerComposeFile}:${cfg.dockerService}`;
      } else {
        throw new Error("configure serverLogFile or both dockerComposeFile and dockerService in .valheim/dev.json");
      }
      return { content: [{ type: "text", text: output || "No log output." }], details: { source, tail } };
    },
  });

  pi.registerTool({
    name: "valheim_server_status",
    label: "Valheim Dev Server Status",
    description: "Read docker compose status for the explicitly configured development server service.",
    approval: "exec",
    parameters: z.object({}),
    async execute(_id, _params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      if (!cfg.dockerComposeFile || !cfg.dockerService) {
        throw new Error("dockerComposeFile and dockerService must be configured in .valheim/dev.json");
      }
      const output = await run(
        "docker",
        ["compose", "-f", cfg.dockerComposeFile, "ps", cfg.dockerService],
        root,
        signal,
      );
      return { content: [{ type: "text", text: output || "No service status output." }], details: { service: cfg.dockerService } };
    },
  });

  pi.registerTool({
    name: "valheim_package",
    label: "Package {{SUITE_NAME}}",
    description: "Run the deterministic Release packaging workflow and write ZIPs/checksums under artifacts/packages.",
    approval: "write",
    parameters: z.object({ confirm: z.boolean().describe("Must be true") }),
    async execute(_id, params, signal, onUpdate, ctx) {
      if (params.confirm !== true) throw new Error("packaging blocked: confirm must be true");
      const root = await findProjectRoot(ctx.cwd);
      onUpdate?.({ content: [{ type: "text", text: "Building Release and creating deterministic packages..." }] });
      const output = await run("bash", ["scripts/package.sh"], root, signal);
      return { content: [{ type: "text", text: output }], details: { outputDir: path.join(root, "artifacts", "packages") } };
    },
  });
}
