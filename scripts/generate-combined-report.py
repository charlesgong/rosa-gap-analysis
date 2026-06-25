#!/usr/bin/env python3
"""Generate combined report from individual gap analysis JSON reports."""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from reporters import generate_html_report, generate_json_report
from common import log_info, log_success
from openshift_releases import extract_minor_version, get_next_minor_version


def parse_build_log(log_path):
    """Parse build log for metrics, status, infrastructure/build failures, and tracebacks."""
    metrics = {
        'duration': 'Unknown',
        'errors_count': 0,
        'warnings_count': 0,
        'status': 'SUCCESS',
        'failures': [],
        'retries': []
    }

    if not log_path or not os.path.exists(log_path):
        return metrics

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Clean ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_content = ansi_escape.sub('', content)
        lines = clean_content.splitlines()

        # 1. Parse duration
        duration_match = re.search(r'Ran for\s+(\w+)', clean_content)
        if duration_match:
            metrics['duration'] = duration_match.group(1)
        else:
            pod_match = re.search(r'failed after\s+(\w+)', clean_content)
            if pod_match:
                metrics['duration'] = pod_match.group(1)

        # 2. Count errors and warnings
        error_lines = [line for line in lines if any(x in line.upper() for x in ['ERROR', 'ERRO[', '❌ FAILED', 'CONTAINERFAILED'])]
        warning_lines = [line for line in lines if any(x in line.upper() for x in ['WARN', '⚠'])]

        metrics['errors_count'] = len(error_lines)
        metrics['warnings_count'] = len(warning_lines)

        # 3. Overall status
        if any(x in clean_content.upper() for x in ['❌ FAILED', 'SOME STEPS FAILED', 'CONTAINERFAILED']):
            metrics['status'] = 'FAILED'

        # 4. Extract infrastructure/build failures
        build_fail_matches = re.findall(r'Build\s+(\S+)\s+failed', clean_content)
        for component in set(build_fail_matches):
            metrics['failures'].append({
                'type': 'Build Failure',
                'component': component,
                'detail': f"Build of image '{component}' failed during the run."
            })

        # 5. Extract retry events
        retry_matches = re.findall(r'(\S+)\s+previously failed.*retrying', clean_content)
        for component in set(retry_matches):
            metrics['retries'].append({
                'component': component,
                'detail': f"Build previously failed, retrying component."
            })

        # 6. Extract test script traceback if any
        if 'Traceback (most recent call last):' in clean_content:
            tb_index = clean_content.find('Traceback (most recent call last):')
            tb_part = clean_content[tb_index:]
            tb_lines = tb_part.splitlines()[:15]
            traceback_text = '\n'.join(tb_lines)
            metrics['failures'].append({
                'type': 'Script Exception',
                'component': 'Test Validation Step',
                'detail': traceback_text
            })

        # 7. Extract specific failed pod details
        pod_fail_match = re.search(r'pod\s+(\S+)\s+failed after\s+(\S+)\s+\(([^)]+)\)', clean_content)
        if pod_fail_match:
            metrics['failures'].append({
                'type': 'Pod Failure',
                'component': pod_fail_match.group(1),
                'detail': f"Pod failed after {pod_fail_match.group(2)}. Failed containers: {pod_fail_match.group(3)}"
            })

    except Exception as e:
        print(f"Error parsing build log: {e}")

    return metrics


def find_latest_reports(baseline, target, report_dir='reports'):
    """Find the latest JSON reports for each analysis type."""
    reports = {
        'aws_sts': None,
        'gcp_wif': None,
        'feature_gates': None,
        'ocp_gate_ack': None,
        'ocm_version_gate': None
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

    # Find OCM Version Gate report (uses minor versions)
    ovg_pattern = os.path.join(report_dir, f"gap-analysis-ocm-version-gate_{baseline_minor}_to_{target_minor}_*.json")
    ovg_files = sorted(glob.glob(ovg_pattern))
    if ovg_files:
        reports['ocm_version_gate'] = ovg_files[-1]  # Latest

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
    parser.add_argument('--build-log', help='Path to the build log file to parse metrics and failures')

    args = parser.parse_args()

    # Create report directory if it doesn't exist
    os.makedirs(args.report_dir, exist_ok=True)

    # Find latest reports
    reports = find_latest_reports(args.baseline, args.target, args.report_dir)

    # Determine build log path
    build_log_path = args.build_log or os.environ.get('BUILD_LOG')
    if not build_log_path:
        # Check standard candidate paths
        candidates = [
            os.path.join(args.report_dir, 'build-log.txt'),
            os.path.join(args.report_dir, '../tmp-prow-logs/build-log.txt'),
            os.path.join(args.report_dir, '../reports/build-log.txt'),
            os.path.join(os.path.dirname(args.report_dir), 'reports/build-log.txt'),
            os.path.join(os.path.dirname(args.report_dir), 'tmp-prow-logs/build-log.txt'),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                build_log_path = candidate
                break

    # Parse build log if found
    build_metrics = None
    if build_log_path and os.path.exists(build_log_path):
        log_info(f"Parsing build log: {build_log_path}")
        build_metrics = parse_build_log(build_log_path)
    else:
        log_info("No build log file found/specified. Skipping build log metrics.")

    # Load report data
    report_data = {
        'type': 'Full Gap Analysis',
        'baseline': args.baseline,
        'target': args.target,
        'timestamp': datetime.now().isoformat(),
        'build_metrics': build_metrics
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

    # Load OCM Version Gate data
    if reports['ocm_version_gate']:
        with open(reports['ocm_version_gate'], 'r') as f:
            report_data['ocm_version_gate'] = json.load(f)
        log_info(f"Loaded OCM Version Gate report: {reports['ocm_version_gate']}")



    # Generate combined reports
    timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Generate HTML report
    html_file = os.path.join(args.report_dir, f"gap-analysis-full_{args.baseline}_to_{args.target}{timestamp_suffix}.html")
    generate_html_report(report_data, html_file)
    log_success(f"Combined HTML report generated: {html_file}")

    # Generate JSON report
    json_file = os.path.join(args.report_dir, f"gap-analysis-full_{args.baseline}_to_{args.target}{timestamp_suffix}.json")
    generate_json_report(report_data, json_file)
    log_success(f"Combined JSON report generated: {json_file}")


if __name__ == '__main__':
    main()
