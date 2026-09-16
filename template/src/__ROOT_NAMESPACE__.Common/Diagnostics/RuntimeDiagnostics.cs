using System;

namespace {{ROOT_NAMESPACE}}.Common.Diagnostics;

public sealed class RuntimeDiagnostics
{
    public const string Prefix = "[RuntimeDebug]";

    private readonly Func<bool> isEnabled;
    private readonly Action<string> sink;

    public RuntimeDiagnostics(Func<bool> isEnabled, Action<string> sink)
    {
        this.isEnabled = isEnabled ?? throw new ArgumentNullException(nameof(isEnabled));
        this.sink = sink ?? throw new ArgumentNullException(nameof(sink));
    }

    public bool Enabled => isEnabled();

    public void Debug(string eventName, string details)
    {
        if (!Enabled) return;

        sink($"{Prefix} {eventName}: {details}");
    }
}
