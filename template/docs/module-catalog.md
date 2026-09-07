# Module Catalog

| Module | Plugin | Scope | Required? | Protocol | Schema | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
{{MODULE_CATALOG_ROWS}}

Only modules actually generated in this repository are listed; `suite.config.json` is authoritative. Update this table whenever scope, requirement level, protocol version, or persistence schema changes.

The Plugin column names each module's project/assembly, not its BepInEx plugin GUID: every plugin GUID is `pluginGuidRoot` (from `suite.config.json`) plus a fixed per-module suffix (`.server`, `.client`, `.shared.diagnostics`). `pluginGuidRoot` is mutable and synchronized by `scripts/suite_metadata.py sync`; see `build/Suite.Generated.props`'s `SuitePluginGuidRoot` or `src/<RootNamespace>.Common/SuiteConstants.Generated.cs`'s `GuidRoot` for the exact current value.
