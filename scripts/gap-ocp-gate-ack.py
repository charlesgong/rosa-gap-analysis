#!/usr/bin/env python3
"""OCP Admin Gate Acknowledgment Analysis - Verify admin gates are acknowledged for upgrades."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, log_warning
from openshift_releases import resolve_openshift_version, extract_minor_version, get_next_minor_version
from reporters import generate_html_report, generate_json_report, generate_status_report
from ack_validation import fetch_yaml_from_url, calculate_expected_baseline, validate_config_yaml

try:
    import yaml
except ImportError:
    log_error("PyYAML not installed. Please install: pip3 install PyYAML")
    sys.exit(1)


# GitHub raw URLs
CVO_ADMIN_GATE_URL = "https://raw.githubusercontent.com/openshift/cluster-version-operator/release-{version}/install/0000_00_cluster-version-operator_01_admingate_configmap.yaml"
MCC_ADMIN_ACK_URL = "https://raw.githubusercontent.com/openshift/managed-cluster-config/master/deploy/osd-cluster-acks/ocp/{version}/admin-ack.yaml"


def fetch_yaml_from_github(url):
    """Fetch and parse YAML from GitHub."""
    try:
        req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=30) as response:
            data = response.read()
            return yaml.safe_load(data)
    except HTTPError as e:
        if e.code == 404:
            return None
        raise
    except (URLError, yaml.YAMLError) as e:
        log_error(f"Failed to fetch or parse YAML from {url}: {e}")
        raise


def fetch_admin_gates(version):
    """Fetch admin gates ConfigMap from cluster-version-operator repo."""
    url = CVO_ADMIN_GATE_URL.format(version=version)
    log_info(f"Fetching admin gates from {url}")

    configmap = fetch_yaml_from_github(url)
    if not configmap:
        log_error(f"Admin gate ConfigMap not found for version {version}")
        return None

    # Extract gates from data field
    gates = configmap.get('data', {})
    if gates:
        log_success(f"Found {len(gates)} admin gate(s) for version {version}")
    else:
        log_info(f"No admin gates found for version {version}")

    return gates


def fetch_admin_acks(version):
    """
    Fetch admin acknowledgments from managed-cluster-config repo.

    Tries both admin-ack.yaml and admin-gates.yaml filenames.

    Returns:
        tuple: (acks_data, filename) where filename is the file that was found,
               or (None, None) if neither file exists
    """
    # Try both possible filenames
    possible_filenames = ['admin-ack.yaml', 'admin-gates.yaml']

    for filename in possible_filenames:
        url = f"https://raw.githubusercontent.com/openshift/managed-cluster-config/master/deploy/osd-cluster-acks/ocp/{version}/{filename}"
        log_info(f"Fetching admin acknowledgments from {url}")

        ack_configmap = fetch_yaml_from_github(url)
        if ack_configmap:
            # Extract acks from data field
            acks = ack_configmap.get('data', {})
            if acks:
                log_success(f"Found {len(acks)} acknowledgment(s) in {filename} for version {version}")
            else:
                log_warning(f"No acknowledgments found in {filename} for version {version}")
            return (acks, filename)

    log_warning(f"Admin acknowledgment file not found for version {version} (tried: {', '.join(possible_filenames)})")
    return (None, None)


def get_pr_link_for_file(file_path, target_version):
    """
    Find the PR that introduced a specific file in managed-cluster-config.

    Uses commit history API to find the exact commit that added the file,
    then queries for the PR associated with that commit.

    Args:
        file_path: Path to file in managed-cluster-config repo (e.g., "deploy/osd-cluster-acks/ocp/4.22/admin-ack.yaml")
        target_version: Target version (e.g., "4.22")

    Returns:
        GitHub PR URL string or None if not found
    """
    import os
    from urllib.request import Request
    from urllib.error import HTTPError, URLError
    import json

    try:
        # Step 1: Get commit history for this specific file
        # This returns commits in reverse chronological order (newest first)
        commits_api_url = f'https://api.github.com/repos/openshift/managed-cluster-config/commits?path={file_path}&per_page=50'

        headers = {'Accept': 'application/vnd.github.v3+json'}
        gh_token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if gh_token:
            headers['Authorization'] = f'token {gh_token}'

        req = Request(commits_api_url, headers=headers)
        response = urlopen(req, timeout=10)
        commits = json.loads(response.read().decode('utf-8'))

        if not commits:
            return None

        # The last commit in the list is the oldest (when file was added)
        first_commit_sha = commits[-1]['sha']

        # Step 2: Get the PR associated with this commit
        pr_api_url = f'https://api.github.com/repos/openshift/managed-cluster-config/commits/{first_commit_sha}/pulls'
        req = Request(pr_api_url, headers=headers)
        response = urlopen(req, timeout=10)
        prs = json.loads(response.read().decode('utf-8'))

        if prs:
            # Return the first PR (should only be one)
            return prs[0]['html_url']

    except (HTTPError, URLError, json.JSONDecodeError, KeyError, IndexError, Exception) as e:
        # Commit history API failed, fall back to title-based search
        pass

    # Fallback: Search for PRs by title (less accurate but still useful)
    try:
        from urllib.parse import quote_plus

        query = f'{target_version} in:title repo:openshift/managed-cluster-config is:pr is:merged'
        api_url = f'https://api.github.com/search/issues?q={quote_plus(query)}&sort=updated&order=desc&per_page=20'

        headers = {'Accept': 'application/vnd.github.v3+json'}
        gh_token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if gh_token:
            headers['Authorization'] = f'token {gh_token}'

        req = Request(api_url, headers=headers)
        response = urlopen(req, timeout=10)
        data = json.loads(response.read().decode('utf-8'))

        items = data.get('items', [])
        if items:
            filename = file_path.split('/')[-1]
            for item in items:
                title = item.get('title', '').lower()
                if target_version in title or filename in title:
                    return item['html_url']
            return items[0]['html_url']

    except Exception:
        pass

    return None


def validate_ocp_acknowledgment_structure(baseline, target, gates_exist, ack_file_exists, ack_filename=None):
    """
    Validate OCP acknowledgment directory structure based on gate presence.

    Expected behavior:
    - If gates exist: BOTH config.yaml AND (admin-ack.yaml OR admin-gates.yaml) MUST exist
    - If no gates: BOTH files MUST be absent (directory should not exist)

    Args:
        baseline: Baseline version
        target: Target version
        gates_exist: Whether admin gates exist in cluster-version-operator
        ack_file_exists: Whether acknowledgment file exists
        ack_filename: The actual acknowledgment filename found (admin-ack.yaml or admin-gates.yaml)
    Returns:
        dict with validation results and warnings
    """
    target_minor = extract_minor_version(target)
    expected_baseline = calculate_expected_baseline(target_minor)

    # Default to admin-ack.yaml if filename not provided (backwards compatibility)
    if ack_filename is None:
        ack_filename = 'admin-ack.yaml'

    config_url = f"https://raw.githubusercontent.com/openshift/managed-cluster-config/master/deploy/osd-cluster-acks/ocp/{target_minor}/config.yaml"

    result = {
        'valid': False,
        'config_exists': False,
        'ack_exists': ack_file_exists,
        'ack_filename': ack_filename,
        'expected_baseline': expected_baseline,
        'actual_baseline': None,
        'errors': [],
        'warnings': []
    }

    log_info(f"Validating acknowledgment structure (gates_exist={gates_exist}, ack_file={ack_filename})...")

    try:
        config_data = fetch_yaml_from_url(config_url)
        config_exists = config_data is not None
        result['config_exists'] = config_exists

        if gates_exist:
            # Gates exist: BOTH files MUST exist
            if not config_exists:
                result['errors'].append(f"config.yaml required but not found at {config_url}")
            if not ack_file_exists:
                result['errors'].append(f"Acknowledgment file (admin-ack.yaml or admin-gates.yaml) required but not found")

            if config_exists and ack_file_exists:
                # Validate config.yaml content
                is_valid, errors, actual_baseline = validate_config_yaml(
                    config_data,
                    expected_baseline,
                    selector_key=None
                )
                result['valid'] = is_valid
                result['errors'].extend(errors)
                result['actual_baseline'] = actual_baseline
            else:
                result['valid'] = False
        else:
            # No gates: "both or neither" rule
            # Check acknowledgment file first, then config.yaml
            if ack_file_exists and config_exists:
                # Both files present → PASS with WARNING (show PR for acknowledgment file)
                file_path = f"deploy/osd-cluster-acks/ocp/{target_minor}/{ack_filename}"
                pr_link = get_pr_link_for_file(file_path, target_minor)

                warning_msg = {
                    'type': 'orphaned_files',
                    'message': f'No admin gates found in cluster-version-operator for version {target_minor}, but unexpected {ack_filename} file is present in managed-cluster-config',
                    'file': file_path,
                    'pr_link': pr_link,
                    'version': target_minor
                }
                result['warnings'].append(warning_msg)
                log_warning(f"⚠️  Orphaned files detected: {file_path}")
                if pr_link:
                    log_warning(f"   Introduced in PR: {pr_link}")

                # Don't add to errors - this is just a warning
                result['valid'] = True

            elif ack_file_exists or config_exists:
                # Only one file present → FAIL
                if ack_file_exists:
                    missing_file = 'config.yaml'
                    present_file = ack_filename
                else:
                    missing_file = 'acknowledgment file (admin-ack.yaml or admin-gates.yaml)'
                    present_file = 'config.yaml'

                result['errors'].append(f'{present_file} exists but {missing_file} is missing (both required when no gates)')
                result['valid'] = False

            else:
                # Neither file exists - normal/expected case
                result['valid'] = True

    except Exception as e:
        result['errors'].append(f"Error validating acknowledgment structure: {e}")

    return result


def analyze_gate_acknowledgments(baseline_version, target_version, baseline_gates, target_acks):
    """Analyze if gates from baseline are properly acknowledged in target."""
    result = {
        'gates_requiring_ack': [],
        'acknowledged_gates': [],
        'unacknowledged_gates': [],
        'extra_acks': [],
        'ack_file_missing': target_acks is None
    }

    if not baseline_gates:
        log_info(f"No admin gates in baseline version {baseline_version}, no acknowledgments required")
        return result

    gate_keys = set(baseline_gates.keys())
    result['gates_requiring_ack'] = sorted(gate_keys)

    if target_acks is None:
        # Acknowledgment file is missing but gates exist
        result['unacknowledged_gates'] = sorted(gate_keys)
        log_error(f"Admin gates exist in {baseline_version} but no acknowledgment file found for {target_version}")
        return result

    ack_keys = set(target_acks.keys())

    # Check which gates are acknowledged
    for gate_key in gate_keys:
        if gate_key in ack_keys:
            result['acknowledged_gates'].append(gate_key)
        else:
            result['unacknowledged_gates'].append(gate_key)

    # Check for extra acknowledgments (not strictly an error, but informational)
    result['extra_acks'] = sorted(ack_keys - gate_keys)

    # Sort for consistent output
    result['acknowledged_gates'] = sorted(result['acknowledged_gates'])
    result['unacknowledged_gates'] = sorted(result['unacknowledged_gates'])

    return result


def print_analysis(analysis, baseline, target):
    """Print analysis results."""
    if not analysis['gates_requiring_ack']:
        log_success(f"No admin gates in {baseline}, upgrade to {target} requires no acknowledgments")
        return

    log_info(f"Admin gates in {baseline} requiring acknowledgment: {len(analysis['gates_requiring_ack'])}")

    if analysis['ack_file_missing']:
        log_error(f"❌ UPGRADE BLOCKED: Acknowledgment file missing for {target}")
        log_error(f"   Required file: deploy/osd-cluster-acks/ocp/{target}/admin-ack.yaml")
        return

    if analysis['unacknowledged_gates']:
        log_error(f"❌ UPGRADE BLOCKED: {len(analysis['unacknowledged_gates'])} gate(s) not acknowledged")
        for gate in analysis['unacknowledged_gates']:
            log_error(f"   - {gate}")

    if analysis['acknowledged_gates']:
        log_success(f"✅ {len(analysis['acknowledged_gates'])} gate(s) properly acknowledged")
        for gate in analysis['acknowledged_gates']:
            log_success(f"   - {gate}")

    if analysis['extra_acks']:
        log_info(f"ℹ️  {len(analysis['extra_acks'])} extra acknowledgment(s) present (not required by baseline)")
        for ack in analysis['extra_acks']:
            log_info(f"   - {ack}")

    # Final verdict
    if analysis['unacknowledged_gates']:
        log_error(f"\n❌ UPGRADE NOT READY: {baseline} → {target}")
    else:
        log_success(f"\n✅ UPGRADE READY: All gates acknowledged for {baseline} → {target}")


def check_ocm_version_gates(target_version):
    """Verify OCM version gates configuration. Scoped to 4.x versions only."""
    major = target_version.split(".")[0]
    if major != "4":
        log_info(f"Skipping OCM version gates check for {major}.x (only applicable to 4.x versions).")
        return {
            'status': 'PASS',
            'message': f'OCM version gates check skipped for {major}.x (only applicable to 4.x).',
            'gates': []
        }

    ocm_path = shutil.which("ocm")
    if not ocm_path:
        log_warning("OCM CLI binary missing in PATH. Skipped version gates check.")
        return {
            'status': 'WARN',
            'message': 'OCM CLI binary missing in PATH. Skipped version gates check.',
            'gates': []
        }

    try:
        log_info("Fetching OCM version gates via 'ocm' CLI...")
        cmd = ["ocm", "get", "/api/clusters_mgmt/v1/version_gates"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            log_warning("Failed to query OCM version gates via 'ocm' CLI (is 'ocm' CLI logged in?). Skipped check.")
            return {
                'status': 'WARN',
                'message': f"Failed to query 'ocm get /api/clusters_mgmt/v1/version_gates' (returncode={proc.returncode}). Ensure 'ocm' CLI is logged in.",
                'gates': []
            }

        gates_data = json.loads(proc.stdout)
        version_prefix = ".".join(target_version.split(".")[:2])
        matching_gates = []
        if gates_data and "items" in gates_data:
            for gate in gates_data["items"]:
                if version_prefix in gate.get("version_raw_id_prefix", ""):
                    matching_gates.append(gate)
                    
        if matching_gates:
            log_success(f"Found {len(matching_gates)} configured OCM version gate(s) for {version_prefix}.x")
            return {
                'status': 'PASS',
                'message': f"Found {len(matching_gates)} configured version gates for {version_prefix}.x.",
                'gates': matching_gates
            }
        else:
            log_warning(f"No configured OCM version gates found for {version_prefix}.x")
            return {
                'status': 'WARN',
                'message': f"No specific version gates found for release prefix {version_prefix}.x. Ensure none are required.",
                'gates': []
            }
    except Exception as e:
        log_error(f"Failed to fetch or process OCM version gates: {e}")
        return {
            'status': 'FAIL',
            'message': f"Failed to fetch OCM version gates: {e}",
            'gates': []
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze OCP admin gate acknowledgments for upgrade readiness.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check if gates from 4.21 are acknowledged in 4.22
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

  # Auto-detect versions
  %(prog)s

Exit Codes:
  0 - Target version validation passed (PASS)
  1 - Target version validation failed (FAIL) OR execution failure
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

    # Extract minor versions (admin gates use minor versions like 4.21, 4.22)
    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)

    # Determine which version to check for acknowledgments
    # For z-stream upgrades (e.g., 4.19.30 → 4.19.31), validate gates from 4.19 against acks in 4.20
    # For cross-minor upgrades (e.g., 4.19 → 4.20), validate gates from 4.19 against acks in 4.20
    if baseline_minor == target_minor:
        # Z-stream upgrade: check acks in next minor version
        ack_check_version = get_next_minor_version(baseline_minor)
        is_zstream = True
        log_info(f"Z-stream upgrade detected ({baseline_full} → {target_full})")
    else:
        # Cross-minor upgrade: check acks in target
        ack_check_version = target_minor
        is_zstream = False

    # Main execution
    log_info("Starting OCP Admin Gate Acknowledgment Analysis")
    log_info("=" * 60)
    log_info(f"Baseline version: {baseline_full} (minor: {baseline_minor})")
    log_info(f"Target version: {target_full} (minor: {target_minor})")
    if is_zstream:
        log_info(f"Acknowledgment check version: {ack_check_version} (next minor for z-stream)")
    log_info("=" * 60)

    # Exit early if dry-run
    if args.dry_run:
        log_info("")
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    try:
        # Fetch admin gates from baseline version
        log_info(f"\nFetching admin gates from cluster-version-operator for version {baseline_minor}...")
        baseline_gates = fetch_admin_gates(baseline_minor)

        # Fetch admin acknowledgments from ack_check_version
        log_info(f"Fetching admin acknowledgments from managed-cluster-config for version {ack_check_version}...")
        target_acks, ack_filename = fetch_admin_acks(ack_check_version)

        # Analyze acknowledgments
        log_info("\nAnalyzing gate acknowledgments...")
        log_info(f"Validating gates from {baseline_minor} against acknowledgments in {ack_check_version}")
        analysis = analyze_gate_acknowledgments(baseline_minor, ack_check_version, baseline_gates, target_acks)

        # Print results with CHECK #5
        log_info("\nCHECK #5: OCP Admin Gate Acknowledgments")
        print_analysis(analysis, baseline_minor, ack_check_version)

        # Validate acknowledgment structure based on gate presence
        log_info("\nValidating acknowledgment structure...")
        gates_count = len(analysis['gates_requiring_ack'])
        gates_exist = gates_count > 0
        ack_file_exists = target_acks is not None

        structure_validation = validate_ocp_acknowledgment_structure(
            baseline_minor, ack_check_version, gates_exist, ack_file_exists, ack_filename
        )

        if structure_validation['valid']:
            if gates_exist:
                ack_file = structure_validation.get('ack_filename', 'admin-ack.yaml')
                log_success(f"✓ Acknowledgment structure valid: config.yaml and {ack_file} present")
                log_success(f"✓ config.yaml baseline version {structure_validation['actual_baseline']} matches expected")
            else:
                log_success(f"✓ Acknowledgment structure valid: no gates, directory correctly absent")
        else:
            log_error("✗ Acknowledgment structure validation failed:")
            for error in structure_validation['errors']:
                log_error(f"  - {error}")

        # Check OCM Version Gates
        log_info("\nChecking OCM Version Gates...")
        ocm_gates_result = check_ocm_version_gates(target_full)

        # Generate reports
        report_dir = args.report_dir
        os.makedirs(report_dir, exist_ok=True)

        timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Calculate summary
        acked_count = len(analysis['acknowledged_gates'])
        unacked_count = len(analysis['unacknowledged_gates'])

        # Determine validation result
        # 1. If no gates: structure must be valid (both files absent)
        # 2. If gates exist: all gates must be acked AND structure must be valid (both files present)
        if gates_count == 0:
            gates_valid = True  # No gates to acknowledge
            overall_valid = structure_validation['valid']
        else:
            gates_valid = (unacked_count == 0 and not analysis['ack_file_missing'])
            overall_valid = gates_valid and structure_validation['valid']

        # Include OCM version gates status in overall validation result (fail if OCM gates check failed)
        ocm_gates_valid = ocm_gates_result['status'] != 'FAIL'
        overall_valid = overall_valid and ocm_gates_valid

        validation_result = 'PASS' if overall_valid else 'FAIL'
        upgrade_ready = overall_valid  # For backward compatibility in reports

        report_data = {
            'type': 'OCP Admin Gate Acknowledgment Analysis',
            'baseline': baseline_minor,
            'target': target_minor,
            'ack_check_version': ack_check_version,
            'is_zstream': is_zstream,
            'baseline_full': baseline_full,
            'target_full': target_full,
            'timestamp': datetime.now().isoformat(),
            'validation_result': validation_result,
            'structure_validation': structure_validation,
            'ocm_version_gates': ocm_gates_result,
            'analysis': analysis,
            'summary': {
                'gates_requiring_ack': gates_count,
                'acknowledged': acked_count,
                'unacknowledged': unacked_count,
                'extra_acks': len(analysis['extra_acks']),
                'ack_file_missing': analysis['ack_file_missing'],
                'upgrade_ready': upgrade_ready
            },
            'baseline_gates': baseline_gates or {},
            'target_acks': target_acks or {},
            'warnings': structure_validation.get('warnings', [])
        }

        # Always generate JSON report (needed for combined report)
        json_file = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{ack_check_version}{timestamp_suffix}.json")
        generate_json_report(report_data, json_file)
        log_info(f"JSON report generated: {json_file}")

        # Skip HTML reports if GAP_FULL_REPORT is set (full report will include these)
        if os.environ.get('GAP_FULL_REPORT'):
            log_info("Skipping HTML reports (full report will be generated)")
        else:
            # Generate HTML report
            html_file = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{ack_check_version}{timestamp_suffix}.html")
            generate_html_report(report_data, html_file)
            log_info(f"HTML report generated: {html_file}")

        # Exit based on validation result
        mcc_ocp_ack_url = f"https://github.com/openshift/managed-cluster-config/tree/master/deploy/osd-cluster-acks/ocp/{ack_check_version}"

        if validation_result == 'FAIL':
            log_error("=" * 60)
            log_error("✗ VALIDATION FAILED")
            log_error("=" * 60)
            log_error(f"\nCHECK #5: OCP Admin Gate Acknowledgments [FAIL]")
            log_error(f"Location: {mcc_ocp_ack_url}")
            log_error("")

            if ocm_gates_result['status'] == 'FAIL':
                log_error(f"OCM Version Gates validation failed: {ocm_gates_result['message']}")

            if gates_count > 0:
                if unacked_count > 0:
                    log_error(f"Gate acknowledgments failed: {unacked_count} gate(s) not acknowledged")
                if analysis['ack_file_missing']:
                     log_error("admin-ack.yaml required but not found")

            if not structure_validation['valid']:
                log_error("Acknowledgment structure validation failed:")
                for error in structure_validation['errors']:
                    log_error(f"  - {error}")

            log_error("")
            log_error(f"❌ FAILED - Target version validation failed")

            # Generate status report for gap-all.sh
            status_message = f"{unacked_count} gate(s) not acknowledged" if unacked_count > 0 else "validation failed"
            status_details = {
                "gates_count": gates_count,
                "acked_count": acked_count,
                "unacked_count": unacked_count,
                "validation_passed": False,
                "message": status_message
            }
            generate_status_report(
                check_number=3,
                check_name="OCP Admin Gate Acknowledgments",
                status="FAIL",
                details=status_details,
                report_dir=args.report_dir,
            )

            sys.exit(1)
        else:
            log_success("=" * 60)
            log_success("✓ VALIDATION PASSED - All checks successful")
            log_success("=" * 60)
            log_success(f"\nCHECK #5: OCP Admin Gate Acknowledgments [PASS]")
            log_success(f"  Location: {mcc_ocp_ack_url}")

            if gates_count > 0:
                log_success(f"  ✓ {acked_count} gate(s) properly acknowledged")
                log_success(f"  ✓ Acknowledgment structure valid (config.yaml + admin-ack.yaml present)")
                if structure_validation['actual_baseline']:
                    log_success(f"  ✓ config.yaml: baseline version {structure_validation['actual_baseline']} validated")
            else:
                log_success(f"  ✓ No admin gates requiring acknowledgment")
                log_success(f"  ✓ Acknowledgment directory correctly absent")

            log_success("")
            log_success(f"✅ PASSED - Target version structure validated")

            # Generate status report for gap-all.sh
            if gates_count > 0:
                status_message = f"{acked_count} gate(s) acknowledged"
            else:
                status_message = "no gates requiring acknowledgment"

            status_details = {
                "gates_count": gates_count,
                "acked_count": acked_count,
                "unacked_count": unacked_count,
                "validation_passed": True,
                "message": status_message
            }
            generate_status_report(
                check_number=3,
                check_name="OCP Admin Gate Acknowledgments",
                status="PASS",
                details=status_details,
                report_dir=args.report_dir,
            )

            sys.exit(0)

    except Exception as e:
        log_error(f"Analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
