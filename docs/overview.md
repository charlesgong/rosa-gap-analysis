# Overview

OpenShift Gap Analysis Framework for comparing cloud credential policies and feature gates across OpenShift versions.

## What It Does

Identifies changes between OpenShift versions through 8 validation checks:

**Checks 1-2: AWS STS Validation**
- **Check 1:** AWS STS Resources - Validates policy files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- **Check 2:** AWS STS Admin Ack - Validates acknowledgment files for AWS clusters

**Checks 3-4: GCP WIF Validation**
- **Check 3:** GCP WIF Resources - Validates WIF template in [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- **Check 4:** GCP WIF Admin Ack - Validates acknowledgment files for GCP clusters

**Check 5: OCP Admin Gate Acknowledgments**
- **Check 5:** OCP Admin Gates - Validates upgrade readiness by checking required gate acknowledgments

**Check 6: Versions & Channels**
- **Check 6:** Versions & Channels - Validates version availability across OCM release channels and marketplace enablement (ROSA Classic, ROSA HCP, OSD GCP)

**Check 7: OCM Version Gates**
- **Check 7:** OCM Version Gates - Validates OCM version gate existence, configurations, and metadata

**Check 8: Feature Gates (Informational)**
- **Check 8:** Feature Gates - Tracks feature additions, removals, and default enablement changes (informational only, always PASS)

## How It Works

```
1. Specify versions (or auto-detect latest stable → candidate)
   ↓
2. Extract credential requests / feature gates
   ↓
3. Compare and generate reports (HTML, JSON)
   ↓
4. Review changes and assess impact
```

## Key Features

- **Automated extraction** - Uses `oc adm release extract` and Sippy API
- **Multi-format reports** - HTML and JSON
- **Auto-detection** - Automatically finds latest versions
- **CI/CD ready** - Exit codes designed for pipelines
- **Template-based** - Jinja2 templates for easy customization

## Use Cases

**Pre-Upgrade Assessment**
```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22
```

**Security Review**
```bash
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
jq '.comparison.actions.target_only' reports/*.json
```

**CI/CD Integration**
```bash
if ./scripts/gap-all.sh 2>&1 | grep -q "differences detected"; then
  echo "Review reports/"
fi
```

## Tools

**Scripts** (Python + Bash)
- Fast, consistent, CI-ready
- Automatic report generation
- Best for: Regular checks, automation

**Claude Skills** (AI-powered)
- Intelligent analysis, recommendations
- Context-aware suggestions
- Best for: Deep investigations, planning

## Data Sources

**AWS STS / GCP WIF:**
- `oc adm release extract --credentials-requests --cloud={aws,gcp}`
- Extracts CredentialsRequest manifests from release images to temporary directories
- Same approach as `osdctl iampermissions diff`
- Dynamically discovers files (no hardcoded lists)

**[managed-cluster-config](https://github.com/openshift/managed-cluster-config) Validation:**
- Uses `git clone --sparse-checkout` to efficiently fetch only needed directories
- Downloads only `resources/sts/{version}` or `resources/wif/{version}` 
- Compares [managed-cluster-config](https://github.com/openshift/managed-cluster-config) policies against OCP release changes
- All file discovery is dynamic - no hardcoded file lists

**Feature Gates:**
- `https://sippy.dptools.openshift.org/api/feature_gates?release={version}`
- Queries Sippy API for feature gate data

**OCP Admin Gate Acknowledgments:**
- `https://github.com/openshift/cluster-version-operator` - Admin gate ConfigMaps
- [`https://github.com/openshift/managed-cluster-config`](https://github.com/openshift/managed-cluster-config) - Acknowledgment ConfigMaps

## Implementation Details

**File Discovery:**
- OCP credential requests: Extracted to temporary directories, dynamically listed
- [managed-cluster-config](https://github.com/openshift/managed-cluster-config): Git sparse checkout to temporary directories
- No hardcoded file lists - everything discovered at runtime
- Efficient: Only downloads needed directories, not entire repositories

**Comparison Flow:**
1. Extract OCP release credential requests → temp directories
2. Sparse checkout [managed-cluster-config](https://github.com/openshift/managed-cluster-config) → temp directories
3. Compare files and actions between versions
4. Validate [managed-cluster-config](https://github.com/openshift/managed-cluster-config) matches OCP release changes
5. Cleanup all temporary directories

## Reports

**Formats:**
- HTML - Browser viewing, presentations
- JSON - Programmatic analysis, CI/CD

**Location:**
- Default: `./reports/`
- Configurable via `--report-dir` or `REPORT_DIR`

**Naming:**
```
gap-analysis-<type>_<baseline>_to_<target>_<timestamp>.<ext>
```

## Quick Links

- [Getting Started](getting-started.md) - Installation and basic usage
- [Configuration](configuration.md) - CLI args, env vars, version resolution
- [Development](development.md) - Contributing and customization
