# Getting Started

Quick guide to installing and running gap analysis.

## Installation

### Prerequisites

```bash
# Required
pip install -r requirements.txt  # PyYAML, Jinja2

# Download oc CLI
curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz | tar xz -C /usr/local/bin
```

Verify installation:
```bash
oc version --client
python3 --version
python3 -c "import yaml, jinja2; print('Dependencies OK')"
```

## Basic Usage

### Auto-Detect Versions (Recommended)

```bash
# Run all analyses (all 8 checks)
./scripts/gap-all.sh

# Individual analysis
python3 ./scripts/gap-aws-sts.py
python3 ./scripts/gap-gcp-wif.py
python3 ./scripts/gap-ocp-gate-ack.py
python3 ./scripts/gap-versions-channels.py
python3 ./scripts/gap-ocm-version-gate.py
python3 ./scripts/gap-feature-gates.py
```

**Auto-detection:** Compares latest stable → latest candidate

### Specify Versions

```bash
# Full analysis
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Individual scripts (examples)
python3 ./scripts/gap-aws-sts.py --baseline 4.21.6 --target 4.22.0-ec.3
python3 ./scripts/gap-gcp-wif.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-ocp-gate-ack.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-versions-channels.py --version 4.22
python3 ./scripts/gap-ocm-version-gate.py --version 4.22
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22
```

### Environment Variables

```bash
# Set versions
BASE_VERSION=4.21 TARGET_VERSION=4.22 ./scripts/gap-all.sh

# Use nightly target
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh

# Custom report directory
REPORT_DIR=/tmp/reports ./scripts/gap-all.sh
```

## Viewing Reports

Reports are generated in `./reports/` (or `$REPORT_DIR`):

```bash
# Open HTML in browser
firefox reports/gap-analysis-full_*.html

# Parse JSON
jq '.aws_sts.comparison' reports/gap-analysis-full_*.json
```

### Report Formats

| Format | Extension | Use Case |
|--------|-----------|----------|
| HTML | `.html` | Browser viewing, presentations |
| JSON | `.json` | Programmatic analysis, CI/CD |

## Common Scenarios

### Pre-Upgrade Assessment

```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22
firefox reports/gap-analysis-full_*.html
```

### CI/CD Integration

```bash
# Run analysis (always exits 0 on success)
./scripts/gap-all.sh || exit 1

# Check for differences by parsing output
if ./scripts/gap-all.sh 2>&1 | grep -q "differences detected"; then
  echo "Changes detected - review reports/"
fi
```

### Multiple Version Comparisons

```bash
for target in 4.21 4.22 4.23; do
  ./scripts/gap-all.sh --baseline 4.20 --target $target
done
```

## Understanding Output

### Exit Codes

- **0** - Successful execution with all validation checks passing
- **1** - Execution error (missing tools, network errors) OR validation checks 1-7 failed

**Note:** `gap-feature-gates.py` (check 8) is informational only and always exits 0 on success.

### Console Output

```
[INFO] OpenShift Gap Analysis Suite
[INFO] Baseline: 4.21.7
[INFO] Target: 4.22.0-ec.4
[INFO] Running AWS STS Policy Gap Analysis...
[INFO] Policy differences detected: 3 added, 1 removed
[SUCCESS] Reports generated: ./reports/
```

## Next Steps

- [Configuration](configuration.md) - Detailed configuration options
- [Development](development.md) - Contributing and testing
