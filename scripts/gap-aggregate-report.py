#!/usr/bin/env python3
"""Generate executive aggregated gap analysis report."""

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
from common import log_info, log_success, log_warning, log_error
from openshift_releases import extract_minor_version, get_next_minor_version

def find_latest_reports(baseline, target, report_dir='reports'):
    """Find the latest JSON reports for each analysis type."""
    reports = {
        'aws_sts': None,
        'gcp_wif': None,
        'feature_gates': None,
        'ocp_gate_ack': None,
        'full': None
    }

    def get_latest(pattern):
        files = sorted(glob.glob(pattern))
        return files[-1] if files else None

    # AWS STS
    reports['aws_sts'] = get_latest(os.path.join(report_dir, f"gap-analysis-aws-sts_{baseline}_to_{target}_*.json"))
    # GCP WIF
    reports['gcp_wif'] = get_latest(os.path.join(report_dir, f"gap-analysis-gcp-wif_{baseline}_to_{target}_*.json"))
    
    # Full report
    reports['full'] = get_latest(os.path.join(report_dir, f"gap-analysis-full_{baseline}_to_{target}_*.json"))

    # Feature Gates (uses minor versions)
    baseline_minor = extract_minor_version(baseline)
    target_minor = extract_minor_version(target)
    reports['feature_gates'] = get_latest(os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline_minor}_to_{target_minor}_*.json"))

    # OCP Gate Acknowledgment
    oga_pattern1 = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{target_minor}_*.json")
    oga_files = glob.glob(oga_pattern1)
    if baseline_minor == target_minor:
        next_minor = get_next_minor_version(baseline_minor)
        oga_pattern2 = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{next_minor}_*.json")
        oga_files.extend(glob.glob(oga_pattern2))
    
    if oga_files:
        reports['ocp_gate_ack'] = sorted(oga_files)[-1]

    return reports

def parse_build_log(log_path):
    """Extract metrics and errors from build log."""
    metrics = {'errors': 0, 'warnings': 0, 'duration': 'Unknown'}
    if not log_path or not os.path.exists(log_path):
        return metrics

    try:
        with open(log_path, 'r') as f:
            for line in f:
                # Precise error/warning counting using word boundaries to prevent false positives
                metrics['errors'] += len(re.findall(r'\b(ERROR|FAILED)\b|❌', line, re.IGNORECASE))
                metrics['warnings'] += len(re.findall(r'\bWARNING\b|⚠️', line, re.IGNORECASE))
                
                # Try to find duration
                duration_match = re.search(r'Finished in ([\d\w\s]+)', line)
                if duration_match:
                    metrics['duration'] = duration_match.group(1)
    except Exception as e:
        log_warning(f"Failed to parse build log: {e}")

    return metrics

