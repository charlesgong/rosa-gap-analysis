# GA Readiness Validation

Standalone validation script for SREs to verify ROSA Production GA readiness prerequisites before a new OpenShift version is marked General Availability (GA).

> **Note:** This script is **not** part of the CI pipeline (`gap-all.sh`). It lives in `scripts/prod/` and is intended to be run manually by SREs.

## Location

```
scripts/prod/gap-ga-validation.py
```

## Purpose

Automates the pre-GA readiness checklist to ensure all production prerequisites are met before a new OCP release is promoted to GA on ROSA. The script performs the following checks:

| Check | Description |
|-------|-------------|
| **Channel Availability** | Verifies the target version is available in required OCM channels (candidate, fast, stable) |
| **ROSA CLI Compatibility** | Confirms the ROSA CLI detects the target version across all channel groups |
| **AWS Marketplace Enablement** | Verifies AWS marketplace enablement for ROSA Classic and ROSA HCP across channels (stable, fast, candidate, eus) |
| **GCP Marketplace Enablement** | Verifies GCP marketplace enablement across channels (stable, fast, candidate, eus) |
| **Version Gates** | Checks OCM version gates are properly configured for the target release |
| **Upgrade Paths** | Confirms upgrade paths from supported versions are available via Cincinnati graph API |
| **CI Job Status** | Checks that gap analysis Prow CI jobs are passing for the target version |
| **SOP & Runbooks Update Status** | Validates that Gap Analysis SOPs and runbooks are updated for the target version |
| **GCP WIF Template Compatibility** | Checks that GCP WIF template configurations in OCM support the target version |

## Prerequisites

- `ocm` CLI (logged in) — for channel availability, version gates, GCP WIF, and GCP marketplace checks
- `rosa` CLI (logged in) — for ROSA CLI compatibility and AWS marketplace checks
- `python3` with `PyYAML` and `Jinja2`
- Network access to OCM API, Cincinnati API, Prow CI, and GitHub

## Usage

```bash
# Single version (auto-resolves baseline and target)
python3 ./scripts/prod/gap-ga-validation.py --version 4.22

# Explicit baseline and target
python3 ./scripts/prod/gap-ga-validation.py --baseline 4.21 --target 4.22

# Dry-run (show resolved versions without running checks)
python3 ./scripts/prod/gap-ga-validation.py --version 4.22 --dry-run

# Custom report directory
python3 ./scripts/prod/gap-ga-validation.py --version 4.22 --report-dir /tmp/reports

# Using environment variables
OPENSHIFT_VERSION=4.22 python3 ./scripts/prod/gap-ga-validation.py
REPORT_DIR=/tmp/reports python3 ./scripts/prod/gap-ga-validation.py --version 4.22
```

## CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--version` | Single version to analyze (auto-resolves baseline and target) | — |
| `--baseline` | Baseline version (requires `--target`) | — |
| `--target` | Target version (requires `--baseline`) | — |
| `--report-dir` | Directory to store reports | `reports/` or `REPORT_DIR` env var |
| `--dry-run` | Show resolved versions and exit | — |
| `--verbose` | Enable verbose logging | — |

## Version Resolution

The script follows the same version resolution logic as the CI pipeline:

- `--version 4.22` → auto-resolves baseline (e.g., 4.21.x stable) and target (e.g., 4.22.0-rc.x candidate)
- `--baseline 4.21 --target 4.22` → resolves both to their latest patch versions
- Full versions (e.g., `4.22.3`) are used directly as the target without re-resolution

## Output

The script generates two report files in the report directory:

- **JSON:** `gap-analysis-ga-validation_GA_readiness_{version}_{timestamp}.json`
- **HTML:** `gap-analysis-ga-validation_GA_readiness_{version}_{timestamp}.html`

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed (no critical failures) |
| `1` | One or more critical failures detected |

## Example Output

```
[INFO] ROSA GA Readiness Validation
[INFO] =========================================
[INFO] Baseline version: 4.21.15
[INFO] Target version: 4.22.0-rc.3
[INFO] =========================================
[INFO] Executing: Verify channel availability (candidate, fast, stable)...
[SUCCESS] Channel Availability - Version 4.22 is available in channels: candidate, fast, stable.
[INFO] Executing: Check ROSA CLI detection and listing across channels...
[SUCCESS] ROSA CLI Compatibility - ROSA CLI detected target version 4.22 across all channels.
[INFO] Executing: Verify AWS marketplace enablement for ROSA Classic and ROSA HCP...
[SUCCESS] AWS Marketplace Enablement - Successfully verified AWS Marketplace enablement across channels.
[INFO] Executing: Verify GCP marketplace enablement across channels...
[SUCCESS] GCP Marketplace Enablement - Successfully verified GCP Marketplace enablement across channels.
[INFO] Executing: Verify OCM version gates are configured for the target release...
[SUCCESS] Version Gates - Found 1 version gate(s) for 4.22.
[INFO] Executing: Verify upgrade paths from supported versions are available via Cincinnati...
[SUCCESS] Upgrade Paths - Upgrade paths available in 3/3 channels.
[INFO] Executing: Check gap analysis Prow CI job status for the target version...
[SUCCESS] CI Job Status - Latest Prow job passed.
[INFO] Executing: Verify SOPs and runbooks updates...
[SUCCESS] SOP & Runbooks Update Status - Verified '4.22' is documented in Gap Analysis SOP.
[INFO] Executing: Verify GCP WIF template compatibility in OCM wif-configs...
[SUCCESS] GCP WIF Template Compatibility - GCP WIF template version 'v4.22' is supported.

✅ PASSED - Target version GA readiness validation successful
```
