# Validation Checks

The gap analysis framework performs 6 validation checks across all scripts.

## Check Numbering

All scripts use a consistent global check numbering system:

| Check # | Category | Description | Pass/Fail Impact |
|---------|----------|-------------|------------------|
| **1** | AWS STS Resources | Validates STS policy files exist in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `resources/sts/{version}/` and match OCP release changes (per-file comparison) | Exit code 1 on FAIL |
| **2** | AWS STS Admin Ack | Validates admin acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/sts/{version}/` | Exit code 1 on FAIL |
| **3** | GCP WIF Resources | Validates WIF template (vanilla.yaml) in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `resources/wif/{version}/` and matches OCP release changes (per-file comparison) | Exit code 1 on FAIL |
| **4** | GCP WIF Admin Ack | Validates admin acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/wif/{version}/` | Exit code 1 on FAIL |
| **5** | OCP Admin Gates | Validates admin gates from cluster-version-operator are acknowledged in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/ocp/{version}/` (conditional: if gates exist, both files required; if no gates, both files must be absent) | Exit code 1 on FAIL |
| **6** | Feature Gates | Analyzes feature gate changes from Sippy API. **Z-stream behavior:** When comparing z-stream versions (e.g., 4.21.15 → 4.21.16), shows default feature gates instead of differences, as z-stream updates should not change feature gates (informational only) | Always PASS (exit code 0) |
| **8** | OCM Version Gates | Validates OCM version gate existence, configurations, and metadata for target OCP versions compared to baseline version gates | Always PASS (exit code 0) |


## Check Execution by Script

### gap-aws-sts.py
- **Check 1:** AWS STS Resources Validation
- **Check 2:** AWS STS Admin Acknowledgment

### gap-gcp-wif.py
- **Check 3:** GCP WIF Resources Validation
- **Check 4:** GCP WIF Admin Acknowledgment

### gap-ocp-gate-ack.py
- **Check 5:** OCP Admin Gate Acknowledgments

### gap-ocm-version-gate.py
- **Check 8:** OCM Version Gates Validation (Informational)

### gap-feature-gates.py
- **Check 6:** Feature Gates Analysis (Informational)

### gap-all.sh (Combined)
Runs all checks in order:
1. AWS STS (Checks 1-2)
2. GCP WIF (Checks 3-4)
3. OCP Admin Gates (Check 5)
4. OCM Version Gates (Check 8)
5. Feature Gates (Check 6) - Always executed last

## Output Format

All checks follow a consistent output format:

### Success Output
```
============================================================
✓ VALIDATION PASSED - All checks successful
============================================================

CHECK #X: [Check Name] [PASS]
  Location: https://github.com/openshift/managed-cluster-config/tree/master/...
  ✓ Details about what was validated
  ✓ Additional success information
```

### Failure Output
```
============================================================
✗ VALIDATION FAILED
============================================================

CHECK #X: [Check Name] [FAIL]
Location: https://github.com/openshift/managed-cluster-config/tree/master/...

[Detailed error messages with GitHub URLs]
```

## Validation Results: Errors vs Warnings

The validation system distinguishes between **errors** (blocking issues) and **warnings** (informational):

| Result Type | Description | Impact |
|-------------|-------------|--------|
| **ERROR** | Mismatch between OCP release and managed-cluster-config (missing expected changes) | Validation FAILS (exit 1) |
| **WARNING** | Unexpected changes in managed-cluster-config (not in OCP release payload) | Validation PASSES but warns (exit 0) |

### Example Output

**ERROR (Validation Fails):**
```
MISMATCH: Expected actions added in OCP release but NOT found in managed-cluster-config:
  • ec2:DescribeVpcEndpoints
  • s3:CreateBucket
  Review policies at: https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/4.22
```

**WARNING (Validation Passes with Information):**
```
UNEXPECTED: Actions added in managed-cluster-config (not in OCP release):
  • ec2:DescribeNetworkInterfaces
  Review policies at: https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/4.22
  Files with unexpected changes:
    - sts_installer_permission_policy.json
      Introduced in PR #1234: https://github.com/openshift/managed-cluster-config/pull/1234
