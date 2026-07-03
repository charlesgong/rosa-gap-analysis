# Configuration

Configuration options for gap analysis scripts.

## Command-Line Arguments

All Python scripts support:

```bash
--baseline <version>     # Baseline version (default: auto-detect)
--target <version>       # Target version (default: auto-detect)
--report-dir <path>      # Report directory (default: reports/)
--verbose                # Enable verbose logging
-h, --help               # Show help
```

**gap-all.sh** orchestrator supports additional arguments:

```bash
--version <version>      # Single version (auto-resolves baseline and target)
--dry-run                # Show resolved versions without running analysis
```

**Note:** For gap-all.sh, `--baseline` and `--target` must be used together, or use `--version` for single-version input.

## Environment Variables

```bash
BASE_VERSION=<version>       # Override baseline (must be used with TARGET_VERSION)
TARGET_VERSION=<version>     # Override target (must be used with BASE_VERSION)
                             # Supports special values: NIGHTLY, CANDIDATE
OPENSHIFT_VERSION=<version>  # Single version (auto-resolves baseline and target)
REPORT_DIR=<path>            # Report directory
OCM_TOKEN=<token>            # OCM Offline Token used to query live OCM API endpoints
                             # If unset, OCM checks will fall back to safe dry-run mode
```

**Note:** For gap-all.sh, `BASE_VERSION` and `TARGET_VERSION` must be used together, or use `OPENSHIFT_VERSION` for single-version input.

## Precedence

**For gap-all.sh**, versions are resolved in this order:
1. `--version` flag (auto-resolves both baseline and target)
2. `OPENSHIFT_VERSION` env var (auto-resolves both baseline and target)
3. `--baseline` AND `--target` flags (both required)
4. `BASE_VERSION` AND `TARGET_VERSION` env vars (both required)
5. Auto-detection (latest stable → latest candidate)

**For individual Python scripts**, versions are resolved independently:
1. Command-line flags (`--baseline` or `--target`)
2. Environment variables (`BASE_VERSION` or `TARGET_VERSION`)
3. Auto-detection

## Version Formats

### Supported Formats

```bash
# Minor version
--baseline 4.21 --target 4.22

# Full version
--baseline 4.21.7 --target 4.22.0-ec.4

# Pullspec
--baseline quay.io/openshift-release-dev/ocp-release:4.21.7-x86_64
```

### Special Keywords

```bash
TARGET_VERSION=NIGHTLY    # Latest dev nightly build
TARGET_VERSION=CANDIDATE  # Latest dev candidate (default)
```

## Auto-Detection

When versions are not specified:

- **Baseline**: Latest stable release for GA version
  - Queries: GA version (4.21) → Stable release (4.21.7)

- **Target**: Latest candidate release for dev version
  - Queries: Dev version (4.22 = GA+1) → Candidate (4.22.0-ec.4)

### Feature Gates Special Case

Feature gates API requires minor versions (4.21, 4.22).

Full versions are automatically converted:
- `4.21.7` → `4.21`
- `4.22.0-ec.4` → `4.22`

## Report Configuration

### Default Location

```bash
./reports/  # Current directory
```

### Custom Location

```bash
# Via flag
python3 ./scripts/gap-aws-sts.py --report-dir /custom/reports

# Via environment variable
REPORT_DIR=/tmp/reports ./scripts/gap-all.sh

# For CI artifacts
REPORT_DIR=${ARTIFACT_DIR}/gap-reports ./scripts/gap-all.sh
```

### Report Naming

```
gap-analysis-<type>_<baseline>_to_<target>_<timestamp>.<ext>

Examples:
  gap-analysis-aws-sts_4.21.7_to_4.22.0-ec.4_20260325_154133.html
  gap-analysis-aws-sts_4.21.7_to_4.22.0-ec.4_20260325_154133.json
  gap-analysis-feature-gates_4.21_to_4.22_20260325_154148.html
  gap-analysis-feature-gates_4.21_to_4.22_20260325_154148.json
  gap-analysis-full_4.21.7_to_4.22.0-ec.4_20260325_154148.html
  gap-analysis-full_4.21.7_to_4.22.0-ec.4_20260325_154148.json
```

## Examples

### Basic Usage

```bash
# Auto-detect everything
./scripts/gap-all.sh

# Single version (auto-resolve) - RECOMMENDED
./scripts/gap-all.sh --version 4.21  # GA: z-stream (stable → stable)
./scripts/gap-all.sh --version 4.22  # Pre-GA: cross-minor (stable → candidate)
./scripts/gap-all.sh --version 4.23  # Other: cross-minor (candidate → candidate)

# Explicit versions (both required)
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Dry-run mode (show versions without running analysis)
./scripts/gap-all.sh --version 4.21 --dry-run
./scripts/gap-all.sh --dry-run  # Show auto-detected versions

# With custom report location
./scripts/gap-all.sh --baseline 4.21 --target 4.22 --report-dir /tmp/reports
```

### Environment Variables

```bash
# Single version (auto-resolve baseline and target) - RECOMMENDED
OPENSHIFT_VERSION=4.21 ./scripts/gap-all.sh

# Override both (both required)
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-all.sh

# Use nightly target
BASE_VERSION=4.21.5 TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh
```

### Mixed Configuration

```bash
# --version takes precedence over environment variables
OPENSHIFT_VERSION=4.21 ./scripts/gap-all.sh --version 4.22
# Result: Uses 4.22 (from flag) → BASE=4.21.15, TARGET=4.22.0-rc.3

# Flags take precedence over environment variables
BASE_VERSION=4.21.0 TARGET_VERSION=4.22.0 ./scripts/gap-all.sh --baseline 4.21.7 --target 4.22.0-ec.3
# Result: Uses 4.21.7 and 4.22.0-ec.3 (from flags)
```

## Sippy API

Scripts query these endpoints for auto-detection:

```
https://sippy.dptools.openshift.org/api/releases
https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted
https://sippy.dptools.openshift.org/api/feature_gates?release={version}
```

## Troubleshooting

**Network errors:**
```bash
# Specify versions explicitly
./scripts/gap-all.sh --baseline 4.21.7 --target 4.22.0-ec.4
```

**Version doesn't exist:**
```bash
# Verify version
oc adm release info quay.io/openshift-release-dev/ocp-release:4.99-x86_64
```

**Report directory issues:**
```bash
# Ensure writable
mkdir -p reports
chmod 755 reports
```
