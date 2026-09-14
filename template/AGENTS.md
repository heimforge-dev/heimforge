# {{SUITE_NAME}} Project Instructions

This repository is a modular Valheim mod suite. Reusable coding-harness behavior belongs in the user's global OMP rules.

## Context routing

Before significant work, read `.context/CONTEXT.md`; it is the sole task router for this repository.

Detailed rules in the routed context and linked `docs/` files are mandatory when their domain applies.

## Always-on guardrails

1. Never guess Valheim API signatures when local assemblies or current Jotunn documentation can be inspected.
2. Treat clients as untrusted; the server validates authoritative gameplay actions.
3. Never commit Valheim assemblies, publicized assemblies, generated game DLLs, credentials, passwords, world saves, or production configuration.
4. Never deploy automatically to a production world. Use a disposable integration-test world by default.
5. Treat WSL/Linux and the Bash scripts as the canonical development workflow; access the Windows client through `/mnt/c/...`. Do not create a second independent PowerShell implementation of build, deploy, or package behavior.
6. `suite.config.json`, `suite.identity.lock.json`, and the canonical solution define suite structure and identity. Synchronize supported metadata edits; never hand-edit generated metadata.
7. Keep changes minimal and scoped. Add dependencies and abstractions only for demonstrated requirements.
8. Use native harness capabilities; do not create project-local generic agents or duplicate global Context Mode or Context7 configuration.
