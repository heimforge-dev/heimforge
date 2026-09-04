namespace {{ROOT_NAMESPACE}}.Common.Modules;

public sealed class ModuleDescriptor
{
    public ModuleDescriptor(
        string id,
        string displayName,
        ModuleScope scope,
        string version,
        int protocolVersion = 1,
        int dataSchemaVersion = 1,
        bool hotReloadable = false)
    {
        Id = id;
        DisplayName = displayName;
        Scope = scope;
        Version = version;
        ProtocolVersion = protocolVersion;
        DataSchemaVersion = dataSchemaVersion;
        HotReloadable = hotReloadable;
    }

    public string Id { get; }
    public string DisplayName { get; }
    public ModuleScope Scope { get; }
    public string Version { get; }
    public int ProtocolVersion { get; }
    public int DataSchemaVersion { get; }
    public bool HotReloadable { get; }
}
