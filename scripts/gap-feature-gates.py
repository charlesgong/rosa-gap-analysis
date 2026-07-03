#!/usr/bin/env python3
"""Feature Gate Gap Analysis - Compare feature gates between OpenShift versions."""

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, check_command
from openshift_releases import resolve_openshift_version, extract_minor_version
from reporters import generate_html_report, generate_json_report, generate_status_report


SIPPY_FEATURE_GATES_API = "https://sippy.dptools.openshift.org/api/feature_gates"


def fetch_feature_gates(version, max_retries=2):
    """Fetch feature gates for a specific version from Sippy API."""
    log_info(f"Fetching feature gates for version {version}...")

    url = f"{SIPPY_FEATURE_GATES_API}?release={version}"
    req = Request(url, headers={'User-Agent': 'gap-analysis-script'})

    for attempt in range(max_retries + 1):
        try:
            with urlopen(req, timeout=30) as response:
                data = response.read()
                gates = json.loads(data)

            if not gates:
                log_error(f"No feature gates found for version {version}")
                return []

            log_success(f"Fetched {len(gates)} feature gates for version {version}")
            return gates

        except (URLError, socket.timeout, json.JSONDecodeError) as e:
            if attempt < max_retries:
                delay = 2 ** (attempt + 1)
                log_info(f"Retry {attempt + 1}/{max_retries} after {delay}s: {e}")
                time.sleep(delay)
            else:
                log_error(f"Failed to fetch feature gates for version {version} after {max_retries + 1} attempts: {e}")
                return []


def is_hypershift_relevant(enabled_list):
    """
    Check if a feature gate has Hypershift-relevant enablement.

    Returns True if enabled list contains any of:
    - Default:Hypershift
    - DevPreviewNoUpgrade:Hypershift
    - TechPreviewNoUpgrade:Hypershift
    """
    hypershift_categories = [
        'Default:Hypershift',
        'DevPreviewNoUpgrade:Hypershift',
        'TechPreviewNoUpgrade:Hypershift'
    ]
    return any(cat in enabled_list for cat in hypershift_categories)


def has_default_hypershift(enabled_list):
    """Check if a feature gate has Default:Hypershift enablement."""
    return 'Default:Hypershift' in enabled_list


def compare_feature_gates(baseline_data, target_data):
    """
    Compare feature gates between baseline and target versions.

    Only considers Hypershift-relevant enablement types:
    - Default:Hypershift
    - DevPreviewNoUpgrade:Hypershift
    - TechPreviewNoUpgrade:Hypershift
    """
    # Create lookup dicts for all gates
    baseline_dict = {g['feature_gate']: g for g in baseline_data}
    target_dict = {g['feature_gate']: g for g in target_data}

    # Filter to only Hypershift-relevant gates
    baseline_gates_hypershift = {
        name for name, gate in baseline_dict.items()
        if is_hypershift_relevant(gate.get('enabled', []))
    }
    target_gates_hypershift = {
        name for name, gate in target_dict.items()
        if is_hypershift_relevant(gate.get('enabled', []))
    }

    # Find differences (only among Hypershift-relevant gates)
    added = sorted(target_gates_hypershift - baseline_gates_hypershift)
    removed = sorted(baseline_gates_hypershift - target_gates_hypershift)
    common = baseline_gates_hypershift & target_gates_hypershift

    # Analyze default enablement changes
    newly_default = []
    removed_default = []
    continues_default = []

    for gate in common:
        baseline_enabled = baseline_dict[gate].get('enabled', [])
        target_enabled = target_dict[gate].get('enabled', [])

        baseline_has_default = has_default_hypershift(baseline_enabled)
        target_has_default = has_default_hypershift(target_enabled)

        if not baseline_has_default and target_has_default:
            newly_default.append(gate)
        elif baseline_has_default and not target_has_default:
            removed_default.append(gate)
        elif baseline_has_default and target_has_default:
            continues_default.append(gate)

    # Also check new gates that are Default:Hypershift
    for gate in added:
        if has_default_hypershift(target_dict[gate].get('enabled', [])):
            newly_default.append(gate)

    return {
        'added': sorted(added),
        'removed': sorted(removed),
        'newly_enabled_by_default': sorted(newly_default),
        'removed_from_default': sorted(removed_default),
        'continues_default_hypershift': sorted(continues_default)
    }


