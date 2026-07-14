---
name: versions-channels-gap
description: >
  Analyze OCP version availability across OCM release channels and marketplace
  enablement (ROSA Classic, ROSA HCP, OSD GCP). Validates channel promotion
  status and marketplace availability. Exits 1 on validation FAIL for GA
  targets missing from required channels or marketplaces. Generates HTML and
  JSON reports.
compatibility:
  required_tools:
    - python3
    - rosa
---

# Versions & Channels Gap Analysis

Analyze OCP version availability across release channels and validate marketplace enablement.

## When to Use

- Checking if a target version is available in the expected release channel
- Verifying marketplace availability (ROSA Classic, ROSA HCP, OSD GCP)
- Pre-upgrade channel readiness assessment
- Validating GA readiness across channels and marketplaces

## What This Analyzes

1. **Channel Availability** - Which OCM channels (candidate/fast/stable/eus for GA, candidate-only for pre-GA) contain the baseline and target versions
2. **Marketplace Availability** - ROSA Classic (OCM API), ROSA HCP (ROSA CLI), OSD GCP (OCM API, 4.x only — skipped for 5.x)

## Workflow

### Step 1: Run the Analysis

```bash
# Single version (recommended)
python3 ./scripts/gap-versions-channels.py --version 4.22

# Explicit versions
python3 ./scripts/gap-versions-channels.py --baseline 4.21 --target 4.22

# Auto-detect
python3 ./scripts/gap-versions-channels.py

# Dry-run (check versions only)
python3 ./scripts/gap-versions-channels.py --version 4.22 --dry-run
```

### Step 2: Interpret Results

The script queries OCM for each channel for both baseline and target minor versions, then checks marketplace availability.

**Key findings to look for:**
- Baseline not in stable channel (unusual for GA versions)
- Target only in candidate channel (normal for pre-GA)
- Target missing from ROSA HCP or ROSA Classic marketplace (FAIL for GA)
- OSD GCP skipped for 5.x targets (AWS/STS-only)

### Step 3: Review Reports

```bash
# View HTML report
firefox reports/gap-analysis-versions-channels_*.html

# Parse JSON report
jq '.summary' reports/gap-analysis-versions-channels_*.json
jq '.marketplace' reports/gap-analysis-versions-channels_*.json
```

## Output

```
[INFO] Starting Version & Channel Gap Analysis
[INFO] Baseline version: 4.21.18 (minor: 4.21)
[INFO] Target version: 4.22.0-rc.5 (minor: 4.22)

CHECK #6: Versions & Channels Analysis

┌─────────────────────────────────────────────────┐
│ Baseline: 4.21.18                               │
├─────────────────────────────────────────────────┤
│  Channels:      stable-4.21, fast-4.21, ...     │
│  ROSA Classic:  ✓ available                     │
│  ROSA HCP:      ✓ available (stable, fast, ...) │
│  OSD GCP:       ✓ available                     │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ Target: 4.22.0-rc.5                             │
├─────────────────────────────────────────────────┤
│  Channels:      candidate-4.22                  │
│  ROSA Classic:  ✗ not available                 │
│  ROSA HCP:      ✓ available (candidate)         │
│  OSD GCP:       ✗ not available                 │
└─────────────────────────────────────────────────┘
```

Exit code: `0` on PASS, `1` on validation FAIL (GA targets missing from required channels/marketplaces) or execution error.

## Data Sources

- **OCM CLI**: `ocm list versions` (channel availability, ROSA Classic/OSD GCP marketplace) — requires `ocm login --token=<token>`, graceful fallback if absent
- **ROSA CLI**: `rosa list versions --hosted-cp` (ROSA HCP availability)
- **Sippy API**: `https://sippy.dptools.openshift.org/api/releases` (GA version detection)

## Example Interaction

**User**: "Check if 4.22 versions are available in release channels"

**Response**:
```bash
python3 ./scripts/gap-versions-channels.py --version 4.22 --verbose
```

**User**: "Is 5.0 available on ROSA HCP?"

**Response**:
```bash
python3 ./scripts/gap-versions-channels.py --version 5.0
# Check marketplace section — OSD GCP will be skipped (5.x is AWS/STS-only)
```
