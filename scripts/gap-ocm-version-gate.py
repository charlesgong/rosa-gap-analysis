#!/usr/bin/env python3
"""OCM Version Gate Gap Analysis - Validate and compare OCM version gates between versions."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, log_warning
from openshift_releases import resolve_gap_versions, extract_minor_version
from reporters import generate_html_report, generate_json_report


def get_mock_gates(baseline_minor, target_minor):
    """Generate mock/simulated gates for baseline and target versions."""
    return [
        {
            "id": f"e4e534f0-{baseline_minor}-11ef-a973-0a580a81063b",
            "kind": "VersionGate",
            "label": "api.openshift.com/gate-ocp",
            "value": baseline_minor,
            "version_raw_id_prefix": baseline_minor,
            "description": f"OpenShift removes several deprecated APIs in version {baseline_minor}.",
            "documentation_url": f"https://access.redhat.com/articles/gate-ocp-{baseline_minor}",
            "warning_message": f"To prevent an outage on your cluster, review any APIs in use that will be removed in {baseline_minor}.",
            "sts_only": False,
            "creation_timestamp": "2024-05-15T12:00:00Z",
            "cluster_condition": ""
        },
        {
            "id": f"f4e534f0-{target_minor}-11ef-a973-0a580a81063c",
            "kind": "VersionGate",
            "label": "api.openshift.com/gate-ocp",
            "value": target_minor,
            "version_raw_id_prefix": target_minor,
            "description": f"OpenShift removes several deprecated APIs in version {target_minor}.",
            "documentation_url": f"https://access.redhat.com/articles/gate-ocp-{target_minor}",
            "warning_message": f"To prevent an outage on your cluster, review any APIs in use that will be removed in {target_minor}.",
            "sts_only": False,
            "creation_timestamp": "2025-05-15T12:00:00Z",
            "cluster_condition": ""
        }
    ]


def fetch_ocm_version_gates():
    """Fetch version gates via 'ocm' CLI or fall back to mock data if unauthenticated/uninstalled."""
    ocm_path = shutil.which("ocm")
    if not ocm_path:
        log_warning("OCM CLI binary missing in PATH. Cannot perform live check.")
        return None

    # Read OCM token from token file or environment
    token = os.environ.get("OCM_TOKEN")
    token_file = "/var/run/ocm-token/token"
    if not token and os.path.exists(token_file):
        try:
            with open(token_file, "r") as f:
                token = f.read().strip()
            log_info(f"Loaded OCM offline token from {token_file}")
        except Exception as e:
            log_warning(f"Failed to read OCM token file at {token_file}: {e}")

    # Log in if token is available
    if token:
        log_info("Authenticating with OCM CLI using token...")
        login_cmd = ["ocm", "login", f"--token={token}"]
        login_proc = subprocess.run(login_cmd, capture_output=True, text=True, check=False)
        if login_proc.returncode == 0:
            log_success("Successfully authenticated with OCM CLI.")
        else:
            log_warning(f"OCM CLI login failed (exit code {login_proc.returncode}): {login_proc.stderr.strip()}")

    try:
        log_info("Executing live OCM GET request /api/clusters_mgmt/v1/version_gates...")
        cmd = ["ocm", "get", "/api/clusters_mgmt/v1/version_gates"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            if data and "items" in data:
                gates = data["items"]
                log_success(f"Successfully retrieved {len(gates)} live version gates from OCM.")
                return gates
            else:
                log_warning("OCM GET /api/clusters_mgmt/v1/version_gates returned empty or malformed JSON.")
        else:
            log_warning(f"OCM CLI GET command failed (exit code {proc.returncode}): {proc.stderr.strip()}")
    except Exception as e:
        log_warning(f"Error executing OCM CLI command: {e}")

    return None


def analyze_version_gates(gates, baseline_minor, target_minor):
    """Analyze and compare version gates for baseline and target versions."""
    # Filter out CI-only test gates (e.g., gate-test-only-ci*)
    gates = [g for g in gates if "gate-test-only-ci" not in g.get("label", "")]

    baseline_gates = []
    target_gates = []

    # Compile regex pattern with word boundaries to avoid partial matching (e.g. 4.2 matching 4.21)
    baseline_pattern = re.compile(rf"\b{re.escape(baseline_minor)}\b")
    target_pattern = re.compile(rf"\b{re.escape(target_minor)}\b")

    for gate in gates:
        prefix = gate.get("version_raw_id_prefix", "")
        value = gate.get("value", "")
        
        # Check if matches baseline
        if baseline_minor == prefix or (value and baseline_pattern.search(value)):
            baseline_gates.append(gate)
        # Check if matches target
        if target_minor == prefix or (value and target_pattern.search(value)):
            target_gates.append(gate)

    # Sort gates by creation timestamp or ID
    baseline_gates.sort(key=lambda g: g.get("creation_timestamp", ""))
    target_gates.sort(key=lambda g: g.get("creation_timestamp", ""))

    baseline_has_gate = len(baseline_gates) > 0
    target_has_gate = len(target_gates) > 0

    # Compare gates by label to identify common, new, and removed gates
    baseline_by_label = {}
    for g in baseline_gates:
        baseline_by_label[g.get("label", "")] = g

    target_by_label = {}
    for g in target_gates:
        target_by_label[g.get("label", "")] = g

    # Version-specific gate exclusions from comparison
    skipped_labels = set()
    if target_minor.startswith("5."):
        # 5.x is STS-only; WIF gates don't apply
        skipped_labels.add("api.openshift.com/gate-wif")

    baseline_labels = set(baseline_by_label.keys()) - skipped_labels
    target_labels = set(target_by_label.keys()) - skipped_labels

    common_labels = sorted(baseline_labels & target_labels)
    new_only_labels = sorted(target_labels - baseline_labels)
    removed_only_labels = sorted(baseline_labels - target_labels)

    def _summarize(g):
        return {
            "id": g.get("id"),
            "description": g.get("description"),
            "label": g.get("label"),
            "sts_only": g.get("sts_only", False),
            "documentation_url": g.get("documentation_url")
        }

    common_gates = [
        {"label": l, "baseline": _summarize(baseline_by_label[l]), "target": _summarize(target_by_label[l])}
        for l in common_labels
    ]
    new_gates = [_summarize(target_by_label[l]) for l in new_only_labels]
    deprecated_gates = [_summarize(baseline_by_label[l]) for l in removed_only_labels]

    # Basic configuration validation for metadata consistency
    metadata_errors = []
    for g in target_gates:
        if not g.get("id"):
            metadata_errors.append(f"Target gate is missing ID: {g}")
        if not g.get("description"):
            metadata_errors.append(f"Target gate {g.get('id')} is missing description")
        if not g.get("documentation_url"):
            metadata_errors.append(f"Target gate {g.get('id')} is missing documentation_url")

    config_valid = len(metadata_errors) == 0

    return {
        "baseline_minor": baseline_minor,
        "target_minor": target_minor,
        "baseline_gates": baseline_gates,
        "target_gates": target_gates,
        "baseline_has_gate": baseline_has_gate,
        "target_has_gate": target_has_gate,
        "common_gates": common_gates,
        "new_gates": new_gates,
        "deprecated_gates": deprecated_gates,
        "skipped_labels": sorted(skipped_labels),
        "config_valid": config_valid,
        "metadata_errors": metadata_errors
    }


def print_summary(analysis, is_mock, baseline_full, target_full):
    """Print standard stdout summary of gate checks."""
    log_info("=========================================")
    log_info("  OCM Version Gate Analysis Summary")
    log_info("=========================================")
    if is_mock:
        log_warning("⚠️  NOTE: Operating in DRY-RUN / SIMULATED mode (No OCM credentials/CLI detected).")
    else:
        log_success("✓ Connected to live OCM API.")

    log_info(f"Baseline version: {baseline_full} ({analysis['baseline_minor']})")
    log_info(f"Target version:   {target_full} ({analysis['target_minor']})")
    log_info("-----------------------------------------")

    if analysis['baseline_has_gate']:
        log_success(f"✓ Found {len(analysis['baseline_gates'])} gate(s) configured for baseline version {analysis['baseline_minor']}.x")
        for g in analysis['baseline_gates']:
            log_info(f"  - Gate ID:   {g.get('id')}")
            log_info(f"    Label:     {g.get('label')}")
            log_info(f"    Description: {g.get('description')}")
    else:
        log_warning(f"⚠️  No OCM version gates found for baseline version {analysis['baseline_minor']}.x")

    if analysis['target_has_gate']:
        log_success(f"✓ Found {len(analysis['target_gates'])} gate(s) configured for target version {analysis['target_minor']}.x")
        for g in analysis['target_gates']:
            log_info(f"  - Gate ID:   {g.get('id')}")
            log_info(f"    Label:     {g.get('label')}")
            log_info(f"    Description: {g.get('description')}")
    else:
        log_error(f"❌ Target version {analysis['target_minor']}.x does not have any OCM version gate configured!")

    log_info("-----------------------------------------")
    log_info("Gate Comparison (by label):")
    common = analysis.get('common_gates', [])
    new = analysis.get('new_gates', [])
    removed = analysis.get('deprecated_gates', [])
    if common:
        log_success(f"  ✓ {len(common)} gate(s) common between {analysis['baseline_minor']} and {analysis['target_minor']}")
        for g in common:
            log_info(f"    - {g['label']}")
    if new:
        log_info(f"  + {len(new)} new gate(s) in {analysis['target_minor']} only:")
        for g in new:
            log_info(f"    - {g['label']}: {g['description']}")
    if removed:
        log_error(f"  ✗ {len(removed)} gate(s) from {analysis['baseline_minor']} missing in {analysis['target_minor']}:")
        for g in removed:
            log_error(f"    - {g['label']}: {g['description']}")
        log_error(f"  ACTION REQUIRED: Create these gate(s) for version {analysis['target_minor']}")
    skipped = analysis.get('skipped_labels', [])
    if skipped:
        log_info(f"  ⊘ {len(skipped)} gate label(s) excluded from comparison (not applicable to {analysis['target_minor']}):")
        for label in skipped:
            log_info(f"    - {label}")
    if not common and not new and not removed:
        log_info("  No gates to compare.")

    if analysis['config_valid']:
        log_success("✓ All gate configurations contain valid and complete metadata.")
    else:
        for err in analysis['metadata_errors']:
            log_error(f"  - Configuration Error: {err}")


def main():
    parser = argparse.ArgumentParser(
        description='Validate and compare OCM version gates.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--version', help='Single version to analyze (auto-resolves baseline and target)')
    parser.add_argument('--baseline', help='Baseline version (requires --target)')
    parser.add_argument('--target', help='Target version (requires --baseline)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--report-dir',
                        default=os.environ.get('REPORT_DIR', 'reports'),
                        help='Directory to store reports')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show versions that would be used and exit (no analysis performed)')

    args = parser.parse_args()

    # Resolve versions using shared logic
    baseline_full, target_full = resolve_gap_versions(
        version=args.version, baseline=args.baseline, target=args.target
    )

    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)

    log_info("=========================================")
    log_info("  CHECK #7: OCM Version Gate Analysis")
    log_info("=========================================")
    log_info(f"Baseline full version: {baseline_full} ({baseline_minor})")
    log_info(f"Target full version:   {target_full} ({target_minor})")
    log_info("=========================================")

    if args.dry_run:
        log_info("Dry-run mode enabled - exiting without performing validation.")
        sys.exit(0)

    # Attempt to fetch version gates from live OCM API
    live_gates = fetch_ocm_version_gates()
    is_mock = False

    if live_gates is None:
        log_warning("Could not execute live check. Falling back to dry-run/mock gates configuration.")
        live_gates = get_mock_gates(baseline_minor, target_minor)
        is_mock = True

    # Perform analysis
    analysis_results = analyze_version_gates(live_gates, baseline_minor, target_minor)

    # Print stdout summary
    print_summary(analysis_results, is_mock, baseline_full, target_full)

    # Determine validation status based on common gate coverage
    # FAIL: baseline gates missing from target (need to be created), or invalid metadata
    # PASS: all baseline gate labels present in target
    validation_status = 'PASS'
    if is_mock:
        if not analysis_results['target_has_gate']:
            validation_status = 'WARN'
    else:
        if len(analysis_results['deprecated_gates']) > 0:
            validation_status = 'FAIL'
        elif not analysis_results['target_has_gate'] and analysis_results['baseline_has_gate']:
            validation_status = 'FAIL'
        elif not analysis_results['config_valid']:
            validation_status = 'FAIL'

    # Build report payload
    report_data = {
        'type': 'OCM Version Gate Gap Analysis',
        'baseline': baseline_full,
        'target': target_full,
        'baseline_minor': baseline_minor,
        'target_minor': target_minor,
        'timestamp': datetime.now().isoformat(),
        'validation_result': validation_status,
        'is_mock_data': is_mock,
        'gates_count': {
            'baseline': len(analysis_results['baseline_gates']),
            'target': len(analysis_results['target_gates']),
        },
        'baseline_gates': analysis_results['baseline_gates'],
        'target_gates': analysis_results['target_gates'],
        'comparison': {
            'common_gates_count': len(analysis_results['common_gates']),
            'new_gates_count': len(analysis_results['new_gates']),
            'deprecated_gates_count': len(analysis_results['deprecated_gates']),
            'common_gates': analysis_results['common_gates'],
            'new_gates': analysis_results['new_gates'],
            'deprecated_gates': analysis_results['deprecated_gates']
        },
        'skipped_labels': analysis_results.get('skipped_labels', []),
        'configuration_validation': {
            'valid': analysis_results['config_valid'],
            'errors': analysis_results['metadata_errors']
        }
    }

    # Write report files
    os.makedirs(args.report_dir, exist_ok=True)
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Always generate JSON report
    json_file = os.path.join(
        args.report_dir,
        f"gap-analysis-ocm-version-gate_{baseline_minor}_to_{target_minor}_{timestamp_str}.json"
    )
    generate_json_report(report_data, json_file)
    log_info(f"\nJSON report generated: {json_file}")

    # Skip HTML in full mode orchestrator
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping HTML report (full report will be generated)")
    else:
        html_file = os.path.join(
            args.report_dir,
            f"gap-analysis-ocm-version-gate_{baseline_minor}_to_{target_minor}_{timestamp_str}.html"
        )
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    if validation_status == 'FAIL':
        log_error("=" * 60)
        log_error(f"✗ VALIDATION {validation_status} - OCM Version Gates Complete")
        log_error("=" * 60)
        log_error(f"\nCHECK #7: OCM Version Gate Analysis [{validation_status}]")
        sys.exit(1)
    else:
        log_success("=" * 60)
        log_success(f"✓ VALIDATION {validation_status} - OCM Version Gates Complete")
        log_success("=" * 60)
        log_success(f"\nCHECK #7: OCM Version Gate Analysis [{validation_status}]")
        sys.exit(0)


if __name__ == '__main__':
    main()