def get_ai_insights(report_data):
    """Generate AI insights using Anthropic API."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        summary = {
            'baseline': report_data['baseline'],
            'target': report_data['target'],
            'checks': {k: v['status'] for k, v in report_data['checks'].items()}
        }
        
        prompt = f"""You are a senior OpenShift SRE analyzing a Gap Analysis report between versions {summary['baseline']} and {summary['target']}.
        Results of checks: {json.dumps(summary['checks'], indent=2)}
        
        Provide a concise executive summary (max 3 paragraphs). 
        Identify the most critical risks (if any) and provide 2-3 actionable recommendations.
        Format the output in HTML (use <h3> for headers, <p> for paragraphs, <ul>/<li> for lists).
        Do not include any conversational filler."""

        log_info("Requesting AI insights from Anthropic...")
        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        if hasattr(message.content[0], 'text'):
            return message.content[0].text
        return str(message.content)

    except Exception as e:
        log_info(f"AI insights skipped due to error: {e}")
        pass
    
    return None

def print_ascii_summary(data, report_dir):
    """Print a text-based summary to stdout for the build log."""
    print("\n" + "="*80)
    print("GAP ANALYSIS SUMMARY")
    print("="*80)
    print(f"Job:       {os.environ.get('JOB_NAME', 'local-run')}")
    print(f"Run:       {os.environ.get('BUILD_ID', 'N/A')}")
    print(f"Baseline:  {data['baseline']}")
    print(f"Target:    {data['target']}")
    print(f"Timestamp: {data['timestamp']}")
    print(f"Duration:  {data.get('build_metrics', {}).get('duration', 'Unknown')}")
    print("-" * 40)
    print("RESULTS:")
    
    check_order = [
        ('AWS STS Policies', 'aws_sts'),
        ('GCP WIF Policies', 'gcp_wif'),
        ('OCP Admin Gates', 'ocp_gate_ack'),
        ('Feature Gates', 'feature_gates')
    ]

    for i, (label, key) in enumerate(check_order, 1):
        check = data['checks'].get(label, {'status': 'SKIPPED', 'summary': ''})
        icon = "[✓]"
        if check['status'] == 'FAIL':
            icon = "[✗]"
        elif check['status'] in ['WARNING', 'ERROR']:
            icon = "[⚠]"
        elif check['status'] in ['INFO', 'SKIPPED']:
            icon = "[ℹ]"
            
        print(f"{icon} CHECK #{i}: {label:25} - {check['status']:8} ({check['summary']})")
    
    print("-" * 40)
    status_label = "SUCCESS" if data['overall_status'] == 'PASS' else "FAILURE"
    print(f"OVERALL STATUS: {status_label}")
    print("-" * 40)
    print("ARTIFACTS:")
    print(f"- Reports: {report_dir}/")
    print(f"- Aggregated: {os.path.join(report_dir, 'aggregate-summary.html')}")
    print("="*80 + "\n")

def main():
    parser = argparse.ArgumentParser(description='Generate aggregated executive gap analysis report.')
    parser.add_argument('--baseline', required=True, help='Baseline version')
    parser.add_argument('--target', required=True, help='Target version')
    parser.add_argument('--report-dir', default='reports', help='Directory containing JSON reports')
    parser.add_argument('--build-log', help='Path to build-log.txt')
    
    args = parser.parse_args()
    
    reports = find_latest_reports(args.baseline, args.target, args.report_dir)
    
    # Aggregate data
    agg_data = {
        'type': 'Aggregate Gap Analysis',
        'baseline': args.baseline,
        'target': args.target,
        'timestamp': datetime.now().isoformat(),
        'checks': {},
        'reports': {},
        'overall_status': 'PASS'
    }

    # Map reports to links (relative to report-dir)
    for key, path in reports.items():
        if path:
            agg_data['reports'][key] = os.path.basename(path).replace('.json', '.html')

    # Process individual check results
    check_map = {
        'aws_sts': 'AWS STS Policies',
        'gcp_wif': 'GCP WIF Policies',
        'ocp_gate_ack': 'OCP Admin Gates',
        'feature_gates': 'Feature Gates'
    }

    for key, label in check_map.items():
        status = 'SKIPPED'
        summary = ''
        
        if reports[key]:
            try:
                with open(reports[key], 'r') as f:
                    data = json.load(f)
                    status = data.get('validation_result', 'INFO')
                    if status == 'FAIL':
                        agg_data['overall_status'] = 'FAIL'
                    
                    # Extract a brief summary based on report type
                    if key == 'aws_sts':
                        summary = f"{len(data.get('comparison', {}).get('actions', {}).get('target_only', []))} added, {len(data.get('comparison', {}).get('actions', {}).get('baseline_only', []))} removed"
                    elif key == 'gcp_wif':
                        summary = f"{len(data.get('comparison', {}).get('actions', {}).get('target_only', []))} added, {len(data.get('comparison', {}).get('actions', {}).get('baseline_only', []))} removed"
                    elif key == 'ocp_gate_ack':
                        summary = f"{data.get('summary', {}).get('unacknowledged', 0)} unacknowledged gates"
                    elif key == 'feature_gates':
                        # Feature gates always pass as informational
                        status = 'PASS'
                        c = data.get('comparison', {})
                        change_count = len(c.get('added', [])) + len(c.get('removed', [])) + len(c.get('newly_enabled_by_default', []))
                        summary = f"{change_count} changes detected"
            except Exception as e:
                log_warning(f"Error reading {key} report: {e}")
        
        agg_data['checks'][label] = {'status': status, 'summary': summary}

    # Parse build log
    agg_data['build_metrics'] = parse_build_log(args.build_log)

    # Get AI Insights
    agg_data['ai_insights'] = get_ai_insights(agg_data)

    # Print ASCII summary to console (SREP-4306)
    print_ascii_summary(agg_data, args.report_dir)

    # Generate Reports
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    html_file = os.path.join(args.report_dir, f"gap-analysis-summary_{args.baseline}_to_{args.target}_{timestamp}.html")
    generate_html_report(agg_data, html_file)
    # Also create a symlink or a fixed name for index.html if in CI
    index_file = os.path.join(args.report_dir, "aggregate-summary.html")
    generate_html_report(agg_data, index_file)
    
    json_file = os.path.join(args.report_dir, f"gap-analysis-summary_{args.baseline}_to_{args.target}_{timestamp}.json")
    generate_json_report(agg_data, json_file)
    
    log_success(f"Aggregated HTML report generated: {html_file}")

if __name__ == '__main__':
    main()
