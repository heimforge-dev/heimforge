using BepInEx;
using Jotunn.Utils;
using ValheimSuite.Common;
using ValheimSuite.Common.Modules;

namespace ValheimSuite.ServerCore;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
[BepInDependency(Jotunn.Main.ModGuid, BepInDependency.DependencyFlags.HardDependency)]
[NetworkCompatibility(CompatibilityLevel.NotEnforced, VersionStrictness.None)]
public sealed class Plugin : BaseUnityPlugin
{
    public const string PluginGuid = SuiteConstants.GuidRoot + ".server";
    public const string PluginName = SuiteConstants.Name + ".ServerCore";
    public const string PluginVersion = SuiteConstants.Version;

    internal static readonly ModuleDescriptor Descriptor = new(
        ModuleIds.ServerCore,
        PluginName,
        ModuleScope.ServerOnly,
        PluginVersion);

    private void Awake()
    {
        Logger.LogInfo($"{PluginName} {PluginVersion} loaded. No gameplay features are active in the scaffold.");
        Logger.LogInfo("Before activating server-only features, verify dedicated-server side detection against the current Valheim/Jotunn runtime.");
    }
}
