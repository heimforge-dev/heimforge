# HeimForge Test Performance Audit

## Summary

The original test suite spent most of its time regenerating and certifying the same generated project in individual test bodies. Fixture and class setup were not the dominant cost. Two narrow changes removed duplicate work without changing the generator, deployment, filesystem-safety, or MSBuild-evaluation boundaries:

- **Tranche 1** reused a certified generated-project seed and gave each caller a private mutable clone.
- **Tranche 2** deduplicated validation steps within one bootstrap validation transaction.

The certified warm profile improved from **3097.32 seconds** to **807.99 seconds**: about **2289.33 seconds saved**, **73.9% lower wall time**, and **3.83x faster**. The final run had **560 tests** and zero failures, errors, or skips.

The remaining runtime is predominantly meaningful integration and adversarial coverage. A third optimization track was investigated and deliberately rejected where it changed tested semantics or weakened a safety boundary.

## Certified baselines

| Profile                 | Tests |                Wall time | Test body time |         Max RSS | Result                  |
| ----------------------- | ----: | -----------------------: | -------------: | --------------: | ----------------------- |
| Original plain unittest |   552 | 3741.24 s (about 62m21s) |              — |       199940 kB | 0 failures/errors/skips |
| Original warm profile   |   552 | 3097.32 s (about 51m37s) |     3052.136 s |       197008 kB | 0 failures/errors/skips |
| After Tranche 1         |   555 | 1120.42 s (about 18m40s) |     1111.026 s | about 197624 kB | 0 failures/errors/skips |
| After Tranche 2         |   560 |  807.99 s (about 13m28s) |      803.487 s |       196228 kB | 0 failures/errors/skips |

These timings were collected in the same audit environment with Python 3.10.12 and .NET SDK 8.0.424. Absolute wall times are machine- and cache-sensitive; the before/after comparisons are the meaningful performance signal.

The original warm profile spent about 44.857 seconds in class setup, with teardown effectively negligible. The evidence therefore pointed to repeated production generation and certification inside test bodies, not unittest fixture machinery.

## Tranche 1: certified generated-fixture reuse

Commit: `a76d45a test: reuse certified generated fixtures`

The change caches a certified generated-project seed downstream of generation and creates a private mutable clone for each caller. The seed is internal; the real `generate()` and `generate_into_temp` paths remain unchanged.

Real generation remains covered at the boundaries that need it, including:

- unsafe output and promotion behavior;
- optional-module matrices;
- template contamination and output-surface checks;
- no-stale-module behavior;
- bootstrap/generated independence;
- rendered-output and identity checks; and
- validation-before-promotion.

Result relative to the original warm profile: about **1976.9 seconds saved**, **63.8% lower wall time**, and **2.76x faster**.

## Tranche 2: validation deduplication

Commit: `23e0a40 perf: deduplicate generated project validation`

One real bootstrap validation previously repeated the following work:

- `suite_metadata.py check` three times;
- scaffold unittest twice; and
- 24 successful `dotnet msbuild -getProperty` evaluations for the default four-project suite.

The change performs one explicit full metadata certification and one explicit scaffold certification. Nested preflight/test calls skip only prerequisites already certified in the same validation transaction. Standalone generated preflight and test behavior is unchanged. The orchestration variable `SUITE_BOOTSTRAP_VALIDATION` is exact-value gated and consumed before child-process inheritance.

The no-dotnet structural path and late-dotnet semantics remain intact. When dotnet is available, bootstrap certification still runs one `dotnet test`; standalone `scripts/test.sh` continues to require dotnet.

Warm `generate()` improved from a mean of about **8.505 seconds** to **4.06 seconds**: **52.3% lower generation time** and about **2.10x faster**.

Result relative to Tranche 1: about **312.43 seconds saved**, **27.9% lower wall time**, and the final certified profile reached **807.99 seconds**.

## Tranche 3: investigated and rejected optimizations

### Deploy manifest track

The deploy-manifest path measured about **199.179 seconds**. That cost is meaningful integration coverage: real deploy subprocesses, metadata validation, filesystem operations, flock concurrency, destination alias/path behavior, fsync/durability, manifest mutation, and stale-entry removal. The small sleeps and polling intervals are synchronization sentinels, not ordinary delays.

Replacing subprocesses or locks with mocks, or shortening synchronization intervals, would weaken the behavior being certified. No optimization was applied.

### MSBuild fanout track

The default suite has four projects and two configurations. The current contract independently evaluates eight project/configuration combinations and twelve properties per combination: **96 exact values**. The warm full check measured about **2.28 seconds** on average.

An external proof of concept produced all **96/96** expected values with one outer `dotnet msbuild` invocation and a warm mean of about **0.420 seconds**. That nominally suggests an **81.6% saving** and **5.43x** property-query speedup, but it is not a certified production optimization.

The candidate was rejected because it changed MSBuild semantics and required fragile project-hook injection:

- Required injection through `CustomAfterMicrosoftCommonTargets` overrode a valid project-defined hook and produced the wrong `AssemblyName` for Debug/Release.
- The aggregator executed `InitialTargets`, while production `-getProperty` evaluation does not execute child targets. A sentinel side effect proved the semantic difference.
- The approach could interfere with legitimate MSBuild hooks and adds maintenance and security risk.

**Do not replace the independent MSBuild `-getProperty` evaluations with an aggregator merely because an aggregator reproduces the same property strings for normal projects. The audit demonstrated that tested aggregation approaches changed project evaluation/target semantics and interfered with legitimate MSBuild hooks.**

Modeled 280–455 second hypothetical suite runtimes based on the rejected aggregator are not certified baselines and must not be used as performance targets.

## Current safe baseline and stopping point

The safe, certified baseline is the Tranche 2 profile: **560 tests in 807.99 seconds**, with zero failures, errors, or skips. Further optimization should not weaken:

- generator-boundary coverage;
- deployment concurrency and filesystem safety;
- MSBuild evaluation semantics;
- validation-before-promotion; or
- adversarial and integration behavior.

The audit stops here. Any future performance work needs new evidence that preserves those boundaries rather than optimizing the modeled rejected paths.

## Reproduction and raw evidence

The measurements were collected during the audit on the `test-performance-audit` branch. Raw local artifacts are outside the repository under `~/heimforge-audit-results/`:

- `baseline/unittest-run1.time`
- `profile-run1-recovered-summary.txt`
- `profile-after-seed-cache/`
- `tranche2-validation-dedupe/`
- `profile-after-validation-dedupe/`
- `tranche3-prewalk/`
- `tranche3-msbuild-equivalence/`

`profile-run1-recovered-summary.txt` is a reconstructed summary from captured baseline output; the original pre-optimization per-test CSV was overwritten during the audit.

These artifacts support the measured values above but are not required for normal repository operation.
