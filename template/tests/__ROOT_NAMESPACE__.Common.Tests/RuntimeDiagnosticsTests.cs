using System.Collections.Generic;
using {{ROOT_NAMESPACE}}.Common.Diagnostics;
using Xunit;

namespace {{ROOT_NAMESPACE}}.Common.Tests;

public sealed class RuntimeDiagnosticsTests
{
    [Fact]
    public void EnabledDiagnosticsReachSinkWithStableFormat()
    {
        var messages = new List<string>();
        var diagnostics = new RuntimeDiagnostics(() => true, messages.Add);
        Assert.True(diagnostics.Enabled);
        diagnostics.Debug("first-person.requested", "enabled=true");

        Assert.Equal(new[] { "[RuntimeDebug] first-person.requested: enabled=true" }, messages);
    }

    [Fact]
    public void DisabledDiagnosticsEmitNothing()
    {
        var messages = new List<string>();
        var diagnostics = new RuntimeDiagnostics(() => false, messages.Add);
        Assert.False(diagnostics.Enabled);
        diagnostics.Debug("first-person.requested", "enabled=true");

        Assert.Empty(messages);
    }

    [Fact]
    public void DiagnosticsObserveCurrentEnablement()
    {
        var enabled = false;
        var messages = new List<string>();
        var diagnostics = new RuntimeDiagnostics(() => enabled, messages.Add);

        Assert.False(diagnostics.Enabled);
        diagnostics.Debug("first-person.requested", "enabled=true");
        Assert.Empty(messages);

        enabled = true;
        Assert.True(diagnostics.Enabled);
        diagnostics.Debug("first-person.requested", "enabled=true");
        Assert.Equal(new[] { "[RuntimeDebug] first-person.requested: enabled=true" }, messages);

        enabled = false;
        Assert.False(diagnostics.Enabled);
        diagnostics.Debug("first-person.requested", "enabled=true");
        Assert.Equal(new[] { "[RuntimeDebug] first-person.requested: enabled=true" }, messages);
    }
}