def print_comparison(comparison, baseline, target, verbose=False):
    """Print comparison results."""
    added_count = len(comparison['added'])
    removed_count = len(comparison['removed'])
    newly_default_count = len(comparison['newly_enabled_by_default'])
    removed_default_count = len(comparison['removed_from_default'])
    continues_default_count = len(comparison.get('continues_default_hypershift', []))

    total_changes = added_count + removed_count + newly_default_count + removed_default_count

    if total_changes == 0 and continues_default_count == 0:
        log_success(f"No feature gate differences found between {baseline} and {target}")
        return

    log_info("Feature gate differences detected (Hypershift-relevant only):")
    if added_count > 0:
        log_info(f"  - New feature gates: {added_count}")
    if removed_count > 0:
        log_info(f"  - Removed feature gates: {removed_count}")
    if newly_default_count > 0:
        log_info(f"  - Newly enabled by default (Default:Hypershift): {newly_default_count}")
    if removed_default_count > 0:
        log_info(f"  - Removed from default: {removed_default_count}")
    if continues_default_count > 0:
        log_info(f"  - Continues as Default:Hypershift: {continues_default_count}")

    if verbose:
        if added_count > 0:
            log_info("")
            log_info(f"New Hypershift-relevant feature gates in {target}:")
            for gate in comparison['added']:
                log_info(f"  + {gate}")

        if removed_count > 0:
            log_info("")
            log_info(f"Removed Hypershift-relevant feature gates in {target}:")
            for gate in comparison['removed']:
                log_info(f"  - {gate}")

        if newly_default_count > 0:
            log_info("")
            log_info(f"Newly enabled by default (Default:Hypershift) in {target}:")
            for gate in comparison['newly_enabled_by_default']:
                log_info(f"  ✓ {gate}")

        if removed_default_count > 0:
            log_info("")
            log_info(f"Removed from default in {target}:")
            for gate in comparison['removed_from_default']:
                log_info(f"  ✗ {gate}")

        if continues_default_count > 0:
            log_info("")
            log_info(f"Continues as Default:Hypershift in {target}:")
            for gate in comparison.get('continues_default_hypershift', []):
                log_info(f"  = {gate}")