```

**PR Link Feature:** When unexpected changes are detected (warnings), the validation system automatically searches for the GitHub PR that introduced the change using the GitHub REST API (unauthenticated, 60 requests/hour). If a `GH_TOKEN` is available, it uses authenticated requests for higher rate limits and falls back to `gh` CLI if needed. This helps identify the context and reasoning behind managed-cluster-config changes that differ from the OCP payload.

## Validation Details

### Check 1: AWS STS Resources

**What it validates:**
- Target version directory exists: `resources/sts/{version}/`
- All policy files are valid JSON with required structure
- Policy changes match OCP release credential request changes using **per-file comparison**
- Per-file comparison aggregates all permission changes across individual CredentialRequest files (a permission can be new to one CR but already exist in another)
- No unexpected files added or removed
- Actions (permissions) in managed-cluster-config match OCP release per-file changes

**Files checked:**
- All JSON files dynamically discovered in `resources/sts/{version}/`
- Typically 30+ policy files

**Pass criteria:**
- All policy files exist and are valid JSON
- Policy changes match OCP release changes exactly (ERRORS cause failure)
- Unexpected permissions generate WARNINGS but do not fail validation

### Check 2: AWS STS Admin Ack

**What it validates:**
- `config.yaml` exists and is valid
- `config.yaml` has correct baseline version selector
- `osd-sts-ack_CloudCredential.yaml` exists and is valid
- CloudCredential has correct upgrade version annotation

**Files checked:**
- `deploy/osd-cluster-acks/sts/{version}/config.yaml`
- `deploy/osd-cluster-acks/sts/{version}/osd-sts-ack_CloudCredential.yaml`

**Pass criteria:**
- Both files exist and are valid YAML
- Baseline version matches expected (target - 1)
- Upgrade version matches target version

### Check 3: GCP WIF Resources

**What it validates:**
- Target version directory exists: `resources/wif/{version}/`
- `vanilla.yaml` exists and is valid
- WIF template has correct structure (id, kind, service_accounts)
- GCP permissions in template match OCP release changes using **per-file comparison**
- Per-file comparison aggregates all permission changes across individual CredentialRequest files (a permission can be new to one CR but already exist in another)

**Files checked:**
- `resources/wif/{version}/vanilla.yaml`

**Pass criteria:**
- vanilla.yaml exists and is valid YAML
- Template structure is correct
- GCP permissions match OCP release changes exactly (ERRORS cause failure)
- Unexpected permissions generate WARNINGS but do not fail validation

### Check 4: GCP WIF Admin Ack

**What it validates:**
- `config.yaml` exists and is valid
- `config.yaml` has correct baseline version selector
- `osd-wif-ack_CloudCredential.yaml` exists and is valid
- CloudCredential has correct upgrade version annotation

**Files checked:**
- `deploy/osd-cluster-acks/wif/{version}/config.yaml`
- `deploy/osd-cluster-acks/wif/{version}/osd-wif-ack_CloudCredential.yaml`

**Pass criteria:**
- Both files exist and are valid YAML
- Baseline version matches expected (target - 1)
- Upgrade version matches target version

### Check 5: OCP Admin Gates

**What it validates:**
- Admin gates from baseline version are acknowledged in target version
- Acknowledgment structure follows conditional presence rules
- All required gates are acknowledged when gates exist
- `config.yaml` and `admin-ack.yaml` are present together or absent together

**Z-stream vs Cross-minor Behavior:**
- **Z-stream upgrade** (e.g., 4.19.30 → 4.19.31): Gates from 4.19 are validated against acknowledgments in 4.20 (next minor)
  - Purpose: Detect if a z-stream adds a new gate that isn't acknowledged in the next minor version
  - Example: `OPENSHIFT_VERSION=4.19` validates gates in 4.19 against acks in 4.20
- **Cross-minor upgrade** (e.g., 4.19 → 4.20): Gates from 4.19 are validated against acknowledgments in 4.20
  - Standard validation: gates in version X must be acknowledged in version X+1

**Conditional validation logic:**
- **If gates exist in baseline**: BOTH `config.yaml` AND `admin-ack.yaml` MUST be present in target, all gates must be acknowledged
- **If no gates in baseline**: BOTH files MUST be absent (directory should not exist)
- Files must always be present together or absent together

**Files checked:**
- Admin gates from: `github.com/openshift/cluster-version-operator/release-{version}/...`
- Acknowledgments from: `deploy/osd-cluster-acks/ocp/{version}/admin-ack.yaml`
- Config from: `deploy/osd-cluster-acks/ocp/{version}/config.yaml`

**Pass criteria:**
- **No gates scenario**: Both `config.yaml` and `admin-ack.yaml` are absent
- **Gates exist scenario**: Both files present, all gates acknowledged, config.yaml has correct baseline version

**Orphaned Acknowledgment Files:**

When no admin gates exist in cluster-version-operator, acknowledgment files use a "both or neither" validation rule:

**Acknowledgment File Names:** Either `admin-ack.yaml` OR `admin-gates.yaml` is acceptable (script checks for both).

**Validation Rules (when no gates exist):**
- **Both files present** (acknowledgment file + config.yaml): **WARNING** with PR link (exit 0)
- **Only one file present**: **FAIL** - both files required together (exit 1)
- **Neither file present**: **PASS** - normal expected state (exit 0)

**Check order:** Acknowledgment file (admin-ack.yaml or admin-gates.yaml) is checked first, then config.yaml.

**Example Warning (both files present, no gates):**
```
⚠️ Warnings
- No admin gates found in cluster-version-operator for version 4.21, but unexpected admin-ack.yaml file is present in managed-cluster-config
  File: deploy/osd-cluster-acks/ocp/4.21/admin-ack.yaml
  Introduced in: https://github.com/openshift/managed-cluster-config/pull/2657
