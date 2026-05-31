#!/usr/bin/env python3
"""Generate combined report from individual gap analysis JSON reports."""

import argparse
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from reporters import generate_html_report, generate_json_report
from common import log_info, log_success
from openshift_releases import extract_minor_version, get_next_minor_version


def find_latest_reports(baseline, target, report_dir='reports'):
    """Find the latest JSON reports for each analysis type."""
    reports = {
        'aws_sts': None,
        'gcp_wif': None,
        'feature_gates': None,
        'ocp_gate_ack': None,
        'versions_channels': None
    }

    # Find AWS STS report
    aws_pattern = os.path.join(report_dir, f"gap-analysis-aws-sts_{baseline}_to_{target}_*.json")
    aws_files = sorted(glob.glob(aws_pattern))
    if aws_files:
        reports['aws_sts'] = aws_files[-1]  # Latest

    # Find GCP WIF report
    gcp_pattern = os.path.join(report_dir, f"gap-analysis-gcp-wif_{baseline}_to_{target}_*.json")
    gcp_files = sorted(glob.glob(gcp_pattern))
    if gcp_files:
        reports['gcp_wif'] = gcp_files[-1]  # Latest

    # Find Feature Gates report (uses minor versions)
    baseline_minor = extract_minor_version(baseline)
    target_minor = extract_minor_version(target)
    fg_pattern = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline_minor}_to_{target_minor}_*.json")
    fg_files = sorted(glob.glob(fg_pattern))
    if fg_files:
        reports['feature_gates'] = fg_files[-1]  # Latest

    # Find OCP Gate Acknowledgment report (uses minor versions)
    # For z-stream upgrades, OCP gate ack uses next minor version for ack_check_version
    # Try both patterns and pick the latest by timestamp
    oga_files = []

    # Pattern 1: standard (baseline_to_target)
    oga_pattern1 = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{target_minor}_*.json")
    oga_files.extend(glob.glob(oga_pattern1))

    # Pattern 2: z-stream (baseline_to_next) - only for z-stream upgrades
    if baseline_minor == target_minor:
        next_minor = get_next_minor_version(baseline_minor)
        oga_pattern2 = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{next_minor}_*.json")
        oga_files.extend(glob.glob(oga_pattern2))

    # Sort all found files and pick the latest
    if oga_files:
        reports['ocp_gate_ack'] = sorted(oga_files)[-1]  # Latest by filename (timestamp)

    # Find Versions & Channels report (uses minor versions)
    vc_pattern = os.path.join(report_dir, f"gap-analysis-versions-channels_{baseline_minor}_to_{target_minor}_*.json")
    vc_files = sorted(glob.glob(vc_pattern))
    if vc_files:
        reports['versions_channels'] = vc_files[-1]  # Latest

    return reports


def main():
    parser = argparse.ArgumentParser(
        description='Generate combined gap analysis report from individual reports.'
    )
    parser.add_argument('--baseline', required=True, help='Baseline version')
    parser.add_argument('--target', required=True, help='Target version')
    parser.add_argument('--report-dir',
                       default=os.environ.get('REPORT_DIR', 'reports'),
                       help='Directory to store reports (default: reports/, env: REPORT_DIR)')

    args = parser.parse_args()

    # Create report directory if it doesn't exist
    os.makedirs(args.report_dir, exist_ok=True)

    # Find latest reports
    reports = find_latest_reports(args.baseline, args.target, args.report_dir)

    # Load report data
    report_data = {
        'type': 'Full Gap Analysis',
        'baseline': args.baseline,
        'target': args.target,
        'timestamp': datetime.now().isoformat()
    }

    # Load AWS STS data
    if reports['aws_sts']:
        with open(reports['aws_sts'], 'r') as f:
            report_data['aws_sts'] = json.load(f)
        log_info(f"Loaded AWS STS report: {reports['aws_sts']}")

    # Load GCP WIF data
    if reports['gcp_wif']:
        with open(reports['gcp_wif'], 'r') as f:
            report_data['gcp_wif'] = json.load(f)
        log_info(f"Loaded GCP WIF report: {reports['gcp_wif']}")

    # Load Feature Gates data
    if reports['feature_gates']:
        with open(reports['feature_gates'], 'r') as f:
            report_data['feature_gates'] = json.load(f)
        log_info(f"Loaded Feature Gates report: {reports['feature_gates']}")

    # Load OCP Gate Acknowledgment data
    if reports['ocp_gate_ack']:
        with open(reports['ocp_gate_ack'], 'r') as f:
            report_data['ocp_gate_ack'] = json.load(f)
        log_info(f"Loaded OCP Gate Acknowledgment report: {reports['ocp_gate_ack']}")

    # Load Versions & Channels data
    if reports['versions_channels']:
        with open(reports['versions_channels'], 'r') as f:
            report_data['versions_channels'] = json.load(f)
        log_info(f"Loaded Versions & Channels report: {reports['versions_channels']}")

    # Generate combined reports
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Generate HTML report
    html_file = os.path.join(args.report_dir, f"gap-analysis-full_{args.baseline}_to_{args.target}_{timestamp}.html")
    generate_html_report(report_data, html_file)
    log_success(f"Combined HTML report generated: {html_file}")

    # Generate JSON report
    json_file = os.path.join(args.report_dir, f"gap-analysis-full_{args.baseline}_to_{args.target}_{timestamp}.json")
    generate_json_report(report_data, json_file)
    log_success(f"Combined JSON report generated: {json_file}")


if __name__ == '__main__':
    main()
