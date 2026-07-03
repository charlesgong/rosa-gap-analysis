#!/usr/bin/env python3
"""AWS STS Policy Gap Analysis - Compare STS policies between OpenShift versions."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent))

from common import log_info, log_success, log_error, log_warning, check_command, is_pre_ga_version
from openshift_releases import resolve_openshift_version, extract_minor_version
from reporters import generate_html_report, generate_json_report, generate_status_report
import shutil
from ack_validation import (
    fetch_yaml_from_url,
    calculate_expected_baseline,
    validate_config_yaml,
    validate_cloudcredential_yaml,
    validate_sts_resources
)


import importlib
_gap_marketplace = importlib.import_module("gap-marketplace")
check_aws_marketplace_enablement = _gap_marketplace.check_aws_marketplace_enablement


def validate_sts_acknowledgment(baseline, target, comparison=None, baseline_cr_dir=None, target_cr_dir=None):
    """
    Comprehensive validation of STS acknowledgment in managed-cluster-config.

    CHECK #1: Resources validation (resources/sts/{version}/)
    CHECK #2: Admin acknowledgment validation (deploy/osd-cluster-acks/sts/{version}/)

    Args:
        baseline: Baseline version (e.g., "4.20.5")
        target: Target version (e.g., "4.21.0")
        comparison: Comparison result from comparing OCP releases (with actions.target_only, actions.baseline_only)

    Returns:
        dict with validation results for both checks
    """
    # Use minor versions
    target_minor = extract_minor_version(target)
    expected_baseline = calculate_expected_baseline(target_minor)

    result = {
        'valid': False,
        'check_1_resources': {},
        'check_2_admin_ack': {}
    }

    # ═══════════════════════════════════════════════════════════════
    # CHECK #1: Resources Validation (resources/sts/{version}/)
    # ═══════════════════════════════════════════════════════════════
    log_info(f"CHECK #1: Validating resources/sts/{target_minor}/ directory...")

    # Pass expected changes from OCP release comparison to validation
    expected_changes = None
    if comparison:
        # Aggregate all per-file changes (not just globally new actions)
        # A permission may be new to one file but already exist in another
        all_added = set()
        all_removed = set()
        for file_change in comparison.get('file_changes', []):
            all_added.update(file_change.get('actions_added', []))
            all_removed.update(file_change.get('actions_removed', []))

        expected_changes = {
            'actions_added': list(all_added),
            'actions_removed': list(all_removed)
        }

    resources_result = validate_sts_resources(expected_baseline, target_minor, expected_changes, baseline_cr_dir, target_cr_dir)

    result['check_1_resources'] = {
        'status': 'PASS' if resources_result['valid'] else 'FAIL',
        'valid': resources_result['valid'],
        'errors': resources_result['errors'],
        'warnings': resources_result.get('warnings', []),
        'warnings_structured': resources_result.get('warnings_structured', []),
        'file_count': len(resources_result.get('file_results', {})),
        'changed_files': resources_result.get('changed_files', []),
        'changed_files_count': resources_result.get('changed_files_count', 0)
    }

    check_1_valid = resources_result['valid']

    # ═══════════════════════════════════════════════════════════════
    # CHECK #2: Admin Acknowledgment Validation (deploy/osd-cluster-acks/sts/{version}/)
    # ═══════════════════════════════════════════════════════════════
    log_info(f"CHECK #2: Validating deploy/osd-cluster-acks/sts/{target_minor}/ acknowledgment...")

    base_url = f"https://raw.githubusercontent.com/openshift/managed-cluster-config/master/deploy/osd-cluster-acks/sts/{target_minor}"

    check_2_result = {
        'status': 'PASS',
        'valid': True,
        'expected_baseline': expected_baseline,
        'actual_baseline': None,
        'files_checked': {},
        'errors': []
    }

    # Check config.yaml
    config_url = f"{base_url}/config.yaml"
    config_result = {'exists': False, 'valid': False, 'errors': []}

    try:
        config_data = fetch_yaml_from_url(config_url)
        if config_data is None:
            config_result['errors'].append(f"File not found")
            check_2_result['errors'].append("config.yaml not found")
        else:
            config_result['exists'] = True
            is_valid, errors, actual_baseline = validate_config_yaml(
                config_data,
                expected_baseline,
                selector_key="api.openshift.com/sts",
                selector_value="true"
            )
            config_result['valid'] = is_valid
            config_result['errors'] = errors
            check_2_result['actual_baseline'] = actual_baseline

            if not is_valid:
                check_2_result['errors'].extend(errors)
    except Exception as e:
        config_result['errors'].append(f"Error: {e}")
        check_2_result['errors'].append(f"config.yaml error: {e}")

    check_2_result['files_checked']['config.yaml'] = config_result

    # Check CloudCredential.yaml
    cc_url = f"{base_url}/osd-sts-ack_CloudCredential.yaml"
    cc_result = {'exists': False, 'valid': False, 'errors': []}

    try:
        cc_data = fetch_yaml_from_url(cc_url)
        if cc_data is None:
            cc_result['errors'].append(f"File not found")
            check_2_result['errors'].append("osd-sts-ack_CloudCredential.yaml not found")
        else:
            cc_result['exists'] = True
            is_valid, errors, actual_version = validate_cloudcredential_yaml(cc_data, target_minor)
            cc_result['valid'] = is_valid
            cc_result['errors'] = errors

            if not is_valid:
                check_2_result['errors'].extend(errors)
    except Exception as e:
        cc_result['errors'].append(f"Error: {e}")
        check_2_result['errors'].append(f"CloudCredential error: {e}")

    check_2_result['files_checked']['osd-sts-ack_CloudCredential.yaml'] = cc_result

    check_2_valid = (
        config_result.get('valid', False) and
        cc_result.get('valid', False) and
        len(check_2_result['errors']) == 0
    )

    check_2_result['valid'] = check_2_valid
    check_2_result['status'] = 'PASS' if check_2_valid else 'FAIL'

    result['check_2_admin_ack'] = check_2_result

    # Overall validity - BOTH checks must pass
    result['valid'] = check_1_valid and check_2_valid

    return result


def extract_credential_requests(version, cloud="aws"):
    """Extract credential requests using oc adm release extract."""
    temp_dir = tempfile.mkdtemp(prefix='ocp-crs-')

    # Construct release image URL
    # If version is just minor (e.g., "4.21"), append .0
    if version.count('.') == 1 and version.replace('.', '').isdigit():
        version = f"{version}.0"

    if version.replace('.', '').replace('-', '').isdigit() or '-rc' in version or '-ec' in version:
        release_image = f"quay.io/openshift-release-dev/ocp-release:{version}-x86_64"
    else:
        release_image = version

    log_info(f"Extracting credential requests from {release_image} for cloud={cloud}")

    try:
        # Run oc adm release extract
        cmd = [
            'oc', 'adm', 'release', 'extract',
            release_image,
            '--credentials-requests',
            f'--cloud={cloud}',
            f'--to={temp_dir}'
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        # Filter out warnings from stderr
        stderr_lines = [line for line in result.stderr.split('\n') if 'warning:' not in line.lower()]
        if stderr_lines and any(line.strip() for line in stderr_lines):
            for line in stderr_lines:
                if line.strip():
                    print(line, file=sys.stderr)

        if result.returncode != 0:
            log_error(f"Failed to extract credential requests for version {version}")
            return None

        log_success(f"Credential requests extracted to: {temp_dir}")
        return temp_dir

    except Exception as e:
        log_error(f"Failed to extract credential requests: {e}")
        return None


def convert_credential_requests_to_policy(cr_dir):
    """Convert CredentialsRequest YAML files to consolidated IAM policy JSON."""
    import glob
    try:
        import yaml
    except ImportError:
        log_error("PyYAML not installed. Please install: pip3 install PyYAML")
        sys.exit(1)

    # Initialize empty policy
    policy = {"Version": "2012-10-17", "Statement": []}

    # Find all YAML files
    yaml_files = glob.glob(os.path.join(cr_dir, '*.yaml'))

    if not yaml_files:
        log_warning(f"No YAML files found in {cr_dir}")
        return policy

    log_info(f"Processing {len(yaml_files)} credential request file(s)...")

    for yaml_file in yaml_files:
        basename = os.path.basename(yaml_file)

        try:
            with open(yaml_file, 'r') as f:
                cr = yaml.safe_load(f)

            # Extract statementEntries from providerSpec
            statement_entries = cr.get('spec', {}).get('providerSpec', {}).get('statementEntries', [])

            if not statement_entries:
                continue

            # Convert to IAM format (capitalize keys)
            for entry in statement_entries:
                statement = {
                    'Effect': entry.get('effect') or entry.get('Effect'),
                    'Action': entry.get('action') or entry.get('Action'),
                    'Resource': entry.get('resource') or entry.get('Resource', '*')
                }

                # Add Condition if present
                condition = entry.get('condition') or entry.get('Condition')
                if condition:
                    statement['Condition'] = condition

                policy['Statement'].append(statement)

            log_info(f"  ✓ Processed {basename}: {len(statement_entries)} statement(s)")

        except Exception as e:
            log_warning(f"Failed to process {basename}: {e}")
            continue

    # Deduplicate statements
    unique_statements = []
    seen = set()

    for stmt in policy['Statement']:
        # Create a hashable representation
        stmt_key = json.dumps(stmt, sort_keys=True)
        if stmt_key not in seen:
            seen.add(stmt_key)
            unique_statements.append(stmt)

    policy['Statement'] = unique_statements

    log_success(f"Converted to IAM policy: {len(unique_statements)} unique statement(s)")
    return policy


def get_sts_policy(version):
    """Get STS policy for a specific version. Returns (policy, cr_dir)."""
    log_info(f"Fetching AWS STS policy for version {version}...")

    # Extract credential requests
    cr_dir = extract_credential_requests(version, 'aws')
    if not cr_dir:
        sys.exit(1)

    # Convert to policy
    policy = convert_credential_requests_to_policy(cr_dir)

    # Validate we got data
    if len(policy['Statement']) == 0:
        log_error("No statements found in extracted credential requests")
        sys.exit(1)

    log_success("Successfully extracted STS policy")
    return policy, cr_dir


def compare_credential_requests_per_file(baseline_dir, target_dir):
    """Compare credential request files between baseline and target to detect per-file changes."""
    import glob
    try:
        import yaml
    except ImportError:
        return []

    changed_files = []

    # Get all YAML files from both directories
    baseline_files = {os.path.basename(f): f for f in glob.glob(os.path.join(baseline_dir, '*.yaml'))}
    target_files = {os.path.basename(f): f for f in glob.glob(os.path.join(target_dir, '*.yaml'))}

    # Check all files that exist in target
    for filename in sorted(target_files.keys()):
        target_file = target_files[filename]

        # Extract actions from target file
        target_actions = set()
        try:
            with open(target_file, 'r') as f:
                cr = yaml.safe_load(f)
            statement_entries = cr.get('spec', {}).get('providerSpec', {}).get('statementEntries', [])
            for entry in statement_entries:
                actions = entry.get('action') or entry.get('Action', [])
                if isinstance(actions, str):
                    actions = [actions]
                target_actions.update(actions)
        except:
            continue

        # Extract actions from baseline file (if exists)
        baseline_actions = set()
        if filename in baseline_files:
            try:
                with open(baseline_files[filename], 'r') as f:
                    cr = yaml.safe_load(f)
                statement_entries = cr.get('spec', {}).get('providerSpec', {}).get('statementEntries', [])
                for entry in statement_entries:
                    actions = entry.get('action') or entry.get('Action', [])
                    if isinstance(actions, str):
                        actions = [actions]
                    baseline_actions.update(actions)
            except:
                pass

        # Check if file changed
        actions_added = sorted(target_actions - baseline_actions)
        actions_removed = sorted(baseline_actions - target_actions)

        if actions_added or actions_removed:
            changed_files.append({
                'filename': filename,
                'actions_added': actions_added,
                'actions_removed': actions_removed,
                'actions_added_count': len(actions_added),
                'actions_removed_count': len(actions_removed)
            })

    return changed_files


def compare_sts_policies(baseline_policy, target_policy):
    """Compare two STS policies and return differences."""
    # Extract all actions from both policies
    baseline_actions = set()
    target_actions = set()

    for stmt in baseline_policy.get('Statement', []):
        actions = stmt.get('Action', [])
        if isinstance(actions, str):
            actions = [actions]
        baseline_actions.update(actions)

    for stmt in target_policy.get('Statement', []):
        actions = stmt.get('Action', [])
        if isinstance(actions, str):
            actions = [actions]
        target_actions.update(actions)

    # Find differences
    added = sorted(target_actions - baseline_actions)
    removed = sorted(baseline_actions - target_actions)

    return {
        'actions': {
            'baseline_only': removed,
            'target_only': added,
            'common': sorted(baseline_actions & target_actions)
        }
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze AWS STS policy gaps between two OpenShift versions.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect versions (stable → candidate)
  %(prog)s

  # Explicit versions
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

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
        baseline, target = resolve_openshift_version(openshift_version)
        if not baseline or not target:
            log_error(f"Failed to resolve versions from: {openshift_version}")
            sys.exit(1)
    elif args.baseline and args.target:
        # Explicit baseline and target provided
        baseline = args.baseline
        target = args.target
    else:
        # Auto-detect (fallback to individual resolution)
        from openshift_releases import resolve_baseline_version, resolve_target_version
        baseline = args.baseline or resolve_baseline_version()
        target = args.target or resolve_target_version()

    # Main execution
    log_info("Starting AWS STS Policy Gap Analysis")
    log_info("=========================================")
    log_info(f"Baseline version: {baseline}")
    log_info(f"Target version: {target}")
    log_info("=========================================")

    # Exit early if dry-run
    if args.dry_run:
        log_info("")
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    # Check prerequisites
    check_command('oc')
    check_command('jq')

    # Fetch policies and keep credential request directories for per-file comparison
    baseline_policy, baseline_cr_dir = get_sts_policy(baseline)
    target_policy, target_cr_dir = get_sts_policy(target)

    # Compare overall policies
    log_info("Comparing STS policies...")
    comparison = compare_sts_policies(baseline_policy, target_policy)

    # Compare per-file to detect which credential request files changed
    log_info("Comparing credential request files...")
    file_changes = compare_credential_requests_per_file(baseline_cr_dir, target_cr_dir)

    # Add file changes to comparison result
    comparison['file_changes'] = file_changes
    comparison['file_changes_count'] = len(file_changes)

    # Check for differences
    added_count = len(comparison['actions']['target_only'])
    removed_count = len(comparison['actions']['baseline_only'])
    total_changes = added_count + removed_count

    if total_changes == 0:
        log_success(f"No policy differences found between {baseline} and {target}")
    else:
        log_info(f"Policy differences detected: {added_count} added, {removed_count} removed")
        if file_changes:
            log_info(f"Changes detected in {len(file_changes)} credential request file(s)")

    # Generate reports
    # Create report directory if it doesn't exist
    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)

    # Generate timestamp suffix
    timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Always validate target version structure (regardless of whether changes detected)
    log_info("\nValidating target version structure in managed-cluster-config...")
    validation_checked = True

    # Pass the comparison result AND the OCP release temp directories to validate
    validation_details = validate_sts_acknowledgment(baseline, target, comparison, baseline_cr_dir, target_cr_dir)

    check_1 = validation_details['check_1_resources']
    check_2 = validation_details['check_2_admin_ack']

    target_minor = extract_minor_version(target)
    mcc_sts_url = f"https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/{target_minor}"
    mcc_ack_url = f"https://github.com/openshift/managed-cluster-config/tree/master/deploy/osd-cluster-acks/sts/{target_minor}"

    # Check AWS Marketplace Enablement
    log_info("\nChecking AWS Marketplace Enablement...")
    aws_marketplace_result = check_aws_marketplace_enablement(target)

    # For pre-GA versions, missing MCC scaffolding is expected
    pre_ga_override = False
    if not validation_details['valid'] and is_pre_ga_version(target):
        pre_ga_override = True
        log_warning(f"MCC scaffolding not yet created for pre-GA version {target}, skipping validation")
        validation_details['valid'] = True

    if validation_details['valid'] and aws_marketplace_result['status'] != 'FAIL':
        validation_result = 'PASS'
        log_success("=" * 60)
        if pre_ga_override:
            log_success("✓ VALIDATION PASSED (pre-GA, MCC scaffolding not yet required)")
        else:
            log_success("✓ VALIDATION PASSED - All checks successful")
        log_success("=" * 60)

        if not pre_ga_override:
            log_success(f"\nCHECK #1: Resources Validation [{check_1['status']}]")
            log_success(f"  Location: {mcc_sts_url}")
            log_success(f"  ✓ Validated {check_1['file_count']} policy file(s)")
            if check_1['changed_files_count'] > 0:
                log_success(f"  ✓ Changes detected in {check_1['changed_files_count']} file(s)")
            log_success(f"\nCHECK #2: Admin Acknowledgment [{check_2['status']}]")
            log_success(f"  Location: {mcc_ack_url}")
            log_success(f"  ✓ config.yaml: baseline version {check_2['actual_baseline']} matches expected")
            log_success(f"  ✓ CloudCredential: upgrade version validated")
        
        # Log AWS Marketplace success / warn
        if aws_marketplace_result['status'] == 'PASS':
            log_success(f"\nAWS Marketplace Enablement [PASS]")
            log_success(f"  ✓ {aws_marketplace_result['message']}")
        elif aws_marketplace_result['status'] == 'WARN':
            log_warning(f"\nAWS Marketplace Enablement [WARN]")
            log_warning(f"  ⚠ {aws_marketplace_result['message']}")
        log_success("")

        # Display warnings if any (these don't fail validation)
        if check_1.get('warnings'):
            log_warning("\n⚠ WARNINGS - Review recommended (does not fail validation):")
            log_warning("=" * 60)
            for warning in check_1['warnings']:
                log_warning(f"{warning}")
            log_warning("")
    else:
        validation_result = 'FAIL'
        log_error("=" * 60)
        log_error("✗ VALIDATION FAILED")
        log_error("=" * 60)

        if aws_marketplace_result['status'] == 'FAIL':
            log_error(f"\nAWS Marketplace Enablement [FAIL]")
            log_error(f"  - {aws_marketplace_result['message']}")

        if check_1['status'] == 'FAIL':
            log_error(f"\nCHECK #1: Resources Validation [FAIL]")
            log_error(f"Location: {mcc_sts_url}")
            log_error("")
            for error in check_1['errors']:
                log_error(f"{error}")
            log_error("")

        if check_2['status'] == 'FAIL':
            log_error(f"CHECK #2: Admin Acknowledgment [FAIL]")
            log_error(f"Location: {mcc_ack_url}")
            log_error("")
            for error in check_2['errors']:
                log_error(f"{error}")
            log_error("")

    report_data = {
        'type': 'AWS STS Policy Gap Analysis',
        'baseline': baseline,
        'target': target,
        'timestamp': datetime.now().isoformat(),
        'validation_result': validation_result,
        'validation_checked': validation_checked,
        'validation_details': validation_details,
        'aws_marketplace': aws_marketplace_result,
        'comparison': comparison,
        'summary': {
            'added': added_count,
            'removed': removed_count,
            'total_changes': total_changes
        }
    }

    # Always generate JSON report (needed for combined report)
    json_file = os.path.join(report_dir, f"gap-analysis-aws-sts_{baseline}_to_{target}{timestamp_suffix}.json")
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    # Skip HTML reports if GAP_FULL_REPORT is set (full report will include these)
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping HTML reports (full report will be generated)")
    else:
        # Generate HTML report
        html_file = os.path.join(report_dir, f"gap-analysis-aws-sts_{baseline}_to_{target}{timestamp_suffix}.html")
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    # Cleanup credential request directories
    import shutil
    shutil.rmtree(baseline_cr_dir, ignore_errors=True)
    shutil.rmtree(target_cr_dir, ignore_errors=True)

    # Generate status report for gap-all.sh
    if validation_result == 'FAIL':
        failed_checks = validation_details.get('failed_checks', [])
        status_message = f"{len(failed_checks)} validation failure(s)"
    else:
        if total_changes == 0:
            status_message = "0 differences found"
        else:
            status_message = f"{total_changes} difference(s) found"

    status_details = {
        "differences_count": total_changes,
        "added_count": added_count,
        "removed_count": removed_count,
        "validation_passed": validation_result == 'PASS',
        "validation_checked": validation_checked,
        "message": status_message
    }

    generate_status_report(
        check_number=1,
        check_name="AWS STS Policy Gap",
        status=validation_result,
        details=status_details,
        report_dir=report_dir,
    )

    # Exit based on validation result
    if validation_result == 'FAIL':
        log_error(f"\n❌ FAILED - Target version validation failed")
        sys.exit(1)
    else:
        log_success(f"\n✅ PASSED - Target version structure validated")
        sys.exit(0)


if __name__ == '__main__':
    main()