```

**PR Detection:** Uses commit history API to find the exact PR that added the admin-ack.yaml file, providing accurate attribution rather than title-based keyword matching.

### Check 6: Feature Gates

**What it analyzes:**
- New feature gates added
- Feature gates removed
- Feature gates newly enabled by default
- Feature gates removed from default

**Data source:**
- Sippy API: `https://sippy.dptools.openshift.org/api/feature_gates?release={version}`

**Z-stream display behavior:**
- For z-stream comparisons (e.g., 4.21.15 → 4.21.16), the HTML report displays default feature gates in a collapsible drop-down list to improve readability
- The summary shows "📋 View all N Default:Hypershift gates (click to expand)"
- This helps distinguish informational gate listings from actual changes

**Pass criteria:**
- Always PASS (informational only)
- Analysis completes successfully
- Changes are tracked but do not affect exit code

### Check 8: OCM Version Gates

**What it analyzes:**
- Checks if target minor version has corresponding version gate in OCM (via clusters-mgmt API `/api/clusters_mgmt/v1/version_gates`)
- Verifies enabled/disabled configurations and gate metadata (labels, descriptions, documentation links)
- Compares gate configurations between baseline (Y-1) and target (Y) to identify new or removed gates

**Data source:**
- OCM API: `/api/clusters_mgmt/v1/version_gates` (via OCM CLI `ocm get`)

**Pass criteria:**
- Always PASS (informational/warning only)
- Script exits 0 even if gates are missing or inconsistent
- Script exits 1 on fatal execution errors (e.g. invalid arguments, missing dependencies, etc.)
- Fallback gracefully to simulated/dry-run gates configuration if OCM credentials or CLI are absent

## Version Resolution

### OpenShift 5.x Major Version Mapping

Starting with OpenShift 5.0, the framework supports special version mappings to handle the major version transition from 4.x to 5.x:

