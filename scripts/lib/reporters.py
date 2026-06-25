#!/usr/bin/env python3
"""Report generation utilities for gap analysis using Jinja2 templates."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Get templates directory
TEMPLATE_DIR = Path(__file__).parent.parent / 'templates'

# Initialize Jinja2 environment
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(['html', 'xml']),
    trim_blocks=True,
    lstrip_blocks=True
)


def generate_json_report(data: Dict[str, Any], output_file: str = None) -> str:
    """Generate JSON report from gap analysis data."""
    report = json.dumps(data, indent=2, sort_keys=True)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(report)

    return report


def generate_status_report(check_number: int, check_name: str, status: str,
                          details: Dict[str, Any], report_dir: str, add_timestamp: bool = True) -> None:
    """
    Generate a structured status file for gap-all.sh to consume.

    Args:
        check_number: Numeric check identifier (1-6)
        check_name: Human-readable check name
        status: PASS, FAIL, WARNING, ERROR, SKIP
        details: Dictionary containing check-specific details
        report_dir: Directory to write status file
        add_timestamp: Always True, timestamp is always added to filename
    """
    status_data = {
        "check_number": check_number,
        "check_name": check_name,
        "status": status,
        "exit_code": 0 if status in ["PASS", "WARNING", "SKIP"] else 1,
        "details": details
    }

    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)

    status_file = report_path / f"status-check-{check_number}.json"
    with open(status_file, 'w') as f:
        json.dump(status_data, f, indent=2)


def generate_html_report(data: Dict[str, Any], output_file: str = None) -> str:
    """Generate HTML report from gap analysis data using Jinja2 templates."""
    report_type = data.get('type', 'Gap Analysis')

    # Select template based on report type
    if 'AWS STS' in report_type:
        template = jinja_env.get_template('aws-sts.html.j2')
    elif 'GCP WIF' in report_type:
        template = jinja_env.get_template('gcp-wif.html.j2')
    elif 'Feature Gate' in report_type:
        template = jinja_env.get_template('feature-gates.html.j2')
    elif 'OCP Admin Gate' in report_type or 'Gate Acknowledgment' in report_type:
        template = jinja_env.get_template('ocp-gate-ack.html.j2')
    elif 'OCM Version Gate' in report_type:
        template = jinja_env.get_template('ocm-version-gate.html.j2')
    elif 'Full Gap Analysis' in report_type:
        template = jinja_env.get_template('full-gap.html.j2')
    else:
        # Fallback to a generic template (use aws-sts as base)
        template = jinja_env.get_template('aws-sts.html.j2')

    # Render template
    html = template.render(**data)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(html)

    return html
