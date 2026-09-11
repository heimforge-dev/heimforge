using System.Collections;
using System.Collections.Generic;
using BepInEx.Logging;
using Jotunn;
using Jotunn.Entities;
using Jotunn.Managers;
using Jotunn.Utils;

namespace {{ROOT_NAMESPACE}}.Shared.Diagnostics;

internal sealed class DiagnosticRpc : System.IDisposable
{
    private const string RpcName = "shared.diagnostics.ping";

    private readonly ManualLogSource logger;
    private readonly HashSet<ZNetPeer> acknowledgedPeers = new();
    private CustomRPC? rpc;
    private ZNet? pendingAcknowledgementConnection;
    private bool disposed;

    internal DiagnosticRpc(ManualLogSource logger)
    {
        this.logger = logger;
    }

    internal void Initialize()
    {
        if (rpc != null)
        {
            return;
        }

        rpc = NetworkManager.Instance.AddRPC(RpcName, OnServerReceive, OnClientReceive);
        SynchronizationManager.OnConfigurationSynchronized += OnConfigurationSynchronized;
    }

    private void OnConfigurationSynchronized(object? sender, ConfigurationSynchronizationEventArgs args)
    {
        var znet = ZNet.instance;
        if (!args.InitialSynchronization || !znet || !znet.IsClientInstance())
        {
            return;
        }

        pendingAcknowledgementConnection = null;
        if (!ModCompatibility.IsModuleOnServer(Plugin.PluginGuid))
        {
            logger.LogInfo("Shared.Diagnostics is absent on the server; diagnostic RPC skipped.");
            return;
        }

        pendingAcknowledgementConnection = znet;
        logger.LogInfo("Shared.Diagnostics diagnostic ping sent.");
        rpc?.Initiate();
    }

    private IEnumerator OnServerReceive(long sender, ZPackage package)
    {
        var znet = ZNet.instance;
        if (!znet || !znet.IsServer())
        {
            yield break;
        }

        var connectedPeers = znet.GetConnectedPeers();
        acknowledgedPeers.RemoveWhere(peer => !connectedPeers.Contains(peer));
        var peer = znet.GetPeer(sender);
        if (peer == null || !acknowledgedPeers.Add(peer))
        {
            yield break;
        }

        logger.LogInfo($"Shared.Diagnostics diagnostic ping received from peer {sender}; sending acknowledgement.");
        if (rpc != null)
        {
            yield return rpc.SendPackageRoutine(sender, new ZPackage());
        }
    }

    private IEnumerator OnClientReceive(long sender, ZPackage package)
    {
        var znet = ZNet.instance;
        var serverPeer = znet ? znet.GetServerPeer() : null;
        if (!znet ||
            !ReferenceEquals(pendingAcknowledgementConnection, znet) ||
            serverPeer == null ||
            sender != serverPeer.m_uid)
        {
            yield break;
        }

        pendingAcknowledgementConnection = null;
        logger.LogInfo("Shared.Diagnostics RPC acknowledgement received; diagnostic networking OK");
        yield break;
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        disposed = true;
        SynchronizationManager.OnConfigurationSynchronized -= OnConfigurationSynchronized;
        acknowledgedPeers.Clear();
        pendingAcknowledgementConnection = null;
        rpc = null;
    }
}
