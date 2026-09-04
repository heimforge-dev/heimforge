namespace ValheimSuite.ServerCore.Core;

internal interface IServerFeature
{
    string Id { get; }
    bool Enabled { get; }
    void Initialize();
    void Shutdown();
}
