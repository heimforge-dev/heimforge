using BepInEx;
using Jotunn.Utils;
using ValheimSuite.Common;
using ValheimSuite.Common.Modules;

namespace ValheimSuite.Client;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
[BepInDependency(Jotunn.Main.ModGuid, BepInDependency.DependencyFlags.HardDependency)]
[NetworkCompatibility(CompatibilityLevel.NotEnforced, VersionStrictness.None)]
public sealed class Plugin : BaseUnityPlugin
{
    public const string PluginGuid = SuiteConstants.GuidRoot + ".client";
    public const string PluginName = SuiteConstants.Name + ".Client";
    public const string PluginVersion = SuiteConstants.Version;

    internal static readonly ModuleDescriptor Descriptor = new(
        ModuleIds.Client,
        PluginName,
        ModuleScope.ClientOnly,
        PluginVersion);

    private void Awake()
    {
        Logger.LogInfo($"{PluginName} {PluginVersion} loaded. No client features are active in the scaffold.");
    }
}
