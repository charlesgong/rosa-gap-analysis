#!/usr/bin/env python3
"""Common utilities for gap analysis scripts."""

import shutil
import sys
from pathlib import Path
from urllib.request import urlopen, Request


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    RESET = '\033[0m'


def log_info(message):
    """Log an info message."""
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {message}", file=sys.stderr)


def log_success(message):
    """Log a success message."""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} {message}", file=sys.stderr)


def log_warning(message):
    """Log a warning message."""
    print(f"{Colors.YELLOW}[WARNING]{Colors.RESET} {message}", file=sys.stderr)


def log_error(message):
    """Log an error message."""
    print(f"{Colors.RED}[ERROR]{Colors.RESET} {message}", file=sys.stderr)


def check_command(command):
    """Check if a command is available in PATH."""
    if not shutil.which(command):
        log_error(f"{command} not found. Please install {command}.")
        sys.exit(1)


def get_project_root():
    """Get the project root directory."""
    # Script is in scripts/lib, so project root is two levels up
    return Path(__file__).parent.parent.parent.resolve()


def fetch_url(url, timeout=30):
    """
    Fetch content from URL with error handling.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Response data as bytes

    Raises:
        HTTPError: If HTTP request fails
        URLError: If connection fails
    """
    req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def is_pre_ga_version(version):
    """Check if a version string is pre-GA (alpha, beta, nightly)."""
    pre_ga_markers = ['-alpha.', '-beta.', '-nightly']
    return any(marker in version for marker in pre_ga_markers)


def is_version_5x(minor_version):
    """Check if minor version is 5.x or higher (AWS/STS-only, no GCP/WIF)."""
    try:
        return int(minor_version.split('.')[0]) >= 5
    except (ValueError, IndexError):
        return False


def check_yaml_installed():
    """Check if PyYAML is installed and exit if not."""
    try:
        import yaml
    except ImportError:
        log_error("PyYAML is not installed. Install it with: pip install pyyaml")
        sys.exit(1)
