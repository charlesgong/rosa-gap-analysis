---
name: ocm-version-gate-gap
description: >
  Analyze OCM version gate configurations for OpenShift upgrade releases.
  Verifies that version gates exist for target OCP versions and checks metadata/configurations.
  Gracefully handles missing CLI tools or tokens by falling back to high-fidelity mock data.
  Automatically generates comprehensive reports in HTML and JSON formats.
compatibility:
  required_tools:
    - python3
    - ocm (optional, for live queries)
---

# OCM Version Gate Gap Analysis

Validate and compare OCM (OpenShift Cluster Manager) version gate configurations between the baseline and target OpenShift versions.

## When to Use

- Planning managed cluster upgrades (OSD, ROSA) in OCM environments
- Validating target version gate readiness prior to GA release
- Checking version gate consistency across OCP releases
- Verifying version gate configurations (STS only, warning messages, documentation URLs)
- CI/CD pipelines validating release candidate milestones

## Workflow

1. Parse baseline and target versions (default: auto-detect latest stable → latest candidate)
2. Connect to OCM API via `ocm` CLI tool:
   - Check if the `ocm` binary is in the `PATH`
   - Read offline OCM token from environment variable `OCM_TOKEN` or `/var/run/ocm-token/token`
   - Perform OCM authentication and query `/api/clusters_mgmt/v1/version_gates`
3. Fall back gracefully to mock version gates if OCM credentials or CLI are absent (always exit 0 for validation checks)
4. Compare gate definitions between baseline (Y-1) and target (Y)
5. Perform configuration validation checks:
   - Ensure the target version has at least one configured gate
   - Validate metadata fields: ensure each gate has an ID, description, and valid documentation URL
6. Generate timestamped HTML and JSON reports under the `reports/` folder

## Script Usage

**Single version (recommended):**
```bash
# Auto-resolves baseline and target
python3 ./scripts/gap-ocm-version-gate.py --version 4.22

# Using environment variable
OPENSHIFT_VERSION=4.22 python3 ./scripts/gap-ocm-version-gate.py

# With verbose output
python3 ./scripts/gap-ocm-version-gate.py --version 4.22 --verbose

# Dry-run mode (exit early without analysis)
python3 ./scripts/gap-ocm-version-gate.py --version 4.22 --dry-run

# Custom report directory
python3 ./scripts/gap-ocm-version-gate.py --version 4.22 --report-dir /custom/reports
```

**Explicit baseline and target:**
```bash
python3 ./scripts/gap-ocm-version-gate.py --baseline 4.21 --target 4.22
```

**Auto-detect (no arguments):**
```bash
# Compares latest stable → latest candidate
python3 ./scripts/gap-ocm-version-gate.py
```

**Generated Reports:**
```bash
reports/gap-analysis-ocm-version-gate_4.21_to_4.22_20260618_120000.html  # HTML Report
reports/gap-analysis-ocm-version-gate_4.21_to_4.22_20260618_120000.json  # JSON Payload
```

**Exit Codes:**
- `0`: Analysis completed successfully (including when missing gates or validation discrepancies are discovered)
- `1`: Unexpected execution error (e.g. invalid flags, missing system libraries, uncaught python exception)

## Key Validation Checks

1. **Gate Existence**: Checks if target version has a version gate configured in OCM.
2. **Metadata Consistency**: Validates that all gates contain required fields (`id`, `description`, `documentation_url`, `label`, etc.).
3. **Difference Comparison**: Identifies new gates added for the target version and deprecated gates from the baseline version.

## Output Example

**With OCM Token (Live Analysis):**
```
[INFO] Starting OCM Version Gate Gap Analysis
[INFO] Baseline version: 4.21 (minor: 4.21)
[INFO] Target version: 4.22 (minor: 4.22)
[INFO] Loaded OCM offline token from /var/run/ocm-token/token
[INFO] Authenticating with OCM CLI using token...
[INFO] Executing live OCM GET request /api/clusters_mgmt/v1/version_gates...
[SUCCESS] Successfully retrieved 12 live version gates from OCM.
[INFO] =========================================
[INFO]   OCM Version Gate Analysis Summary
[INFO] =========================================
[SUCCESS] ✓ Connected to live OCM API.
[INFO] Baseline version: 4.21.14 (4.21)
[INFO] Target version:   4.22.0-rc.3 (4.22)
[INFO] -----------------------------------------
[SUCCESS] ✓ Found 1 gate(s) configured for baseline version 4.21.x
[SUCCESS] ✓ Found 1 gate(s) configured for target version 4.22.x
[SUCCESS] ✓ All gate configurations contain valid and complete metadata.
[INFO] JSON report generated: reports/gap-analysis-ocm-version-gate_4.21_to_4.22_20260618_101015.json
[INFO] HTML report generated: reports/gap-analysis-ocm-version-gate_4.21_to_4.22_20260618_101015.html
[SUCCESS] ============================================================
[SUCCESS] ✓ VALIDATION PASS - OCM Version Gates Complete
[SUCCESS] ============================================================
```

**Without OCM Token (Graceful Fallback Mode):**
```
[INFO] Starting OCM Version Gate Gap Analysis
[INFO] Baseline version: 4.21 (minor: 4.21)
[INFO] Target version: 4.22 (minor: 4.22)
[WARNING] OCM CLI binary missing in PATH. Cannot perform live check.
[WARNING] Could not execute live check. Falling back to dry-run/mock gates configuration.
[INFO] =========================================
[INFO]   OCM Version Gate Analysis Summary
[INFO] =========================================
[WARNING] ⚠️  NOTE: Operating in DRY-RUN / SIMULATED mode (No OCM credentials/CLI detected).
[INFO] Baseline version: 4.21.14 (4.21)
[INFO] Target version:   4.22.0-rc.3 (4.22)
[INFO] -----------------------------------------
[SUCCESS] ✓ Found 1 gate(s) configured for baseline version 4.21.x
[SUCCESS] ✓ Found 1 gate(s) configured for target version 4.22.x
[SUCCESS] ✓ All gate configurations contain valid and complete metadata.
[INFO] JSON report generated: reports/gap-analysis-ocm-version-gate_4.21_to_4.22_20260618_101130.json
[INFO] HTML report generated: reports/gap-analysis-ocm-version-gate_4.21_to_4.22_20260618_101130.html
[SUCCESS] ============================================================
[SUCCESS] ✓ VALIDATION PASS - OCM Version Gates Complete
[SUCCESS] ============================================================
```
