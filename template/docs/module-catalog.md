# Module Catalog

| Module | Plugin | Scope | Required? | Protocol | Schema | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
{{MODULE_CATALOG_ROWS}}

This table reflects the initial/bootstrap-time standard-module snapshot; `suite.config.json` plus the canonical `<RootNamespace>.sln` remain the machine-validated current structural authority afterward. It is human-maintained prose: update it whenever scope, requirement level, protocol version, persistence schema, or the configured project set changes.

The Plugin column names each module's project/assembly, not its BepInEx plugin GUID: every plugin GUID is `pluginGuidRoot` (from `suite.config.json`) plus a fixed per-module suffix (`.server`, `.client`, `.shared.diagnostics`). `pluginGuidRoot` is mutable and synchronized by `scripts/suite_metadata.py sync`; see `build/Suite.Generated.props`'s `SuitePluginGuidRoot` or `src/<RootNamespace>.Common/SuiteConstants.Generated.cs`'s `GuidRoot` for the exact current value.
