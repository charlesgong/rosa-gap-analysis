# Gap Analysis Reports

All gap analysis scripts automatically generate reports in multiple formats when executed.

## Report Formats

Each script execution generates two report files:

1. **HTML (.html)** - Rich formatted report for viewing in browsers
2. **JSON (.json)** - Machine-readable data for automation

## Report Naming Convention

Reports are automatically named with timestamps:

```
gap-analysis-{type}_{baseline}_to_{target}_{timestamp}.{format}
```

**Examples:**
```
gap-analysis-aws-sts_4.20_to_4.21_20260325_153237.html
gap-analysis-aws-sts_4.20_to_4.21_20260325_153237.json

gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html
gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.json

gap-analysis-full_4.20_to_4.21_20260325_153500.html
gap-analysis-full_4.20_to_4.21_20260325_153500.json
```

## Individual Script Reports

All reports follow the global 8-check validation system. See [Validation Checks](validation-checks.md) for details.

### AWS STS Gap Analysis (Checks 1-2)

```bash
python3 scripts/gap-aws-sts.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-aws-sts_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-aws-sts_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 1:** AWS STS Resources validation results
- **Check 2:** AWS STS Admin Ack validation results
- Added IAM actions/permissions
- Removed IAM actions/permissions
- **Changed Files**: Lists specific credential request files that changed with per-file diffs
- Total changes summary
- Validation results for [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- Timestamp and version information

### GCP WIF Gap Analysis (Checks 3-4)

```bash
python3 scripts/gap-gcp-wif.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-gcp-wif_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-gcp-wif_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 3:** GCP WIF Resources validation results
- **Check 4:** GCP WIF Admin Ack validation results
- Added GCP IAM permissions
- Removed GCP IAM permissions
- **Changed Files**: Lists specific credential request files that changed with per-file diffs
- Total changes summary
- Validation results for [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- Timestamp and version information

### OCP Admin Gate Acknowledgment Analysis (Check 5)

```bash
python3 scripts/gap-ocp-gate-ack.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-ocp-gate-ack_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-ocp-gate-ack_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 5:** OCP Admin Gates validation results
- Admin gates requiring acknowledgment
- Acknowledged gates
- Unacknowledged gates
- config.yaml validation results
- Timestamp and version information

### Versions & Channels Gap Analysis (Check 6)

```bash
python3 scripts/gap-versions-channels.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-versions-channels_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-versions-channels_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 6:** Versions & Channels validation results
- Channel availability across OCM channels (candidate/fast/stable/eus)
- Marketplace availability (ROSA Classic, ROSA HCP, OSD GCP)
- Timestamp and version information

### OCM Version Gate Gap Analysis (Check 7)

```bash
python3 scripts/gap-ocm-version-gate.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-ocm-version-gate_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-ocm-version-gate_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 7:** OCM Version Gates validation results
- Gate configurations for baseline and target versions
- New, common, and removed gates comparison
- Configuration metadata validation
- Timestamp and version information

### Feature Gate Gap Analysis (Check 8 - Informational)

```bash
python3 scripts/gap-feature-gates.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-feature-gates_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-feature-gates_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 8:** Feature Gates analysis (informational only, always PASS)
- New feature gates
- Removed feature gates
- Newly enabled by default
- Removed from default
- Total changes summary
- Timestamp and version information

## Combined Report (gap-all.sh) - All 8 Checks

When running the full gap analysis orchestrator:

```bash
bash scripts/gap-all.sh --baseline 4.20 --target 4.21
```

**Generates individual reports for each analysis PLUS a combined report:**

- `gap-analysis-full_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-full_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Combined Report Contents (All 8 Checks):**
- **Check 1:** AWS STS Resources validation
- **Check 2:** AWS STS Admin Ack validation
- **Check 3:** GCP WIF Resources validation
- **Check 4:** GCP WIF Admin Ack validation
- **Check 5:** OCP Admin Gates validation
- **Check 6:** Versions & Channels validation
- **Check 7:** OCM Version Gates validation
- **Check 8:** Feature Gates analysis (informational)
- Aggregate statistics
- Timestamp and version information

**Execution Order:**
1. AWS STS (Checks 1-2)
2. GCP WIF (Checks 3-4)
3. OCP Admin Gates (Check 5)
4. Versions & Channels (Check 6)
5. OCM Version Gates (Check 7)
6. Feature Gates (Check 8) - Always executed last

## Viewing Reports

### HTML Reports (.html)

Open in any web browser:
```bash
firefox gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html
```

Or:
```bash
open gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html  # macOS
xdg-open gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html  # Linux
```

**Features:**
- Professional styling with tables
- Color-coded changes (green for added, red for removed, orange for changed)
- Responsive design
- Print-friendly layout

### JSON Reports (.json)

Process programmatically:
```bash
jq '.' gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.json
```

Parse in scripts:
```python
import json
with open('gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.json') as f:
    data = json.load(f)
    print(f"Total changes: {data['summary']['total_changes']}")
```

## Report Location

Reports are generated in `./reports/` by default.

To specify a different location:
```bash
python3 /path/to/scripts/gap-aws-sts.py --baseline 4.20 --target 4.21 --report-dir /path/to/reports
# Or via environment variable:
REPORT_DIR=/path/to/reports ./scripts/gap-all.sh --baseline 4.20 --target 4.21
```

## CI/CD Integration

### Archiving Reports

```yaml
# In ci-operator config
- as: gap-analysis-all
  commands: |
    gap-all.sh --baseline 4.20 --target 4.21
  container:
    from: src
  artifacts:
    - name: gap-analysis-reports
      path: gap-analysis-*.html
    - name: gap-analysis-reports
      path: gap-analysis-*.json
```

### Parsing JSON for Automation

```bash
#!/bin/bash
# Check if any differences were found
REPORT=$(ls -t gap-analysis-full_*.json | head -1)

AWS_CHANGES=$(jq '.aws_sts.summary.total_changes' "$REPORT")
GCP_CHANGES=$(jq '.gcp_wif.summary.total_changes' "$REPORT")
FG_CHANGES=$(jq '.feature_gates.summary.total_changes' "$REPORT")

if [ $AWS_CHANGES -gt 0 ] || [ $GCP_CHANGES -gt 0 ] || [ $FG_CHANGES -gt 0 ]; then
    echo "Changes detected - review required"
    # Send notification, create Jira ticket, etc.
fi
```

## Report Customization

The report generation is handled by `scripts/lib/reporters.py` using Jinja2 templates in `scripts/templates/`. To customize:

1. Edit HTML templates in `scripts/templates/*.html.j2`
2. Modify CSS styles within the HTML templates
3. Add new report formats (PDF, Excel, etc.) by extending `reporters.py`

See `scripts/lib/reporters.py` and `scripts/templates/` for implementation details.

## Troubleshooting

### Reports Not Generated

Check that the script completed successfully:
```bash
echo $?  # Should be 0
```

### Missing Reports

Verify you have write permissions in the current directory:
```bash
pwd
ls -la
```

### Large Reports

For versions with many changes, reports can be large. Use JSON for programmatic processing:
```bash
jq '.summary' gap-analysis-*.json  # Get summary only
```

## Future Enhancements

Planned features:
- PDF report generation
- Excel spreadsheet export
- Email notifications with attached reports
- Slack/Teams integration for posting reports
- Chart/graph generation for trends over time
