using ValheimSuite.Common.Modules;
using Xunit;

namespace ValheimSuite.Common.Tests;

public sealed class ModuleDescriptorTests
{
    [Fact]
    public void DescriptorPreservesCompatibilityMetadata()
    {
        var descriptor = new ModuleDescriptor(
            "shared.example",
            "Example",
            ModuleScope.SharedRequired,
            "1.2.3",
            protocolVersion: 4,
            dataSchemaVersion: 2,
            hotReloadable: false);

        Assert.Equal("shared.example", descriptor.Id);
        Assert.Equal(ModuleScope.SharedRequired, descriptor.Scope);
        Assert.Equal(4, descriptor.ProtocolVersion);
        Assert.Equal(2, descriptor.DataSchemaVersion);
        Assert.False(descriptor.HotReloadable);
    }
}
