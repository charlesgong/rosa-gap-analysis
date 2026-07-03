#!/usr/bin/env python3
"""Version and Channel Gap Analysis - Validate OCP version availability across release channels."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, log_warning
from openshift_releases import resolve_openshift_version, extract_minor_version
from reporters import generate_html_report, generate_json_report, generate_status_report


CINCINNATI_API = "https://api.openshift.com/api/upgrades_info/v1/graph"
ACCEPTED_STREAMS_API = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted"
SIPPY_API = "https://sippy.dptools.openshift.org/api/releases"

CHANNELS = ['candidate', 'fast', 'stable']


def fetch_cincinnati_channel(channel, arch="amd64"):
    """Fetch version graph from Cincinnati for a specific channel.

    Returns (data, error) tuple. On failure, data is the empty fallback and
    error is a descriptive string so callers can surface API issues.
    """
    try:
        url = f"{CINCINNATI_API}?channel={channel}&arch={arch}"
        req = Request(url, headers={
            'User-Agent': 'gap-analysis-script',
            'Accept': 'application/json'
        })
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read()), None
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        log_warning(f"Failed to fetch Cincinnati channel {channel}: {e}")
        return {'nodes': [], 'edges': []}, f"Cincinnati channel {channel}: {e}"


def fetch_accepted_streams():
    """Fetch accepted release streams."""
    try:
        req = Request(ACCEPTED_STREAMS_API, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read())
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        log_warning(f"Failed to fetch accepted streams: {e}")
        return {}


def fetch_sippy_releases():
    """Fetch release info from Sippy API."""
    try:
        req = Request(SIPPY_API, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read())
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        log_warning(f"Failed to fetch Sippy releases: {e}")
        return {}


def get_versions_in_channel(channel_data, minor_version):
    """Extract versions matching a minor version from Cincinnati channel data."""
    versions = []
    for node in channel_data.get('nodes', []):
        version = node.get('version', '')
        if version.startswith(f"{minor_version}."):
            versions.append(version)
    return sorted(versions, key=lambda v: v)


def analyze_channel_availability(baseline_minor, target_minor, baseline_full, target_full):
    """Analyze which channels contain baseline and target versions."""
    result = {
        'baseline': {
            'version': baseline_full,
            'minor': baseline_minor,
            'channels': {}
        },
        'target': {
            'version': target_full,
            'minor': target_minor,
            'channels': {}
        },
        'baseline_version_channels': [],
        'target_version_channels': [],
        'baseline_in_stable': False,
        'target_highest_channel': 'none',
        'api_errors': []
    }

    minors_to_check = {baseline_minor, target_minor}

    for minor in minors_to_check:
        for channel_type in CHANNELS:
            channel_name = f"{channel_type}-{minor}"
            log_info(f"Querying Cincinnati channel: {channel_name}")
            channel_data, err = fetch_cincinnati_channel(channel_name)
            if err:
                result['api_errors'].append(err)

            versions = get_versions_in_channel(channel_data, minor)
            channel_info = {
                'available': len(versions) > 0,
                'version_count': len(versions),
                'versions': versions,
                'latest': versions[-1] if versions else None
            }

            if minor == baseline_minor:
                result['baseline']['channels'][channel_type] = channel_info
                if baseline_full in versions:
                    result['baseline_version_channels'].append(channel_type)
            if minor == target_minor:
                result['target']['channels'][channel_type] = channel_info
                if target_full in versions:
                    result['target_version_channels'].append(channel_type)

    result['baseline_in_stable'] = 'stable' in result['baseline_version_channels']

    for ch in ['stable', 'fast', 'candidate']:
        if ch in result['target_version_channels']:
            result['target_highest_channel'] = ch
            break

    return result


def analyze_accepted_vs_channels(target_minor):
    """Compare accepted streams with Cincinnati channel data."""
    result = {
        'accepted_versions': [],
        'channel_versions': [],
        'accepted_only': [],
        'channel_only': [],
        'consistent': [],
        'accepted_count': 0,
        'channel_count': 0,
        'api_errors': []
    }

    streams = fetch_accepted_streams()
    if not streams:
        return result

    # Collect accepted versions for this minor version from all streams
    accepted = set()
    for stream_name, versions in streams.items():
        if isinstance(versions, list):
            for v in versions:
                if v.startswith(f"{target_minor}."):
                    accepted.add(v)

    # Collect versions from Cincinnati channels
    channel_versions = set()
    for channel_type in CHANNELS:
        channel_name = f"{channel_type}-{target_minor}"
        channel_data, err = fetch_cincinnati_channel(channel_name)
        if err:
            result['api_errors'].append(err)
        for node in channel_data.get('nodes', []):
            version = node.get('version', '')
            if version.startswith(f"{target_minor}."):
                channel_versions.add(version)

    result['accepted_versions'] = sorted(accepted)
    result['channel_versions'] = sorted(channel_versions)
    result['accepted_only'] = sorted(accepted - channel_versions)
    result['channel_only'] = sorted(channel_versions - accepted)
    result['consistent'] = sorted(accepted & channel_versions)
    result['accepted_count'] = len(accepted)
    result['channel_count'] = len(channel_versions)

    return result


def analyze_upgrade_paths(baseline_minor, target_minor, baseline_full, target_full):
    """Analyze upgrade paths between baseline and target versions."""
    result = {
        'total_paths': 0,
        'direct_path_exists': False,
        'paths_from_baseline': 0,
        'paths_to_target': 0,
        'sample_paths': [],
        'channel_queried': None,
        'api_errors': []
    }

    is_z_stream = (baseline_minor == target_minor)

    if is_z_stream:
        channel_name = f"stable-{target_minor}"
    else:
        channel_name = f"candidate-{target_minor}"

    result['channel_queried'] = channel_name
    log_info(f"Querying upgrade paths from Cincinnati channel: {channel_name}")
    channel_data, err = fetch_cincinnati_channel(channel_name)
    if err:
        result['api_errors'].append(err)

    nodes = channel_data.get('nodes', [])
    edges = channel_data.get('edges', [])

    if not nodes or not edges:
        return result

    version_idx = {i: n['version'] for i, n in enumerate(nodes)}

    cross_paths = []
    for src, dst in edges:
        src_v = version_idx.get(src, '')
        dst_v = version_idx.get(dst, '')

        if src_v.startswith(f"{baseline_minor}.") and dst_v.startswith(f"{target_minor}."):
            cross_paths.append({'from': src_v, 'to': dst_v})

    result['total_paths'] = len(cross_paths)
    result['sample_paths'] = cross_paths[:10]

    result['direct_path_exists'] = any(
        p['from'] == baseline_full and p['to'] == target_full
        for p in cross_paths
    )

    result['paths_from_baseline'] = sum(
        1 for p in cross_paths if p['from'] == baseline_full
    )
    result['paths_to_target'] = sum(
        1 for p in cross_paths if p['to'] == target_full
    )

    return result


def analyze_cross_source_consistency(baseline_minor, target_minor):
    """Check consistency across Sippy, accepted streams, and Cincinnati."""
    result = {
        'baseline_ga_date': None,
        'target_ga_date': None,
        'baseline_is_ga': False,
        'target_is_ga': False,
        'sippy_releases': [],
        'observations': []
    }

    sippy = fetch_sippy_releases()
    if not sippy:
        result['observations'].append("Sippy API unavailable — skipped GA date check")
        return result

    ga_dates = sippy.get('ga_dates', {})
    releases = sippy.get('releases', [])

    result['sippy_releases'] = [r for r in releases if not r.endswith('-okd')]

    if baseline_minor in ga_dates:
        result['baseline_ga_date'] = ga_dates[baseline_minor]
        result['baseline_is_ga'] = True
    if target_minor in ga_dates:
        result['target_ga_date'] = ga_dates[target_minor]
        result['target_is_ga'] = True

    if result['baseline_is_ga'] and not result['target_is_ga']:
        result['observations'].append(
            f"Baseline {baseline_minor} is GA (since {result['baseline_ga_date'][:10]}), "
            f"target {target_minor} is pre-GA"
        )
    elif result['baseline_is_ga'] and result['target_is_ga']:
        result['observations'].append(
            f"Both versions are GA: {baseline_minor} ({result['baseline_ga_date'][:10]}), "
            f"{target_minor} ({result['target_ga_date'][:10]})"
        )
    elif not result['baseline_is_ga']:
        result['observations'].append(
            f"Baseline {baseline_minor} is pre-GA — upgrade path may be limited"
        )

    if target_minor not in [r for r in releases if not r.endswith('-okd')]:
        result['observations'].append(
            f"Target {target_minor} not found in Sippy releases list"
        )

    return result


def is_ocm_authenticated():
    """Check if ocm CLI is available and authenticated."""
    try:
        result = subprocess.run(
            ['ocm', 'whoami'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def fetch_ocm_versions(minor_version, channel_group='stable'):
    """Fetch versions from OCM API for a minor version and channel group."""
    if not re.match(r'^\d+\.\d+$', minor_version):
        log_warning(f"Invalid minor version format: {minor_version}")
        return []
    if not re.match(r'^[a-z]+$', channel_group):
        log_warning(f"Invalid channel group format: {channel_group}")
        return []
    try:
        search = f"raw_id like '{minor_version}%' and channel_group='{channel_group}'"
        result = subprocess.run(
            ['ocm', 'get', '/api/clusters_mgmt/v1/versions',
             '--parameter', f'search={search}',
             '--parameter', 'size=100',
             '--parameter', 'order=raw_id desc'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return data.get('items', [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log_warning(f"Failed to fetch OCM versions for {minor_version} ({channel_group}): {e}")
        return []


def analyze_marketplace_availability(baseline_minor, target_minor, baseline_full, target_full):
    """Check version availability on AWS (ROSA) and GCP marketplaces via OCM API."""
    result = {
        'available': False,
        'aws': {
            'baseline': {'version': baseline_full, 'rosa_enabled': None, 'channel_group': None},
            'target': {'version': target_full, 'rosa_enabled': None, 'channel_group': None},
            'target_minor_versions': []
        },
        'gcp': {
            'baseline': {'version': baseline_full, 'gcp_marketplace_enabled': None, 'channel_group': None},
            'target': {'version': target_full, 'gcp_marketplace_enabled': None, 'channel_group': None},
            'target_minor_versions': []
        }
    }

    if not is_ocm_authenticated():
        log_warning("OCM not authenticated — skipping marketplace validation")
        log_warning("  Run 'ocm login --token=<token>' to enable marketplace checks")
        return result

    result['available'] = True
    log_info("OCM authenticated — checking marketplace availability")

    channel_groups = ['stable', 'candidate', 'fast', 'nightly']

    for channel_group in channel_groups:
        versions = fetch_ocm_versions(target_minor, channel_group)
        for v in versions:
            raw_id = v.get('id', '').replace('openshift-v', '')
            version_info = {
                'version': raw_id,
                'channel_group': channel_group,
                'rosa_enabled': v.get('rosa_enabled', False),
                'gcp_marketplace_enabled': v.get('gcp_marketplace_enabled', False),
                'hosted_control_plane_enabled': v.get('hosted_control_plane_enabled', False),
                'enabled': v.get('enabled', False)
            }

            result['aws']['target_minor_versions'].append(version_info)
            result['gcp']['target_minor_versions'].append(version_info)

            if raw_id == target_full or raw_id == f"{target_full}-{channel_group}":
                result['aws']['target']['rosa_enabled'] = v.get('rosa_enabled', False)
                result['aws']['target']['channel_group'] = channel_group
                result['gcp']['target']['gcp_marketplace_enabled'] = v.get('gcp_marketplace_enabled', False)
                result['gcp']['target']['channel_group'] = channel_group

    for channel_group in channel_groups:
        versions = fetch_ocm_versions(baseline_minor, channel_group)
        for v in versions:
            raw_id = v.get('id', '').replace('openshift-v', '')
            if raw_id == baseline_full or raw_id == f"{baseline_full}-{channel_group}":
                result['aws']['baseline']['rosa_enabled'] = v.get('rosa_enabled', False)
                result['aws']['baseline']['channel_group'] = channel_group
                result['gcp']['baseline']['gcp_marketplace_enabled'] = v.get('gcp_marketplace_enabled', False)
                result['gcp']['baseline']['channel_group'] = channel_group
                break
        if result['aws']['baseline']['rosa_enabled'] is not None:
            break

    return result


def print_marketplace_analysis(marketplace_analysis, baseline_full, target_full):
    """Print marketplace analysis results."""
    if not marketplace_analysis['available']:
        return

    log_info(f"\nMarketplace availability:")

    # AWS (ROSA)
    aws_baseline = marketplace_analysis['aws']['baseline']
    aws_target = marketplace_analysis['aws']['target']

    if aws_baseline['rosa_enabled'] is not None:
        if aws_baseline['rosa_enabled']:
            log_info(f"  AWS: ✓ Baseline {baseline_full} available (ROSA enabled, {aws_baseline['channel_group']})")
        else:
            log_warning(f"  AWS: ✗ Baseline {baseline_full} NOT available on AWS marketplace")
    else:
        log_info(f"  AWS: - Baseline {baseline_full} not found in OCM")

    if aws_target['rosa_enabled'] is not None:
        if aws_target['rosa_enabled']:
            log_info(f"  AWS: ✓ Target {target_full} available (ROSA enabled, {aws_target['channel_group']})")
        else:
            log_warning(f"  AWS: ✗ Target {target_full} NOT available on AWS marketplace")
    else:
        log_info(f"  AWS: - Target {target_full} not found in OCM")

    # GCP
    gcp_baseline = marketplace_analysis['gcp']['baseline']
    gcp_target = marketplace_analysis['gcp']['target']

    if gcp_baseline['gcp_marketplace_enabled'] is not None:
        if gcp_baseline['gcp_marketplace_enabled']:
            log_info(f"  GCP: ✓ Baseline {baseline_full} available (GCP marketplace, {gcp_baseline['channel_group']})")
        else:
            log_warning(f"  GCP: ✗ Baseline {baseline_full} NOT available on GCP marketplace")
    else:
        log_info(f"  GCP: - Baseline {baseline_full} not found in OCM")

    if gcp_target['gcp_marketplace_enabled'] is not None:
        if gcp_target['gcp_marketplace_enabled']:
            log_info(f"  GCP: ✓ Target {target_full} available (GCP marketplace, {gcp_target['channel_group']})")
        else:
            log_warning(f"  GCP: ✗ Target {target_full} NOT available on GCP marketplace")
    else:
        log_info(f"  GCP: - Target {target_full} not found in OCM")

    # Summary of target minor versions on marketplaces
    aws_enabled = [v for v in marketplace_analysis['aws']['target_minor_versions'] if v['rosa_enabled']]
    gcp_enabled = [v for v in marketplace_analysis['gcp']['target_minor_versions'] if v['gcp_marketplace_enabled']]
    total_versions = len(marketplace_analysis['aws']['target_minor_versions'])

    if total_versions > 0:
        log_info(f"\n  Target minor version marketplace summary:")
        log_info(f"    AWS (ROSA enabled): {len(aws_enabled)}/{total_versions} versions")
        log_info(f"    GCP (marketplace enabled): {len(gcp_enabled)}/{total_versions} versions")


def print_analysis(channel_analysis, accepted_analysis, upgrade_analysis, consistency_analysis,
                   baseline_full, target_full, verbose=False, marketplace_analysis=None):
    """Print analysis results."""
    baseline_minor = channel_analysis['baseline']['minor']
    target_minor = channel_analysis['target']['minor']

    log_info("\nCHECK #6: Versions & Channels Analysis")

    # Channel availability
    log_info(f"\nBaseline {baseline_full} channel status:")
    if channel_analysis['baseline_version_channels']:
        for ch in channel_analysis['baseline_version_channels']:
            log_info(f"  ✓ {ch}-{baseline_minor}")
    else:
        log_warning(f"  ✗ Not found in any {baseline_minor} channel")

    log_info(f"\nTarget {target_full} channel status:")
    if channel_analysis['target_version_channels']:
        for ch in channel_analysis['target_version_channels']:
            log_info(f"  ✓ {ch}-{target_minor}")
    else:
        log_warning(f"  ✗ Not found in any {target_minor} channel")

    log_info(f"\nChannel availability for {target_minor}:")
    for ch_type in CHANNELS:
        ch_info = channel_analysis['target']['channels'].get(ch_type, {})
        if ch_info.get('available'):
            log_info(f"  ✓ {ch_type}-{target_minor}: {ch_info['version_count']} version(s), latest: {ch_info['latest']}")
        else:
            log_info(f"  ✗ {ch_type}-{target_minor}: not available")

    # Accepted vs channels
    if accepted_analysis['accepted_only']:
        log_info(f"\nAccepted in CI but not in any channel ({len(accepted_analysis['accepted_only'])}):")
        for v in accepted_analysis['accepted_only'][:5]:
            log_info(f"  • {v}")
        if len(accepted_analysis['accepted_only']) > 5:
            log_info(f"  ... and {len(accepted_analysis['accepted_only']) - 5} more")

    # Upgrade paths
    log_info(f"\nUpgrade paths ({upgrade_analysis['channel_queried']}):")
    log_info(f"  Total {baseline_minor} → {target_minor} paths: {upgrade_analysis['total_paths']}")
    if upgrade_analysis['direct_path_exists']:
        log_success(f"  ✓ Direct path exists: {baseline_full} → {target_full}")
    else:
        log_warning(f"  ✗ No direct path: {baseline_full} → {target_full}")
    log_info(f"  Paths from {baseline_full}: {upgrade_analysis['paths_from_baseline']}")
    log_info(f"  Paths to {target_full}: {upgrade_analysis['paths_to_target']}")

    if verbose and upgrade_analysis['sample_paths']:
        log_info(f"\n  Sample upgrade paths:")
        for p in upgrade_analysis['sample_paths']:
            log_info(f"    {p['from']} → {p['to']}")

    # Cross-source consistency
    if consistency_analysis['observations']:
        log_info(f"\nCross-source observations:")
        for obs in consistency_analysis['observations']:
            log_info(f"  ℹ️  {obs}")

    # Marketplace availability
    if marketplace_analysis:
        print_marketplace_analysis(marketplace_analysis, baseline_full, target_full)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze OCP version availability across release channels.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect versions (stable → candidate)
  %(prog)s

  # Single version (auto-resolves baseline and target)
  %(prog)s --version 4.22

  # Explicit versions
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

Exit Codes:
  0 - Successful execution (regardless of findings)
  1 - Execution failure (e.g., network errors, invalid versions)
        """
    )

    parser.add_argument('--version', help='Single version to analyze (auto-resolves baseline and target)')
    parser.add_argument('--baseline', help='Baseline version (requires --target)')
    parser.add_argument('--target', help='Target version (requires --baseline)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--report-dir',
                       default=os.environ.get('REPORT_DIR', 'reports'),
                       help='Directory to store reports (default: reports/, env: REPORT_DIR)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show versions that would be used and exit (no analysis performed)')

    args = parser.parse_args()

    # Resolve versions using shared logic
    openshift_version = args.version or os.environ.get('OPENSHIFT_VERSION')

    if openshift_version:
        log_info(f"Using single version: {openshift_version}")
        baseline_full, target_full = resolve_openshift_version(openshift_version)
        if not baseline_full or not target_full:
            log_error(f"Failed to resolve versions from: {openshift_version}")
            sys.exit(1)
    elif args.baseline and args.target:
        baseline_full = args.baseline
        target_full = args.target
    else:
        from openshift_releases import resolve_baseline_version, resolve_target_version
        baseline_full = args.baseline or resolve_baseline_version()
        target_full = args.target or resolve_target_version()

    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)
    is_z_stream = (baseline_minor == target_minor)

    # Main execution
    log_info("Starting Version & Channel Gap Analysis")
    log_info("=========================================")
    log_info(f"Baseline version: {baseline_full} (minor: {baseline_minor})")
    log_info(f"Target version: {target_full} (minor: {target_minor})")
    if is_z_stream:
        log_info(f"Comparison type: Z-stream (same minor version)")
    else:
        log_info(f"Comparison type: Cross-minor ({baseline_minor} → {target_minor})")
    log_info("=========================================")

    if args.dry_run:
        log_info("")
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    # Run analyses
    log_info("\nAnalyzing channel availability...")
    channel_analysis = analyze_channel_availability(
        baseline_minor, target_minor, baseline_full, target_full
    )

    log_info("\nComparing accepted streams with channel data...")
    accepted_analysis = analyze_accepted_vs_channels(target_minor)

    log_info("\nAnalyzing upgrade paths...")
    upgrade_analysis = analyze_upgrade_paths(
        baseline_minor, target_minor, baseline_full, target_full
    )

    log_info("\nChecking cross-source consistency...")
    consistency_analysis = analyze_cross_source_consistency(baseline_minor, target_minor)

    log_info("\nChecking marketplace availability...")
    marketplace_analysis = analyze_marketplace_availability(
        baseline_minor, target_minor, baseline_full, target_full
    )

    # Print results
    print_analysis(
        channel_analysis, accepted_analysis, upgrade_analysis, consistency_analysis,
        baseline_full, target_full, args.verbose, marketplace_analysis
    )

    # Generate reports
    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Collect API errors from all analyses
    api_errors = []
    for analysis in [channel_analysis, accepted_analysis, upgrade_analysis]:
        api_errors.extend(analysis.get('api_errors', []))

    if api_errors:
        log_warning(f"{len(api_errors)} Cincinnati API call(s) failed — results may be incomplete:")
        for err in api_errors:
            log_warning(f"  - {err}")

    validation_result = 'PASS'

    report_data = {
        'type': 'Version Channel Gap Analysis',
        'baseline': baseline_full,
        'target': target_full,
        'baseline_minor': baseline_minor,
        'target_minor': target_minor,
        'is_z_stream': is_z_stream,
        'timestamp': datetime.now().isoformat(),
        'validation_result': validation_result,
        'channel_availability': channel_analysis,
        'accepted_vs_channels': accepted_analysis,
        'upgrade_paths': upgrade_analysis,
        'cross_source': consistency_analysis,
        'marketplace': marketplace_analysis,
        'summary': {
            'baseline_in_stable': channel_analysis['baseline_in_stable'],
            'target_highest_channel': channel_analysis['target_highest_channel'],
            'baseline_channels': channel_analysis['baseline_version_channels'],
            'target_channels': channel_analysis['target_version_channels'],
            'accepted_not_in_channel': len(accepted_analysis['accepted_only']),
            'total_upgrade_paths': upgrade_analysis['total_paths'],
            'direct_path_exists': upgrade_analysis['direct_path_exists'],
            'paths_from_baseline': upgrade_analysis['paths_from_baseline'],
            'paths_to_target': upgrade_analysis['paths_to_target'],
            'target_is_ga': consistency_analysis.get('target_is_ga', False),
            'marketplace_available': marketplace_analysis.get('available', False),
            'target_aws_marketplace': marketplace_analysis['aws']['target']['rosa_enabled'] if marketplace_analysis.get('available') else None,
            'target_gcp_marketplace': marketplace_analysis['gcp']['target']['gcp_marketplace_enabled'] if marketplace_analysis.get('available') else None,
            'api_errors': api_errors,
        }
    }

    # Always generate JSON report
    json_file = os.path.join(
        report_dir,
        f"gap-analysis-versions-channels_{baseline_minor}_to_{target_minor}_{timestamp}.json"
    )
    generate_json_report(report_data, json_file)
    log_info(f"\nJSON report generated: {json_file}")

    # Skip HTML if full report mode
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping HTML reports (full report will be generated)")
    else:
        html_file = os.path.join(
            report_dir,
            f"gap-analysis-versions-channels_{baseline_minor}_to_{target_minor}_{timestamp}.html"
        )
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    # Always pass (informational only)
    log_success("=" * 60)
    log_success("✓ VALIDATION PASSED - Versions & Channels (Informational)")
    log_success("=" * 60)
    log_success(f"\nCHECK #6: Versions & Channels Analysis [PASS]")
    log_success(f"  Data Sources: Cincinnati API, Accepted Streams, Sippy")

    if is_z_stream:
        log_success(f"  Comparison Type: Z-stream ({baseline_full} → {target_full})")
    else:
        log_success(f"  Comparison Type: Cross-minor ({baseline_minor} → {target_minor})")

    if channel_analysis['baseline_in_stable']:
        log_success(f"  ✓ Baseline {baseline_full} is in stable channel")
    else:
        log_success(f"  ℹ️  Baseline {baseline_full} not in stable (channels: {', '.join(channel_analysis['baseline_version_channels']) or 'none'})")

    log_success(f"  ℹ️  Target {target_full} highest channel: {channel_analysis['target_highest_channel']}")

    if upgrade_analysis['total_paths'] > 0:
        log_success(f"  ✓ {upgrade_analysis['total_paths']} upgrade path(s) available")
    else:
        log_success(f"  ℹ️  No upgrade paths found in {upgrade_analysis['channel_queried']}")

    if accepted_analysis['accepted_only']:
        log_success(f"  ℹ️  {len(accepted_analysis['accepted_only'])} version(s) accepted but not yet in channels")

    if marketplace_analysis.get('available'):
        aws_status = marketplace_analysis['aws']['target']['rosa_enabled']
        gcp_status = marketplace_analysis['gcp']['target']['gcp_marketplace_enabled']
        if aws_status is not None:
            log_success(f"  {'✓' if aws_status else '⚠️ '} AWS Marketplace (ROSA): {'available' if aws_status else 'NOT available'}")
        if gcp_status is not None:
            log_success(f"  {'✓' if gcp_status else '⚠️ '} GCP Marketplace: {'available' if gcp_status else 'NOT available'}")

    log_success("")
    log_success(f"✅ PASSED - Version & Channel analysis complete (informational)")

    # Generate status file for gap-all.sh
    accepted_not_in_channel = len(accepted_analysis['accepted_only'])
    if accepted_not_in_channel > 0:
        status_message = f"{accepted_not_in_channel} accepted-only, {upgrade_analysis['total_paths']} upgrade paths"
    else:
        status_message = f"{upgrade_analysis['total_paths']} upgrade paths"

    status_details = {
        "is_z_stream": is_z_stream,
        "accepted_not_in_channel": accepted_not_in_channel,
        "total_upgrade_paths": upgrade_analysis['total_paths'],
        "direct_path_exists": upgrade_analysis['direct_path_exists'],
        "baseline_in_stable": channel_analysis['baseline_in_stable'],
        "target_highest_channel": channel_analysis['target_highest_channel'],
        "marketplace_available": marketplace_analysis.get('available', False),
        "message": status_message
    }

    generate_status_report(
        check_number=6,
        check_name="Versions & Channels",
        status="PASS",
        details=status_details,
        report_dir=report_dir
    )

    sys.exit(0)


if __name__ == '__main__':
    main()
