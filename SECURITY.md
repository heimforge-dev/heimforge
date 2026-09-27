# Security Policy

## Supported versions

Security fixes are maintained for the latest released version of HeimForge and
the current `main` branch.

Older releases may not receive backported fixes unless explicitly stated.

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected security vulnerability.

Use GitHub's private vulnerability reporting for this repository:

1. Open the repository on GitHub.
2. Select **Security**.
3. Select **Report a vulnerability**.
4. Provide enough detail to reproduce and assess the issue.

Useful reports include:

- the affected HeimForge version or commit
- the affected component or file
- reproduction steps
- the expected and observed behavior
- the potential security impact
- any suggested mitigation, if known

Do not include live credentials, private keys, access tokens, production server
credentials, or other secrets unless specifically required for coordinated
investigation.

## Scope

Security-sensitive areas include, among others:

- generator path and filesystem safety
- generated-project deployment tooling
- archive/package path handling
- SSH/SFTP deployment behavior
- handling of local configuration and credentials
- GitHub Actions and release automation
- validation boundaries between HeimForge and generated repositories

Ordinary bugs, documentation issues, feature requests, and project-specific
Valheim gameplay problems should use the normal issue forms instead.

## Disclosure

Please allow maintainers reasonable time to investigate and prepare a fix
before publicly disclosing an unresolved vulnerability.
