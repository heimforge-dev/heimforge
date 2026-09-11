using BepInEx;
using Jotunn.Managers;
using Jotunn.Utils;
using {{ROOT_NAMESPACE}}.Common;
using {{ROOT_NAMESPACE}}.Common.Modules;

namespace {{ROOT_NAMESPACE}}.ServerCore;

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
        Logger.LogInfo($"ServerCore process mode: {(GUIManager.IsHeadless() ? "headless/dedicated" : "graphical")}.");
    }
}
