import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

const MAX_BUFFER = 16 * 1024 * 1024;

type BuildConfiguration = "Debug" | "Release";

type ServerDeployment =
  | { type: "local"; pluginDir: string }
  | {
      type: "ssh";
      host: string;
      pluginDir: string;
      remotePlatform?: "auto" | "windows" | "posix";
      sshExecutable?: string;
      scpExecutable?: string;
    };

type ServerLifecycle =
  | { type: "none" }
  | { type: "docker"; container: string };

type DevConfig = {
  schemaVersion: 1 | 2;
  developmentOnly: boolean;
  valheimInstall: string;
  clientPluginDir: string;
  serverPluginDir?: string;
  dockerComposeFile?: string | null;
  dockerService?: string | null;
  server?: { deployment: ServerDeployment; lifecycle: ServerLifecycle };
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

function rejectUnknownFields(value: object, allowed: readonly string[], field: string): void {
  const unexpected = Object.keys(value).filter(key => !allowed.includes(key)).sort();
  if (unexpected.length) throw new Error(`${field} contains unsupported field(s): ${unexpected.join(", ")}`);
}

function rejectCredentialFields(value: object, configPath: string): void {
  const credentialFields = Object.keys(value).filter((field) => {
    const normalized = field.replaceAll("-", "").replaceAll("_", "").toLowerCase();
    return normalized.includes("password") ||
      normalized.includes("privatekey") ||
      normalized.endsWith("token") ||
      ["identityfile", "sshkey", "keymaterial"].includes(normalized);
  }).sort();
  if (credentialFields.length) {
    throw new Error(
      `${configPath} contains prohibited credential field(s): ${credentialFields.join(", ")}; ` +
      "keep SSH authentication material in SSH configuration",
    );
  }
}

function validateDevConfig(cfg: DevConfig, configPath: string): void {
  if (cfg.schemaVersion !== 1 && cfg.schemaVersion !== 2) {
    throw new Error(`${configPath}: schemaVersion must be 1 or 2`);
  }
  if (cfg.developmentOnly !== true) throw new Error(`${configPath}: developmentOnly must be true`);
  rejectCredentialFields(cfg, configPath);
  for (const key of ["valheimInstall", "clientPluginDir"] as const) {
    const value = cfg[key];
    if (typeof value !== "string" || !value.trim() || !path.isAbsolute(value)) {
      throw new Error(`${configPath}: ${key} must be a non-empty absolute WSL/Linux path`);
    }
  }
  if (cfg.configuration && cfg.configuration !== "Debug" && cfg.configuration !== "Release") {
    throw new Error(`${configPath}: configuration must be Debug or Release`);
  }
  if (cfg.serverLogFile != null &&
      (typeof cfg.serverLogFile !== "string" || !cfg.serverLogFile.trim() || !path.isAbsolute(cfg.serverLogFile))) {
    throw new Error(`${configPath}: serverLogFile must be null or an absolute WSL/Linux path`);
  }
  if (cfg.schemaVersion === 1) {
    if (typeof cfg.serverPluginDir !== "string" || !cfg.serverPluginDir.trim() || !path.isAbsolute(cfg.serverPluginDir)) {
      throw new Error(`${configPath}: serverPluginDir must be a non-empty absolute WSL/Linux path`);
    }
    if (cfg.dockerComposeFile != null &&
        (typeof cfg.dockerComposeFile !== "string" || !cfg.dockerComposeFile.trim() || !path.isAbsolute(cfg.dockerComposeFile))) {
      throw new Error(`${configPath}: dockerComposeFile must be null or an absolute WSL/Linux path`);
    }
    return;
  }
  rejectUnknownFields(
    cfg,
    ["schemaVersion", "developmentOnly", "valheimInstall", "clientPluginDir", "server", "serverLogFile", "solution", "configuration"],
    configPath,
  );
  if (!cfg.server || typeof cfg.server !== "object") throw new Error(`${configPath}: server must be an object`);
  rejectUnknownFields(cfg.server, ["deployment", "lifecycle"], `${configPath}: server`);
  const deployment = cfg.server.deployment;
  if (!deployment || (deployment.type !== "local" && deployment.type !== "ssh")) {
    throw new Error(`${configPath}: server.deployment.type must be local or ssh`);
  }
  rejectUnknownFields(
    deployment,
    deployment.type === "local"
      ? ["type", "pluginDir"]
      : ["type", "host", "pluginDir", "remotePlatform", "sshExecutable", "scpExecutable"],
    `${configPath}: server.deployment`,
  );
  if (typeof deployment.pluginDir !== "string" || !deployment.pluginDir.trim()) {
    throw new Error(`${configPath}: server.deployment.pluginDir must be a non-empty string`);
  }
  if (deployment.type === "local" && !path.isAbsolute(deployment.pluginDir)) {
    throw new Error(`${configPath}: local server.deployment.pluginDir must be an absolute WSL/Linux path`);
  }
  if (deployment.type === "ssh") {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(deployment.host)) {
      throw new Error(`${configPath}: server.deployment.host must be an SSH config alias`);
    }
    if (deployment.remotePlatform && !["auto", "windows", "posix"].includes(deployment.remotePlatform)) {
      throw new Error(`${configPath}: server.deployment.remotePlatform must be auto, windows, or posix`);
    }
    for (const key of ["sshExecutable", "scpExecutable"] as const) {
      const value = deployment[key];
      if (value != null && (typeof value !== "string" || !value.trim())) {
        throw new Error(`${configPath}: server.deployment.${key} must be a non-empty string`);
      }
    }
  }
  const lifecycle = cfg.server.lifecycle;
  if (!lifecycle || (lifecycle.type !== "none" && lifecycle.type !== "docker")) {
    throw new Error(`${configPath}: server.lifecycle.type must be none or docker`);
  }
  rejectUnknownFields(
    lifecycle,
    lifecycle.type === "none" ? ["type"] : ["type", "container"],
    `${configPath}: server.lifecycle`,
  );
  if (lifecycle.type === "docker" &&
      (typeof lifecycle.container !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(lifecycle.container))) {
    throw new Error(`${configPath}: server.lifecycle.container must be a Docker container name`);
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

export function isPathInside(root: string, target: string): boolean {
  const relative = path.relative(root, target);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

export async function resolveCanonicalManagedRoot(managed: string): Promise<string> {
  let canonical: string;
  try {
    canonical = await fs.realpath(managed);
  } catch (error) {
    throw new Error(`Valheim Managed directory not found or unresolvable: ${managed} (${String(error)})`);
  }
  const stat = await fs.stat(canonical).catch((error) => {
    throw new Error(`Valheim Managed directory not accessible: ${canonical} (${String(error)})`);
  });
  if (!stat.isDirectory()) {
    throw new Error(`Valheim Managed path is not a directory: ${canonical}`);
  }
  return canonical;
}

export async function resolveCanonicalManagedAssembly(canonicalManagedRoot: string, relative: string): Promise<string> {
  const lexical = path.resolve(canonicalManagedRoot, relative);
  let canonical: string;
  try {
    canonical = await fs.realpath(lexical);
  } catch (error) {
    throw new Error(`Assembly not found or unresolvable: ${relative} (${String(error)})`);
  }
  if (canonical === canonicalManagedRoot) {
    throw new Error("assembly must be a file under valheim_Data/Managed, not the Managed directory itself");
  }
  if (!isPathInside(canonicalManagedRoot, canonical)) {
    throw new Error("assembly resolves outside the configured Valheim Managed directory");
  }
  const stat = await fs.stat(canonical).catch((error) => {
    throw new Error(`Assembly not accessible: ${relative} (${String(error)})`);
  });
  if (!stat.isFile()) {
    throw new Error(`Assembly path is not a regular file: ${relative}`);
  }
  return canonical;
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
        serverDeployment: cfg.schemaVersion === 1
          ? { type: "local", pluginDir: cfg.serverPluginDir }
          : cfg.server!.deployment,
        serverLifecycle: cfg.schemaVersion === 1
          ? { type: "legacy", dockerComposeFile: cfg.dockerComposeFile ?? null, dockerService: cfg.dockerService ?? null }
          : cfg.server!.lifecycle,
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
      const canonicalManagedRoot = await resolveCanonicalManagedRoot(managed);
      const relative = ensureRelativeManagedPath(params.assembly);
      const assembly = await resolveCanonicalManagedAssembly(canonicalManagedRoot, relative);
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
      restart: z.boolean().optional().describe("Restart the configured server lifecycle after deployment"),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const cfg = await loadDevConfig(root);
      if (cfg.developmentOnly !== true) throw new Error("deployment blocked: developmentOnly must be true");
      if (params.confirm !== true) throw new Error("deployment blocked: confirm must be true");
      const configuration = params.configuration ?? cfg.configuration ?? "Debug";
      const argv = ["scripts/deploy.py", "--target", params.target, "--configuration", configuration];
      if (params.restart) argv.push("--restart");
      const output = await run(
        "python3",
        argv,
        root,
        signal,
      );
      return { content: [{ type: "text", text: output }], details: { target: params.target, configuration } };
    },
  });

  pi.registerTool({
    name: "valheim_logs",
    label: "Valheim Server Logs",
    description: "Read a bounded tail from the configured local or remote server log source.",
    approval: "exec",
    parameters: z.object({
      tail: z.number().int().min(10).max(2000).optional().describe("Number of lines, default 250"),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const tail = params.tail ?? 250;
      const output = await run(
        "python3",
        ["scripts/server_runtime.py", "logs", "--tail", String(tail)],
        root,
        signal,
      );
      return { content: [{ type: "text", text: output || "No log output." }], details: { tail } };
    },
  });

  pi.registerTool({
    name: "valheim_server_status",
    label: "Valheim Dev Server Status",
    description: "Read status from the configured local or remote server lifecycle.",
    approval: "exec",
    parameters: z.object({}),
    async execute(_id, _params, signal, _onUpdate, ctx) {
      const root = await findProjectRoot(ctx.cwd);
      const output = await run("python3", ["scripts/server_runtime.py", "status"], root, signal);
      return { content: [{ type: "text", text: output || "No server status output." }], details: {} };
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
