using System;
using System.Collections.Generic;

namespace ValheimSuite.ServerCore.Core;

internal sealed class FeatureRegistry
{
    private readonly List<IServerFeature> _features = new();

    public void Add(IServerFeature feature)
    {
        if (feature == null) throw new ArgumentNullException(nameof(feature));
        _features.Add(feature);
    }

    public void InitializeEnabled()
    {
        foreach (IServerFeature feature in _features)
        {
            if (feature.Enabled) feature.Initialize();
        }
    }

    public void ShutdownAll()
    {
        for (int i = _features.Count - 1; i >= 0; i--)
        {
            _features[i].Shutdown();
        }
    }
}