**Upgrade Paths:**
- 4.19 → 4.20 → 4.21 → 4.22 → 4.23 (continues in 4.x line)
- 4.22 → 5.0 (first major bump to 5.x)
- 4.23 → 5.1 (second path to 5.x)
- 5.1 → 5.2 → 5.3 → ... (normal 5.x progression)

**Special Baseline Mappings:**

When using `--version` or `OPENSHIFT_VERSION` with 5.x versions, the framework automatically maps to the correct 4.x baseline:

| Target Version | Baseline Resolution | Example |
|---------------|---------------------|---------|
| `5.0` | 4.22.x (latest stable) | BASE=4.22.15, TARGET=5.0.0-rc.0 |
| `5.1` | 4.23.x (latest candidate) | BASE=4.23.0-rc.1, TARGET=5.1.0-rc.0 |
| `5.2+` | 5.(x-1) (normal progression) | BASE=5.1.5, TARGET=5.2.0-rc.0 |

**Usage Examples:**

**Python:**
```bash
# Compare 4.22 → 5.0 (first major bump)
python3 ./scripts/gap-aws-sts.py --version 5.0
# Resolves to: baseline=4.22.15, target=5.0.0-rc.0

# Compare 4.23 → 5.1 (second path to 5.x)
python3 ./scripts/gap-gcp-wif.py --version 5.1
# Resolves to: baseline=4.23.0-rc.1, target=5.1.0-rc.0

# Compare 5.1 → 5.2 (normal 5.x progression)
python3 ./scripts/gap-feature-gates.py --version 5.2
# Resolves to: baseline=5.1.5, target=5.2.0-rc.0
```

**Bash:**
```bash
# Using OPENSHIFT_VERSION environment variable
OPENSHIFT_VERSION=5.0 ./scripts/gap-all.sh
# Resolves to: BASE=4.22.15, TARGET=5.0.0-rc.0

OPENSHIFT_VERSION=5.1 ./scripts/gap-all.sh
# Resolves to: BASE=4.23.0-rc.1, TARGET=5.1.0-rc.0

# Using --version flag
./scripts/gap-all.sh --version 5.0  # Same as above
./scripts/gap-all.sh --version 5.1
```

**Why This Mapping Exists:**

The special mappings for 5.0 and 5.1 reflect the actual OpenShift upgrade paths during the major version transition:
- Clusters on 4.22 can upgrade to 5.0
- Clusters on 4.23 can upgrade to 5.1
- Starting with 5.2, upgrades follow normal sequential progression (5.1 → 5.2)

**Explicit Version Override:**

You can always override the automatic mapping by specifying both baseline and target explicitly:

```bash
# Override automatic mapping
./scripts/gap-all.sh --baseline 4.21 --target 5.0
python3 ./scripts/gap-aws-sts.py --baseline 4.23 --target 5.0
```

## Exit Codes

### Individual Scripts (gap-aws-sts.py, gap-gcp-wif.py, gap-ocp-gate-ack.py)
- **Exit 0 (PASS):** All relevant checks passed OR dry-run mode
- **Exit 1 (FAIL):** One or more checks failed OR execution error

### Feature Gates Script (gap-feature-gates.py)
- **Exit 0 (PASS):** Always (informational only) OR dry-run mode
- **Exit 1 (FAIL):** Only on execution error (network, invalid version, etc.)

### OCM Version Gate Script (gap-ocm-version-gate.py)
- **Exit 0 (PASS):** Always (informational only) OR dry-run mode
- **Exit 1 (FAIL):** Only on execution error (missing Python dependency, syntax error, etc.)

### Combined Script (gap-all.sh)
- **Exit 0 (PASS):** All checks 1-5 passed (check 6 is informational) OR dry-run mode
- **Exit 1 (FAIL):** Any of checks 1-5 failed OR execution error

## CI/CD Integration

The check numbering is consistent across:
- Console output
- Report files (HTML, JSON)
- Exit codes
- Log messages

This allows CI/CD systems to reliably:
- Parse specific check results from logs
- Identify which validation failed
- Link directly to [managed-cluster-config](https://github.com/openshift/managed-cluster-config) files needing updates
