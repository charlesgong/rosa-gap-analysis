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
    elif 'Version Channel' in report_type:
        template = jinja_env.get_template('versions-channels.html.j2')
    elif 'OCP Admin Gate' in report_type or 'Gate Acknowledgment' in report_type:
        template = jinja_env.get_template('ocp-gate-ack.html.j2')
    elif 'Full Gap Analysis' in report_type:
        template = jinja_env.get_template('full-gap.html.j2')
    elif 'Aggregate Gap Analysis' in report_type:
        template = jinja_env.get_template('aggregate-report.html.j2')
    else:
        # Fallback to a generic template (use aws-sts as base)
        template = jinja_env.get_template('aws-sts.html.j2')

    # Render template
    html = template.render(**data)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(html)

    return html
