---
name: versions-channels-gap
description: >
  Analyze OCP version availability across Cincinnati release channels.
  Validates channel promotion status, upgrade paths, and cross-source consistency
  between Sippy, accepted streams, and Cincinnati. Always exits 0 on successful
  execution (informational only). Generates HTML and JSON reports.
compatibility:
  required_tools:
    - python3
---

# Versions & Channels Gap Analysis

Analyze OCP version availability across release channels and validate upgrade path existence.

## When to Use

- Checking if a target version is available in the expected release channel
- Verifying upgrade paths exist between baseline and target versions
- Identifying versions accepted in CI but not yet promoted to channels
- Cross-checking version data across Sippy, accepted streams, and Cincinnati
- Pre-upgrade channel readiness assessment

## What This Analyzes

1. **Channel Availability** - Which Cincinnati channels (candidate/fast/stable) contain the baseline and target versions
2. **Accepted vs Channels** - Versions that passed CI acceptance but haven't been promoted to any channel yet
3. **Upgrade Paths** - Whether valid upgrade edges exist in Cincinnati from baseline to target
4. **Cross-Source Consistency** - GA dates from Sippy vs accepted streams data

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

The script queries Cincinnati for each channel (candidate/fast/stable) for both baseline and target minor versions, then compares with accepted streams data.

**Key findings to look for:**
- Baseline not in stable channel (unusual for GA versions)
- Target only in candidate channel (normal for pre-GA)
- No direct upgrade path between specific versions
- Versions accepted in CI but not yet in any channel (promotion lag)

### Step 3: Review Reports

```bash
# View HTML report
firefox reports/gap-analysis-versions-channels_*.html

# Parse JSON report
jq '.summary' reports/gap-analysis-versions-channels_*.json
jq '.upgrade_paths.sample_paths' reports/gap-analysis-versions-channels_*.json
```

## Output

```
[INFO] Starting Version & Channel Gap Analysis
[INFO] Baseline version: 4.21.18 (minor: 4.21)
[INFO] Target version: 4.22.0-rc.5 (minor: 4.22)

CHECK #6: Versions & Channels Analysis

Baseline 4.21.18 channel status:
  ✓ candidate-4.21

Target 4.22.0-rc.5 channel status:
  ✓ candidate-4.22

Channel availability for 4.22:
  ✓ candidate-4.22: 12 version(s), latest: 4.22.0-rc.5
  ✗ fast-4.22: not available
  ✗ stable-4.22: not available

Upgrade paths (candidate-4.22):
  Total 4.21 → 4.22 paths: 73
  ✓ Direct path exists: 4.21.18 → 4.22.0-rc.5

✅ PASSED - Version & Channel analysis complete (informational)
```

Exit code: `0` (always, informational only)

## Data Sources

- **Cincinnati API**: `https://api.openshift.com/api/upgrades_info/v1/graph?channel={channel}&arch=amd64`
- **Accepted Streams**: `https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted`
- **Sippy API**: `https://sippy.dptools.openshift.org/api/releases`

All APIs are public and require no authentication.

## Example Interaction

**User**: "Check if 4.22 versions are available in release channels"

**Response**:
```bash
python3 ./scripts/gap-versions-channels.py --version 4.22 --verbose
```

**User**: "Is there an upgrade path from 4.21.18 to 4.22.0-rc.5?"

**Response**:
```bash
python3 ./scripts/gap-versions-channels.py --baseline 4.21.18 --target 4.22.0-rc.5
# Check: "Direct path exists: 4.21.18 → 4.22.0-rc.5"
```
