using BepInEx;
using Jotunn.Utils;
using ValheimSuite.Common;
using ValheimSuite.Common.Modules;

namespace ValheimSuite.Shared.Diagnostics;

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

    private void Awake()
    {
        Logger.LogInfo($"{PluginName} {PluginVersion} protocol {ProtocolVersion} loaded.");
        Logger.LogInfo("Diagnostic CustomRPC is intentionally left for bootstrap Milestone 2 so exact current Jotunn signatures are verified before implementation.");
    }
}
