# Versioning and stability

gleanly follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

## What is public API

- Everything exported from `gleanly` (`load`, `aload`, `search`, `asearch`, `Client`,
  `LoadOptions`, the output models and the errors).
- The fields of the output models (`Document`, `Block`, `QualityReport`,
  `ComplianceInfo`, `Provenance`, `FetchTrace`, `SearchResponse`, ...).
- The `gleanly` command line.

Modules and names starting with an underscore, and anything under `bench/`, are internal.

## Before 1.0 (now)

- `0.x` releases may change the public API, but only with a note in
  [CHANGELOG.md](../CHANGELOG.md) and, where possible, a `DeprecationWarning` for at least
  one minor release first.
- Alpha / beta / release-candidate builds are marked `a`, `b`, `rc` (e.g. `0.1.0a1`).

## From 1.0

- **PATCH**: bug fixes only.
- **MINOR**: new features; existing code keeps working. Deprecated names keep working
  and warn for at least two minor releases.
- **MAJOR**: breaking changes, listed under "Breaking" in the changelog with migration
  notes.

## Scores and verdicts

Scores (`quality.score`, `extraction_confidence`, ...) are measurements, and improving
how they are measured is not a breaking change. Their meaning (higher = more trustworthy,
0..1 range) and the `ai_use` values are stable. Changes to how they are computed are
listed in the changelog together with the benchmark result behind them.
