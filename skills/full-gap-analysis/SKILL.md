---
name: full-gap-analysis
description: >
  Comprehensive gap analysis between OpenShift versions covering AWS STS policies,
  GCP WIF policies, feature gates, and OCP admin gate acknowledgments. Use when
  performing complete version upgrade assessment for managed OpenShift (OSD, ROSA).
  Exits 1 if any validation check (CHECK #1-7) fails; exits 0 if all checks pass. CHECK #8 (Feature Gates) is Info only.
compatibility:
  required_tools:
    - oc
    - jq
    - python3
    - PyYAML
---

# Full Gap Analysis

Orchestrate comprehensive gap analysis across OpenShift versions.
Automatically analyzes AWS STS policies, GCP WIF policies, feature gates, and OCP admin gate acknowledgments.

## When to Use

- Planning major version upgrades (e.g., 4.21 → 4.22)
- Comparing platform variants (ROSA Classic vs HCP)
- Cross-cloud comparison (OSD AWS vs GCP)
- Complete upgrade impact assessment for IAM/WIF policies
- Validating managed cluster upgrade readiness
- Quarterly upgrade planning
- CI/CD pipelines that need to detect policy changes and validate upgrade prerequisites

## What This Analyzes

Automatically analyzes all of:

1. **AWS STS IAM Policies**
   - IAM permission changes
   - Service account requirements
   - Security posture changes

2. **GCP WIF Configurations**
   - Workload Identity Federation changes
   - GCP IAM role/permission changes
   - Service account bindings

3. **Feature Gates**
   - New feature gates added
   - Feature gates removed
   - Gates newly enabled by default
   - Gates removed from default

4. **OCP Admin Gate Acknowledgments**
   - Admin gates requiring acknowledgment
   - Missing acknowledgment files
   - Unacknowledged gates that would block upgrades
   - Upgrade readiness validation

The script runs all analyses and reports if differences exist in any area.

## Workflow

### Step 1: Parse Request

Understand the comparison being requested:
- Baseline version (default: auto-detect latest stable)
- Target version (default: auto-detect latest candidate)
- Specific focus areas (if any)

The analysis automatically covers both AWS STS and GCP WIF platforms.

### Step 2: Use the Orchestrator Script

The `scripts/gap-all.sh` script runs credential policy analysis for both AWS and GCP:

**Auto-detect versions:**
```bash
# Compares latest stable → latest candidate
./scripts/gap-all.sh
```

**Single version (RECOMMENDED):**
```bash
# Auto-resolves baseline and target based on version type
# Baseline precedence: stable > candidate > CI > nightly
# Target precedence: candidate > CI > nightly
./scripts/gap-all.sh --version 4.21  # GA: z-stream (stable → stable)
./scripts/gap-all.sh --version 4.22  # Pre-GA: cross-minor (stable → candidate)
./scripts/gap-all.sh --version 4.23  # Other: cross-minor (candidate → candidate)

# Using environment variable
OPENSHIFT_VERSION=4.22 ./scripts/gap-all.sh

# Dry-run mode (verify versions without running analysis)
./scripts/gap-all.sh --version 4.21 --dry-run
./scripts/gap-all.sh --dry-run  # Show auto-detected versions
```

**Explicit versions (both required):**
```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# With full version strings
./scripts/gap-all.sh --baseline 4.21.6 --target 4.22.0-ec.3
```

**Environment variables (both required):**
```bash
# Override both versions
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-all.sh

# Use nightly target
BASE_VERSION=4.21 TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh
```

The script:
- Auto-detects versions if not specified (stable → candidate)
- Runs AWS STS policy analysis (Python)
- Runs GCP WIF policy analysis (Python)
- Runs feature gate analysis (Python)
- Runs OCP admin gate acknowledgment analysis (Python)
- Generates JSON reports for each analysis (used for combined report)
- Generates combined report aggregating all analyses (HTML, JSON)
- Logs detected differences to stdout/stderr
- Exits 1 if any validation check (CHECK #1-7) fails
- Exits 0 only when all validation checks pass
- Also exits 1 on execution failures (missing tools, network errors, etc.)

**Report Files Generated:**
- `reports/gap-analysis-aws-sts_*.json` (individual JSON only)
- `reports/gap-analysis-gcp-wif_*.json` (individual JSON only)
- `reports/gap-analysis-feature-gates_*.json` (individual JSON only)
- `reports/gap-analysis-ocp-gate-ack_*.json` (individual JSON only)
- `reports/gap-analysis-full_*.{html,json}` (combined report with all analyses)

**Use in CI/CD:**
```bash
# Exit code reflects validation result: 0=all checks passed, 1=one or more checks failed
if ./scripts/gap-all.sh --version 4.22; then
  echo "All validation checks passed - safe to proceed"
else
  echo "Validation failed - review reports for details"
fi

# Test against nightly
BASE_VERSION=4.21 TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh
```

### Step 3: Interpret Results

The script provides pass/fail indication via exit codes. For detailed analysis:

**Extract comparison data from JSON reports:**
```bash
# Run analysis to generate reports
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

# Extract specific data from JSON report
jq '.comparison.actions.target_only' reports/gap-analysis-aws-sts_*.json  # Added actions
jq '.comparison.actions.baseline_only' reports/gap-analysis-aws-sts_*.json  # Removed actions
jq '.validation' reports/gap-analysis-aws-sts_*.json  # Validation results
```

### Step 4: Perform Deep Analysis

Go beyond the scripts by:
- **Security assessment**: Evaluate new permissions for security implications
- **Impact assessment**: Prioritize IAM/WIF changes by criticality
- **Timeline analysis**: Identify upgrade blockers related to credentials
- **Customer communication**: Draft IAM policy update notices

## Output

The script outputs log messages for both platforms and exits based on validation results:

**No differences:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Baseline: 4.21
[INFO] Target: 4.22
[INFO] Gap Analysis checks: AWS STS, GCP WIF, Feature Gates, OCP Gate Acknowledgments

[INFO] Running AWS STS Policy Gap Analysis...
[SUCCESS] No AWS STS policy differences found

[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found

[INFO] Running Feature Gates Gap Analysis...
[SUCCESS] No feature gate differences found between 4.21 and 4.22

[INFO] Running OCP Admin Gate Acknowledgment Analysis...
[SUCCESS] No admin gates in 4.21, upgrade to 4.22 requires no acknowledgments

[INFO] Gap Analysis Complete!
[SUCCESS] No policy, feature gate differences, or gate acknowledgment issues found
```
Exit code: `0` (all validation checks PASSED)

**Differences found:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Baseline: 4.21
[INFO] Target: 4.22
[INFO] Gap Analysis checks: AWS STS, GCP WIF, Feature Gates, OCP Gate Acknowledgments

[INFO] Running AWS STS Policy Gap Analysis...
[INFO] Policy differences detected: 3 added, 1 removed

[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found

[INFO] Running Feature Gates Gap Analysis...
[INFO] Feature gate differences detected:
[INFO]   - New feature gates: 5
[INFO]   - Newly enabled by default: 2

[INFO] Running OCP Admin Gate Acknowledgment Analysis...
[INFO] ✅ UPGRADE READY: All gates acknowledged for 4.21 → 4.22

[INFO] Gap Analysis Complete!
[INFO] AWS STS: Policy differences detected
[INFO] Feature Gates: Differences detected
[INFO] Differences detected - review recommended
```
Exit code: `0` (validation PASSED) or `1` (validation FAILED - one or more checks failed)

## Comparison Scenarios

### Version Upgrade (All Platforms)
```
Baseline: 4.21
Target: 4.22
```
Analyzes all of:
- AWS STS IAM policy changes
- GCP WIF policy changes
- Feature gate changes
- OCP admin gate acknowledgments

Exits 1 if any validation check (CHECK #1-7) fails; exits 0 if all checks pass. CHECK #8 (Feature Gates) is Info only.

## Enhanced Analysis

Provide additional insights:

### Prioritization Matrix
| Change | Impact | Effort | Priority |
|--------|--------|--------|----------|
| New STS permission | High | Low | P0 |
| Removed WIF role | High | Medium | P0 |
| Changed permission scope | Medium | Low | P1 |

### Timeline Recommendations
- **Before upgrade**: Update IAM roles/policies in AWS/GCP
- **During upgrade**: Monitor for permission denied errors
- **After upgrade**: Validate all credential-dependent workloads

### Risk Assessment
- **High risk**: New required permissions, removed roles
- **Medium risk**: Changed permission scopes
- **Low risk**: Added optional permissions

## Going Beyond Scripts

While scripts provide credential policy data, add strategic value:
- Executive summaries for leadership
- Technical deep-dives for platform engineers
- Customer-facing IAM policy update guides
- Security risk mitigation strategies
- Rollback procedures for IAM changes

## Example Interaction

**User**: "Check if policies changed between latest stable and latest candidate"

**Response**:
```bash
# Auto-detect versions
./scripts/gap-all.sh
```

**User**: "Check if policies changed between 4.21 and 4.22"

**Response**:
```bash
# Single version auto-resolve (recommended)
./scripts/gap-all.sh --version 4.22

# Or explicit baseline and target
./scripts/gap-all.sh --baseline 4.21 --target 4.22
```

**User**: "Verify what versions will be used for 4.22 analysis"

**Response**:
```bash
# Dry-run mode shows versions without running analysis
./scripts/gap-all.sh --version 4.22 --dry-run
```

**User**: "Check against latest nightly"

**Response**:
```bash
BASE_VERSION=4.21 TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh
```

**If no changes:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Running AWS STS Policy Gap Analysis...
[SUCCESS] No AWS STS policy differences found
[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found
[INFO] Running Feature Gates Gap Analysis...
[SUCCESS] No feature gate differences found between 4.21 and 4.22
[SUCCESS] No policy or feature gate differences found
```
Exit code: `0` - All validation checks PASSED

**If changes detected:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Running AWS STS Policy Gap Analysis...
[INFO] Policy differences detected: 3 added, 1 removed
[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found
[INFO] Running Feature Gates Gap Analysis...
[INFO] Feature gate differences detected:
[INFO]   - New feature gates: 5
[INFO] AWS STS: Policy differences detected
[INFO] Feature Gates: Differences detected
[INFO] Differences detected - review recommended
```
Exit code: `0` (validation PASSED) or `1` (validation FAILED - CHECK #1-7)

**Next steps when changes detected:**
1. Run individual platform scripts to get detailed information
2. Extract detailed comparison data using the comparison functions
3. Analyze policy changes in depth
4. Assess security implications of new permissions
5. Evaluate upgrade complexity based on IAM/WIF changes
6. Generate prioritized update action plan
7. Provide go/no-go recommendation with security justification
