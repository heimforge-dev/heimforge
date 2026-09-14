# Testing

## Level 0: scaffold invariants

Run:

```text
python3 -m unittest discover -s tests/scaffold -p 'test_*.py' -v
```

These tests require no Valheim binaries and verify repository invariants such as metadata synchronization, project mapping, deployment side separation, Bash syntax, ignored local config, cross-platform net48 targeting support, compatibility attributes, and non-placeholder packaging.

## Level 1: pure C# unit tests

Must run without Valheim binaries:

```text
./scripts/test.sh
```

The script runs scaffold invariants first, then the C# unit tests.

## Level 2: plugin build validation

Build against the legitimate local Valheim/Jötunn development environment from WSL.

A first build may require Jötunn prebuild if publicized game references do not exist yet.

## Level 3: disposable dedicated-server smoke test

Verify BepInEx, Jötunn, suite plugin load, config generation, world initialization, and absence of fatal errors.

## Level 4: multiplayer integration

Exercise the compatibility matrix in `.context/references/testing.md` for changed networking modules.

Compilation and package generation are never sufficient proof of network correctness.
