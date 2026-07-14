# Development

Guide for contributing to gap analysis scripts.

## Setup

```bash
git clone https://github.com/your-org/gap-analysis.git
cd gap-analysis
pip install -r requirements.txt
```

## Structure

```
scripts/
├── gap-aws-sts.py              # AWS STS analysis
├── gap-gcp-wif.py              # GCP WIF analysis
├── gap-ocp-gate-ack.py         # OCP admin gate acknowledgments
├── gap-versions-channels.py    # Version & channel availability analysis
├── gap-ocm-version-gate.py     # OCM version gate analysis
├── gap-feature-gates.py        # Feature gates analysis
├── gap-all.sh                  # Orchestrator
├── generate-combined-report.py # Combined report aggregator
├── templates/                  # Jinja2 templates
│   ├── aws-sts.html.j2
│   ├── gcp-wif.html.j2
│   ├── ocp-gate-ack.html.j2
│   ├── versions-channels.html.j2
│   ├── ocm-version-gate.html.j2
│   ├── feature-gates.html.j2
│   └── full-gap.html.j2
└── lib/
    ├── common.py               # Utilities
    ├── openshift_releases.py   # Version resolution
    ├── reporters.py            # Report generation
    ├── ack_validation.py       # managed-cluster-config validation
    ├── marketplace.py          # AWS/GCP marketplace checks
    ├── logging.sh              # Bash logging utilities
    └── openshift-releases.sh   # Bash version resolution
```

## Testing

```bash
# Test scripts
./scripts/gap-all.sh

# Test specific versions
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-ocp-gate-ack.py --baseline 4.21 --target 4.22

# Verbose output
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22 --verbose

# Custom reports
REPORT_DIR=/tmp/test ./scripts/gap-all.sh
```

## Customizing Templates

Edit Jinja2 templates in `scripts/templates/`:

```bash
# Edit HTML template
vim scripts/templates/aws-sts.html.j2

# Test changes
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
firefox reports/gap-analysis-aws-sts_*.html
```

Template variables available:
```python
{
    'type': 'AWS STS Policy Gap Analysis',
    'baseline': '4.21.7',
    'target': '4.22.0-ec.4',
    'timestamp': '2026-03-25T15:41:33',
    'comparison': {
        'actions': {
            'target_only': [...],
            'baseline_only': [...],
            'common': [...]
        }
    }
}
```

## Container Testing

```bash
# Build
podman build -f ci/Containerfile -t gap-analysis:dev .

# Test
podman run --rm gap-analysis:dev gap-all.sh --baseline 4.21 --target 4.22

# Mount reports
podman run --rm -v $(pwd)/reports:/gap-analysis/reports gap-analysis:dev \
  gap-all.sh
```

## Code Style

```bash
# Format (optional)
black scripts/**/*.py

# Lint (optional)
flake8 scripts/**/*.py

# Shell check
shellcheck scripts/*.sh
```

## Adding a New Script

1. Create script in `scripts/`:
```python
#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info
from openshift_releases import resolve_gap_versions
from reporters import generate_html_report, generate_json_report

# Your logic here
```

2. Create template:
```bash
scripts/templates/new-analysis.html.j2
```

3. Test:
```bash
python3 ./scripts/new-analysis.py --baseline 4.21 --target 4.22
```

## Contributing

1. Fork repository
2. Create feature branch
3. Make changes
4. Test locally
5. Submit pull request

Use conventional commits:
```
feat: add PDF report generation
fix: correct version resolution
docs: update installation guide
```

## Troubleshooting

```bash
# Debug oc extraction
oc adm release extract \
  quay.io/openshift-release-dev/ocp-release:4.22-x86_64 \
  --credentials-requests \
  --cloud=aws \
  --to=/tmp/test

# Check Python imports
python3 -c "import yaml, jinja2; print('OK')"

# Test Sippy API
curl -s "https://sippy.dptools.openshift.org/api/feature_gates?release=4.22" | jq '.'
```