def print_zstream_summary(default_hypershift_gates, total_hypershift_gates, version, verbose=False):
    """Print z-stream summary results."""
    log_success(f"Found {len(default_hypershift_gates)} Default:Hypershift gates in {version}")
    log_info(f"Total Hypershift-relevant gates: {total_hypershift_gates}")

    if verbose:
        log_info("")
        log_info(f"Default:Hypershift feature gates in {version}:")
        for gate in default_hypershift_gates:
            log_info(f"  ✓ {gate}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze feature gate differences between two OpenShift versions.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect versions (stable → candidate)
  %(prog)s

  # Explicit versions
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

  # Environment variables
  BASE_VERSION=4.21 TARGET_VERSION=4.22 %(prog)s

Exit Codes:
  0 - Successful execution (regardless of whether differences were found)
  1 - Execution failure (e.g., missing tools, network errors, invalid versions)
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
    # Check for single version resolution first (--version or OPENSHIFT_VERSION)
    openshift_version = args.version or os.environ.get('OPENSHIFT_VERSION')

    if openshift_version:
        # Single version auto-resolution
        log_info(f"Using single version: {openshift_version}")
        baseline_full, target_full = resolve_openshift_version(openshift_version)
        if not baseline_full or not target_full:
            log_error(f"Failed to resolve versions from: {openshift_version}")
            sys.exit(1)
    elif args.baseline and args.target:
        # Explicit baseline and target provided
        baseline_full = args.baseline
        target_full = args.target
    else:
        # Auto-detect (fallback to individual resolution)
        from openshift_releases import resolve_baseline_version, resolve_target_version
        baseline_full = args.baseline or resolve_baseline_version()
        target_full = args.target or resolve_target_version()

    # Feature gates API needs minor version only (e.g., "4.21" not "4.21.7")
    baseline = extract_minor_version(baseline_full)
    target = extract_minor_version(target_full)

    # Detect z-stream comparison
    is_z_stream = (baseline == target)

    # Main execution
    start_time = datetime.now()
    log_info("Starting Feature Gate Gap Analysis")
    log_info("=========================================")
    log_info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_info(f"Baseline version: {baseline_full} (minor: {baseline})")
    log_info(f"Target version: {target_full} (minor: {target})")
    if is_z_stream:
        log_info(f"Comparison type: Z-stream (same minor version)")
    else:
        log_info(f"Comparison type: Cross-minor ({baseline} → {target})")
    log_info("=========================================")

    # Exit early if dry-run
    if args.dry_run:
        log_info("")
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    # Check prerequisites
    check_command('curl')

    if is_z_stream:
        # Z-stream comparison: show default gates instead of differences
        log_info(f"Z-stream comparison detected: {baseline_full} → {target_full}")
        log_info(f"Z-stream updates should not introduce/remove feature gates")
        log_info(f"Showing default feature gates for {target}")

        # Fetch target version gates only
        target_data = fetch_feature_gates(target)

        # Filter to Default:Hypershift gates
        default_hypershift_gates = sorted(
            [gate['feature_gate'] for gate in target_data
             if has_default_hypershift(gate.get('enabled', []))]
        )

        # Count all Hypershift-relevant gates
        total_hypershift_gates = sum(
            1 for gate in target_data
            if is_hypershift_relevant(gate.get('enabled', []))
        )

        # Print results with CHECK #8
        log_info("\nCHECK #8: Feature Gates Analysis (Z-stream)")
        print_zstream_summary(default_hypershift_gates, total_hypershift_gates, target, args.verbose)

    else:
        # Cross-minor comparison: use existing logic
        log_info(f"Cross-minor comparison: {baseline} → {target}")

        # Fetch both versions
        baseline_data = fetch_feature_gates(baseline)
        target_data = fetch_feature_gates(target)

        # Collect all Default:Hypershift gates from target
        target_dict = {g['feature_gate']: g for g in target_data}
        default_hypershift_gates = sorted(
            [name for name, gate in target_dict.items()
             if has_default_hypershift(gate.get('enabled', []))],
        )
        total_hypershift_gates = sum(
            1 for gate in target_data
            if is_hypershift_relevant(gate.get('enabled', []))
        )

        # Compare
        log_info("Comparing feature gates...")
        comparison = compare_feature_gates(baseline_data, target_data)

        # Print results with CHECK #8
        log_info("\nCHECK #8: Feature Gates Analysis")
        print_comparison(comparison, baseline, target, args.verbose)

    # Generate reports
    # Create report directory if it doesn't exist
    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)

    timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    # Feature gates are informational only - always PASS regardless of changes
    validation_result = 'PASS'

    if is_z_stream:
        # Z-stream report data
        report_data = {
            'type': 'Feature Gate Gap Analysis',
            'version': target,
            'baseline': baseline_full,
            'target': target_full,
            'is_z_stream': True,
            'timestamp': datetime.now().isoformat(),
            'validation_result': validation_result,
            'default_hypershift_gates': default_hypershift_gates,
            'total_hypershift_gates': total_hypershift_gates,
            'summary': {
                'default_hypershift_gates': len(default_hypershift_gates),
                'total_hypershift_gates': total_hypershift_gates
            },
            'note': 'Z-stream updates should not change feature gates'
        }
    else:
        # Cross-minor report data
        added_count = len(comparison['added'])
        removed_count = len(comparison['removed'])
        newly_default_count = len(comparison['newly_enabled_by_default'])
        removed_default_count = len(comparison['removed_from_default'])
        continues_default_count = len(comparison.get('continues_default_hypershift', []))
        total_changes = added_count + removed_count + newly_default_count + removed_default_count

        report_data = {
            'type': 'Feature Gate Gap Analysis',
            'baseline': baseline,
            'target': target,
            'is_z_stream': False,
            'timestamp': datetime.now().isoformat(),
            'validation_result': validation_result,
            'comparison': comparison,
            'default_hypershift_gates': default_hypershift_gates,
            'total_hypershift_gates': total_hypershift_gates,
            'summary': {
                'added': added_count,
                'removed': removed_count,
                'newly_enabled_by_default': newly_default_count,
                'removed_from_default': removed_default_count,
                'continues_default_hypershift': continues_default_count,
                'total_changes': total_changes
            }
        }

    # Always generate JSON report (needed for combined report)
    json_file = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline}_to_{target}{timestamp_suffix}.json")
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    # Skip HTML reports if GAP_FULL_REPORT is set (full report will include these)
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping HTML reports (full report will be generated)")
    else:
        # Generate HTML report
        html_file = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline}_to_{target}{timestamp_suffix}.html")
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    # Feature gates are informational only - always pass
    sippy_url = f"https://sippy.dptools.openshift.org/api/feature_gates?release={target}"

    log_success("=" * 60)
    log_success("✓ VALIDATION PASSED - Feature Gates (Informational)")
    log_success("=" * 60)
    log_success(f"\nCHECK #8: Feature Gates Analysis [PASS - Info]")
    log_success(f"  Data Source: Sippy API")
    log_success(f"  URL: {sippy_url}")

    if is_z_stream:
        log_success(f"  Comparison Type: Z-stream ({baseline_full} → {target_full})")
        log_success(f"  ℹ️  Z-stream updates should not change feature gates")
        log_success(f"  ✓ {len(default_hypershift_gates)} Default:Hypershift gates in {target}")
        log_success(f"  ✓ {total_hypershift_gates} total Hypershift-relevant gates")
    else:
        log_success(f"  Comparison Type: Cross-minor ({baseline} → {target})")
        if total_changes > 0:
            log_success(f"  ℹ️  Detected {total_changes} change(s) (informational only)")
            if added_count > 0:
                log_success(f"    • {added_count} new feature gate(s)")
            if removed_count > 0:
                log_success(f"    • {removed_count} removed feature gate(s)")
            if newly_default_count > 0:
                log_success(f"    • {newly_default_count} newly enabled by default")
            if removed_default_count > 0:
                log_success(f"    • {removed_default_count} removed from default")
        else:
            log_success(f"  ✓ No feature gate changes detected")

    log_success("")
    log_success(f"✅ PASSED - Feature Gates analysis complete (informational)")

    # Generate status report for gap-all.sh
    if is_z_stream:
        status_message = f"{len(default_hypershift_gates)} default gates"
    else:
        total_changes = added_count + removed_count + newly_default_count + removed_default_count
        if total_changes == 0:
            status_message = "no changes detected"
        else:
            status_message = f"{total_changes} change(s) detected"

    status_details = {
        "is_z_stream": is_z_stream,
        "total_changes": total_changes if not is_z_stream else 0,
        "added_count": added_count if not is_z_stream else 0,
        "removed_count": removed_count if not is_z_stream else 0,
        "newly_default_count": newly_default_count if not is_z_stream else 0,
        "removed_default_count": removed_default_count if not is_z_stream else 0,
        "default_gates_count": len(default_hypershift_gates) if is_z_stream else 0,
        "message": status_message
    }

    generate_status_report(
        check_number=8,
        check_name="Feature Gates Gap",
        status="PASS",
        details=status_details,
        report_dir=args.report_dir,
    )

    sys.exit(0)


if __name__ == '__main__':
    import os
    main()
