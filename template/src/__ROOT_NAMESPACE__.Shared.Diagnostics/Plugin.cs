using BepInEx;
using Jotunn.Managers;
using Jotunn.Utils;
using {{ROOT_NAMESPACE}}.Common;
using {{ROOT_NAMESPACE}}.Common.Diagnostics;
using {{ROOT_NAMESPACE}}.Common.Modules;

namespace {{ROOT_NAMESPACE}}.Shared.Diagnostics;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
[BepInDependency(Jotunn.Main.ModGuid, BepInDependency.DependencyFlags.HardDependency)]
[NetworkCompatibility(CompatibilityLevel.VersionCheckOnly, VersionStrictness.Minor)]
public sealed class Plugin : BaseUnityPlugin
{
    public const string PluginGuid = SuiteConstants.GuidRoot + ".shared.diagnostics";
    public const string PluginName = SuiteConstants.Name + ".Shared.Diagnostics";
    public const string PluginVersion = SuiteConstants.Version;
    public const int ProtocolVersion = 1;

    internal static readonly ModuleDescriptor Descriptor = new(
        ModuleIds.SharedDiagnostics,
        PluginName,
        ModuleScope.SharedOptional,
        PluginVersion,
        ProtocolVersion);

    internal RuntimeDiagnostics Diagnostics { get; private set; } = null!;

    private DiagnosticRpc? diagnosticRpc;

    private void Awake()
    {
        var debugLogging = Config.Bind(
            "Development",
            "DebugLogging",
            false,
            "Enable opt-in runtime debug logging for this module.");
        Diagnostics = new RuntimeDiagnostics(() => debugLogging.Value, Logger.LogInfo);

        Logger.LogInfo($"{PluginName} {PluginVersion} protocol {ProtocolVersion} loaded.");
        Logger.LogInfo($"Shared.Diagnostics process mode: {(GUIManager.IsHeadless() ? "headless/dedicated" : "graphical")}.");

        diagnosticRpc = new DiagnosticRpc(Logger);
        diagnosticRpc.Initialize();
    }

    private void OnDestroy()
    {
        diagnosticRpc?.Dispose();
        diagnosticRpc = null;
    }
}
