#!/usr/bin/env python3
"""OpenShift release version utilities using release streams API."""

import json
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError

from common import log_info, log_error


SIPPY_API = "https://sippy.dptools.openshift.org/api/releases"
ACCEPTED_STREAMS_API = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted"
STABLE_STREAM = "4-stable"
DEV_PREVIEW_STREAM = "4-dev-preview"


def fetch_sippy_ga_dates():
    """Fetch GA dates from Sippy API."""
    try:
        req = Request(SIPPY_API, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=10) as response:
            data = response.read()
            return json.loads(data).get('ga_dates', {})
    except (URLError, json.JSONDecodeError) as e:
        log_error(f"Failed to fetch GA dates from Sippy API: {e}")
        sys.exit(1)


def is_ga_minor_version(minor_version, ga_dates=None):
    """Check if a minor version is GA according to Sippy API."""
    if ga_dates is None:
        ga_dates = fetch_sippy_ga_dates()
    return minor_version in ga_dates


def get_latest_ga_version():
    """Get the latest GA version from Sippy API."""
    ga_dates = fetch_sippy_ga_dates()
    if not ga_dates:
        log_error("No GA versions found in Sippy API")
        sys.exit(1)

    # Sort versions and get the latest
    versions = sorted(ga_dates.keys(), key=lambda v: list(map(int, v.split('.'))))
    return versions[-1]


def fetch_accepted_streams():
    """
    Fetch all accepted release streams in a single API call.

    Returns:
        dict: {"4-stable": ["4.22.0-rc.0", "4.21.11", ...], "4-dev-preview": [...]}
    """
    try:
        req = Request(ACCEPTED_STREAMS_API, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except (URLError, json.JSONDecodeError) as e:
        log_error(f"Failed to fetch accepted release streams: {e}")
        sys.exit(1)


def get_latest_stable_version(ga_version=None):
    """
    Get the latest stable OpenShift version from accepted streams, filtered by GA version line.

    Args:
        ga_version: GA version line to filter by (e.g., "4.21"). If None, auto-detects from Sippy.

    Returns:
        Latest stable version matching the GA line (e.g., "4.21.11")
    """
    if ga_version is None:
        ga_version = get_latest_ga_version()

    # Fetch accepted streams (single API call)
    streams = fetch_accepted_streams()
    stable_versions = streams.get(STABLE_STREAM, [])

    if not stable_versions:
        log_error(f"No versions found in {STABLE_STREAM} accepted stream")
        sys.exit(1)

    # Filter to match GA version line (e.g., 4.21.x)
    # Versions are already sorted newest first in the accepted API
    matching_versions = [v for v in stable_versions if v.startswith(f"{ga_version}.")]

    if not matching_versions:
        log_error(f"No stable versions found matching GA version line {ga_version}.x")
        sys.exit(1)

    return matching_versions[0]


def get_latest_candidate_version(dev_version=None):
    """
    Get the latest candidate OpenShift version using dual-source priority from accepted streams.

    Priority 1: Check {major}-stable for RC version (e.g., 4.22.0-rc.*, 5.0.0-rc.*)
    Priority 2: Fall back to {major}-dev-preview for EC version (e.g., 4.22.0-ec.*, 5.0.0-ec.*)

    Args:
        dev_version: Dev version line to search for (e.g., "4.22", "5.0"). If None, auto-calculates from GA+1.

    Returns:
        Latest candidate version (RC from stable or EC from dev-preview)
    """
    if dev_version is None:
        ga_version = get_latest_ga_version()
        parts = ga_version.split('.')
        dev_minor = int(parts[1]) + 1
        dev_version = f"{parts[0]}.{dev_minor}"

    major = dev_version.split('.')[0]
    stable_stream = f"{major}-stable"
    dev_preview_stream = f"{major}-dev-preview"

    # Fetch accepted streams (single API call)
    streams = fetch_accepted_streams()

    # Priority 1: Check {major}-stable for RC version (e.g., 5.0.0-rc.*)
    stable_versions = streams.get(stable_stream, []) or []
    rc_versions = [v for v in stable_versions if v.startswith(f"{dev_version}.0-rc.")]

    if rc_versions:
        return rc_versions[0]

    # Priority 2: Check {major}-dev-preview for EC version (e.g., 5.0.0-ec.*)
    dev_versions = streams.get(dev_preview_stream, []) or []
    ec_versions = [v for v in dev_versions if v.startswith(f"{dev_version}.0-ec.")]

    if ec_versions:
        return ec_versions[0]

    # No RC or EC found
    log_error(f"No candidate version found for {dev_version} "
              f"(checked RC in {stable_stream} and EC in {dev_preview_stream})")
    sys.exit(1)


def get_latest_dev_nightly_version():
    """Get the latest dev nightly OpenShift version."""
    # Get the latest GA version
    ga_version = get_latest_ga_version()

    # Calculate dev version (GA + 1)
    parts = ga_version.split('.')
    dev_minor = int(parts[1]) + 1
    dev_version = f"{parts[0]}.{dev_minor}"

    try:
        url = f"{RELEASE_STREAM_BASE}/{dev_version}.0-0.nightly/latest?rel=1"
        req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            nightly_name = data.get('name')
            if not nightly_name:
                log_error(f"No nightly version found for {dev_version}")
                sys.exit(1)
            return nightly_name
    except (URLError, json.JSONDecodeError, KeyError) as e:
        log_error(f"Failed to fetch latest nightly version: {e}")
        sys.exit(1)


def extract_minor_version(version_string):
    """Extract minor version (e.g., '4.21' from '4.21.5')."""
    parts = version_string.split('.')
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return version_string


def get_next_minor_version(version_string):
    """
    Get next minor version (e.g., '4.19' → '4.20', '4.21' → '4.22').

    Args:
        version_string: Version string (e.g., '4.19', '4.19.30', '4.21.5')

    Returns:
        str: Next minor version (e.g., '4.20')
    """
    minor = extract_minor_version(version_string)
    parts = minor.split('.')
    if len(parts) >= 2:
        next_minor_num = int(parts[1]) + 1
        return f"{parts[0]}.{next_minor_num}"
    return version_string


def get_all_minor_versions_from_accepted_streams():
    """
    Get all unique minor versions from accepted streams, sorted.

    Returns:
        list: Sorted list of minor versions (e.g., ['4.18', '4.19', '4.20', '4.21', '4.22', '4.23', '5.0'])
    """
    streams = fetch_accepted_streams()

    # Extract all versions from ALL streams (not just 4-stable and 4-dev-preview)
    # This includes 5-stable, 5-dev-preview, and version-specific nightly/CI streams
    all_versions = []
    for stream_name, versions in streams.items():
        if versions and isinstance(versions, list):
            all_versions.extend(versions)

    # Extract minor versions and deduplicate
    minor_versions = set()
    for version in all_versions:
        minor = extract_minor_version(version)
        minor_versions.add(minor)

    # Sort versions properly (by numeric comparison)
    sorted_versions = sorted(minor_versions, key=lambda v: list(map(int, v.split('.'))))

    return sorted_versions


def get_previous_z_stream_version(minor_version):
    """
    Get the previous z-stream version for a given minor version.

    Args:
        minor_version: Minor version to get previous z-stream for (e.g., "4.21")

    Returns:
        str: Previous z-stream version (e.g., "4.21.10" if latest is "4.21.11")
        None: If only one z-stream version available

    Raises:
        SystemExit: If no stable versions found for the minor version line
    """
    streams = fetch_accepted_streams()
    stable_versions = streams.get(STABLE_STREAM, [])

    # Filter to versions matching this minor version line
    matching_versions = [v for v in stable_versions if v.startswith(f"{minor_version}.")]

    if not matching_versions:
        log_error(f"No stable versions found for {minor_version}.x")
        sys.exit(1)

    # Check if we have at least 2 versions
    if len(matching_versions) < 2:
        log_info(f"Only one z-stream version available for {minor_version}, skipping gap analysis")
        return None

    # Return the second version (previous z-stream)
    # Versions are already sorted newest first in accepted API
    return matching_versions[1]


def get_latest_version_baseline_priority(minor_version):
    """
    Get the latest version for baseline.
    Precedence: stable > candidate (RC/EC) > CI > nightly

    Args:
        minor_version: Minor version line to search for (e.g., "4.22", "5.0")

    Returns:
        str: Latest version using baseline precedence

    Raises:
        SystemExit: If no version found for the minor version line
    """
    streams = fetch_accepted_streams()

    # Extract major version from minor_version (4.22 → 4, 5.0 → 5)
    major_version = minor_version.split('.')[0]
    stable_stream = f"{major_version}-stable"
    dev_preview_stream = f"{major_version}-dev-preview"
    nightly_stream = f"{minor_version}.0-0.nightly"
    ci_stream = f"{minor_version}.0-0.ci"

    # Get versions from streams
    stable_versions = streams.get(stable_stream, []) or []
    dev_versions = streams.get(dev_preview_stream, []) or []
    nightly_versions = streams.get(nightly_stream, []) or []
    ci_versions = streams.get(ci_stream, []) or []

    # Priority 1: Stable version (e.g., 4.22.5, 5.0.5)
    stable_matches = [v for v in stable_versions
                     if v.startswith(f"{minor_version}.")
                     and '-rc.' not in v and '-ec.' not in v]
    if stable_matches:
        return stable_matches[0]

    # Priority 2: RC from X-stable
    rc_versions = [v for v in stable_versions if v.startswith(f"{minor_version}.0-rc.")]
    if rc_versions:
        return rc_versions[0]

    # Priority 3: EC from X-dev-preview
    ec_versions = [v for v in dev_versions if v.startswith(f"{minor_version}.0-ec.")]
    if ec_versions:
        return ec_versions[0]

    # Priority 4: CI from X.Y.0-0.ci
    if ci_versions:
        return ci_versions[0]

    # Priority 5: Nightly from X.Y.0-0.nightly
    if nightly_versions:
        return nightly_versions[0]

    log_error(f"No version found for {minor_version} (checked stable, RC, EC, CI, nightly)")
    sys.exit(1)


def get_latest_version_target_priority(minor_version):
    """
    Get the latest version for target.
    Precedence: candidate (RC/EC) > CI > nightly

    Args:
        minor_version: Minor version line to search for (e.g., "4.22", "5.0")

    Returns:
        str: Latest version using target precedence

    Raises:
        SystemExit: If no version found for the minor version line
    """
    streams = fetch_accepted_streams()

    # Extract major version from minor_version (4.22 → 4, 5.0 → 5)
    major_version = minor_version.split('.')[0]
    stable_stream = f"{major_version}-stable"
    dev_preview_stream = f"{major_version}-dev-preview"
    nightly_stream = f"{minor_version}.0-0.nightly"
    ci_stream = f"{minor_version}.0-0.ci"

    # Get versions from streams
    stable_versions = streams.get(stable_stream, []) or []
    dev_versions = streams.get(dev_preview_stream, []) or []
    nightly_versions = streams.get(nightly_stream, []) or []
    ci_versions = streams.get(ci_stream, []) or []

    # Priority 1: RC from X-stable
    rc_versions = [v for v in stable_versions if v.startswith(f"{minor_version}.0-rc.")]
    if rc_versions:
        return rc_versions[0]

    # Priority 2: EC from X-dev-preview
    ec_versions = [v for v in dev_versions if v.startswith(f"{minor_version}.0-ec.")]
    if ec_versions:
        return ec_versions[0]

    # Priority 3: CI from X.Y.0-0.ci
    if ci_versions:
        return ci_versions[0]

    # Priority 4: Nightly from X.Y.0-0.nightly
    if nightly_versions:
        return nightly_versions[0]

    log_error(f"No version found for {minor_version} (checked candidate, CI, nightly)")
    sys.exit(1)


def get_latest_version_for_line(minor_version):
    """
    Get the latest version for a given minor version line.
    Uses baseline precedence (stable > candidate > CI > nightly).

    This function is kept for backward compatibility.
    For baseline/target resolution, use get_latest_version_baseline_priority()
    or get_latest_version_target_priority() directly.

    Args:
        minor_version: Minor version line to search for (e.g., "4.22", "5.0")

    Returns:
        str: Latest version using baseline precedence

    Raises:
        SystemExit: If no version found for the minor version line
    """
    return get_latest_version_baseline_priority(minor_version)


def get_special_baseline_mapping(target_version):
    """
    Get special baseline version mapping for major version transitions.

    OpenShift upgrade path mapping:
    - 4.19 → 4.20 → 4.21 → 4.22 → 4.23 (continues)
    - 4.22 → 5.0 (first major bump)
    - 4.23 → 5.1 (second major bump)
    - 5.1 → 5.2 → 5.3 → ... (normal progression)

    Args:
        target_version: Target minor version (e.g., "5.0", "5.1")

    Returns:
        str: Special baseline version if mapping exists, None otherwise
    """
    # Special mappings for 5.x transition
    special_mappings = {
        "5.0": "4.22",
        "5.1": "4.23"
    }

    return special_mappings.get(target_version)


def get_special_target_mapping(baseline_version):
    """
    Get special target version mapping for major version transitions.
    Inverse of get_special_baseline_mapping.

    Args:
        baseline_version: Baseline minor version (e.g., "4.22", "4.23")

    Returns:
        str: Special target version if mapping exists, None otherwise
    """
    special_mappings = {
        "4.22": "5.0",
        "4.23": "5.1"
    }

    return special_mappings.get(baseline_version)


def resolve_gap_versions(version=None, baseline=None, target=None):
    """
    Unified version resolution for all gap analysis scripts.

    Handles all resolution paths including special baseline→target mappings
    (e.g., 4.22 → 5.0) so individual scripts don't need to duplicate this logic.

    Precedence:
      1. --version (or OPENSHIFT_VERSION env) → resolve_openshift_version()
      2. --baseline + --target → used directly
      3. --baseline only → apply special target mapping if available, else error
      4. No args → auto-detect via resolve_baseline_version() + resolve_target_version()

    Args:
        version: Single version to resolve (--version flag or OPENSHIFT_VERSION env)
        baseline: Explicit baseline version (--baseline flag)
        target: Explicit target version (--target flag)

    Returns:
        tuple: (baseline_version, target_version)
    """
    openshift_version = version or __import__('os').environ.get('OPENSHIFT_VERSION')

    if openshift_version:
        log_info(f"Resolving baseline and target from version: {openshift_version}")
        baseline_full, target_full = resolve_openshift_version(openshift_version)
        if not baseline_full or not target_full:
            log_error(f"Failed to resolve versions from: {openshift_version}")
            sys.exit(1)
    elif baseline and target:
        if baseline.count('.') == 1:
            baseline_full = get_latest_version_baseline_priority(baseline)
            log_info(f"Resolved baseline {baseline} → {baseline_full}")
        else:
            baseline_full = baseline
        if target.count('.') == 1:
            target_full = get_latest_version_target_priority(target)
            log_info(f"Resolved target {target} → {target_full}")
        else:
            target_full = target
    elif baseline and not target:
        baseline_minor = extract_minor_version(baseline)
        if baseline.count('.') == 1:
            baseline_full = get_latest_version_baseline_priority(baseline_minor)
            log_info(f"Resolved baseline {baseline} → {baseline_full}")
        else:
            baseline_full = baseline
        special_target = get_special_target_mapping(baseline_minor)
        if special_target:
            log_info(f"Using special target mapping: baseline {baseline_minor} → target {special_target}")
            target_full = get_latest_version_target_priority(special_target)
        else:
            log_error("--target is required when --baseline is specified "
                      f"(no default target mapping for {baseline_minor})")
            sys.exit(1)
    else:
        baseline_full = resolve_baseline_version()
        baseline_minor = extract_minor_version(baseline_full)
        special_target = get_special_target_mapping(baseline_minor)
        if special_target:
            log_info(f"Applying special target mapping: baseline {baseline_minor} → target {special_target}")
            target_full = get_latest_version_target_priority(special_target)
        else:
            target_full = resolve_target_version()

    return (baseline_full, target_full)


def resolve_openshift_version(openshift_version):
    """
    Resolve baseline and target versions from a single OPENSHIFT_VERSION.

    For GA or older versions (≤ current GA): z-stream comparison
      - BASE = previous z-stream
      - TARGET = latest z-stream
      - Example: 4.21 → BASE=4.21.14, TARGET=4.21.15

    For pre-GA versions (> current GA): cross-minor comparison
      - BASE = latest from (version-1): stable if GA, else candidate/nightly
      - TARGET = latest candidate/nightly for version
      - Example: 4.22 → BASE=4.21.15, TARGET=4.22.0-rc.3

    Special version mappings for major transitions:
      - 5.0 → BASE=4.22.x (not 4.23)
      - 5.1 → BASE=4.23.x (not 5.0)

    Args:
        openshift_version: Version to resolve (e.g., "4.21", "4.22", "5.0")

    Returns:
        tuple: (baseline_version, target_version)
        tuple: (None, None) if only one z-stream available (skip scenario)

    Raises:
        SystemExit: If version not found in Sippy releases or resolution fails
    """
    # Step 1: Get GA version from Sippy
    ga_version = get_latest_ga_version()

    # Step 2: Get all minor versions from accepted streams (sorted)
    # This includes both GA and pre-GA versions
    all_minor_versions = get_all_minor_versions_from_accepted_streams()

    # Step 3: Check if version exists in accepted streams
    if openshift_version not in all_minor_versions:
        log_error(f"Version {openshift_version} not found in accepted streams")
        log_error(f"Available versions: {' '.join(all_minor_versions)}")
        sys.exit(1)

    # Step 4: Compare openshift_version with ga_version
    # Extract major and minor for comparison
    ocp_parts = openshift_version.split('.')
    ga_parts = ga_version.split('.')

    ocp_major = int(ocp_parts[0])
    ocp_minor = int(ocp_parts[1]) if len(ocp_parts) > 1 else 0
    ga_major = int(ga_parts[0])
    ga_minor = int(ga_parts[1]) if len(ga_parts) > 1 else 0

    # Compare major first, then minor
    is_ga_or_older = (ocp_major < ga_major) or (ocp_major == ga_major and ocp_minor <= ga_minor)

    if is_ga_or_older:
        # GA or older version → z-stream comparison
        log_info(f"Version {openshift_version} is GA or older (GA={ga_version}), using z-stream comparison")

        # Get previous z-stream version
        base_version = get_previous_z_stream_version(openshift_version)

        if base_version is None:
            # Skip scenario - only one z-stream available
            return (None, None)

        # Get latest z-stream version (baseline precedence since both are stable)
        target_version = get_latest_version_baseline_priority(openshift_version)

        return (base_version, target_version)

    else:
        # Pre-GA version → cross-minor comparison
        log_info(f"Version {openshift_version} is pre-GA (GA={ga_version}), using cross-minor comparison")

        # Check for special baseline mapping first (e.g., 5.0 → 4.22, 5.1 → 4.23)
        special_baseline = get_special_baseline_mapping(openshift_version)

        if special_baseline:
            log_info(f"Using special baseline mapping: {openshift_version} → {special_baseline}")
            previous_version = special_baseline
        else:
            # Find previous version in sorted list
            try:
                idx = all_minor_versions.index(openshift_version)
                if idx == 0:
                    log_error(f"Cannot find previous version for {openshift_version} (first in sorted list)")
                    sys.exit(1)
                previous_version = all_minor_versions[idx - 1]
            except ValueError:
                log_error(f"Version {openshift_version} not found in accepted streams")
                sys.exit(1)

            log_info(f"Previous version in sorted list: {previous_version}")

        # Check if previous version is GA or pre-GA
        prev_parts = previous_version.split('.')
        prev_major = int(prev_parts[0])
        prev_minor = int(prev_parts[1]) if len(prev_parts) > 1 else 0

        previous_is_ga = (prev_major < ga_major) or (prev_major == ga_major and prev_minor <= ga_minor)

        if previous_is_ga:
            # Previous is GA → get latest stable
            log_info(f"Previous version {previous_version} is GA, using latest stable")
            base_version = get_latest_stable_version(ga_version=previous_version)
        else:
            # Previous is pre-GA → get latest using baseline precedence
            log_info(f"Previous version {previous_version} is pre-GA, using baseline precedence (stable > candidate > CI > nightly)")
            base_version = get_latest_version_baseline_priority(previous_version)

        # Get target version using target precedence
        log_info(f"Target version {openshift_version} using target precedence (candidate > CI > nightly)")
        target_version = get_latest_version_target_priority(openshift_version)

        return (base_version, target_version)


def resolve_baseline_version(cli_arg=None, env_var=None):
    """
    Resolve baseline version with precedence: CLI > ENV > Auto-detect.

    If CLI/ENV value is a minor version (e.g., "4.21"), it will be resolved to the
    latest patch version from 4-stable stream (e.g., "4.21.7").

    Args:
        cli_arg: Version from CLI argument (--baseline)
        env_var: Version from environment variable (BASE_VERSION)

    Returns:
        str: Resolved version string
    """
    if cli_arg:
        # Check if this is a minor version (X.Y format) that needs resolution
        if cli_arg.count('.') == 1:
            log_info(f"Resolving baseline minor version from CLI: {cli_arg}")
            version = get_latest_stable_version(ga_version=cli_arg)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using baseline version from CLI: {cli_arg}")
            return cli_arg
    elif env_var:
        # Check if this is a minor version (X.Y format) that needs resolution
        if env_var.count('.') == 1:
            log_info(f"Resolving baseline minor version from BASE_VERSION env: {env_var}")
            version = get_latest_stable_version(ga_version=env_var)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using baseline version from BASE_VERSION env: {env_var}")
            return env_var
    else:
        log_info("Auto-detecting baseline version from latest stable...")
        version = get_latest_stable_version()
        log_info(f"Auto-detected baseline version: {version}")
        return version


def resolve_target_version(cli_arg=None, env_var=None):
    """
    Resolve target version with precedence: CLI > ENV > Auto-detect.

    If CLI/ENV value is a minor version (e.g., "4.22"), it will be resolved to the
    latest candidate (RC from 4-stable or EC from 4-dev-preview).

    Special keywords: NIGHTLY, CANDIDATE

    Args:
        cli_arg: Version from CLI argument (--target)
        env_var: Version from environment variable (TARGET_VERSION)

    Returns:
        str: Resolved version string
    """
    if cli_arg:
        # Check if this is a minor version (X.Y format) that needs resolution
        if cli_arg.count('.') == 1:
            log_info(f"Resolving target minor version from CLI: {cli_arg}")
            version = get_latest_candidate_version(dev_version=cli_arg)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using target version from CLI: {cli_arg}")
            return cli_arg
    elif env_var:
        # Check if TARGET_VERSION is a special keyword
        if env_var.upper() == 'NIGHTLY':
            log_info("TARGET_VERSION=NIGHTLY detected, using latest dev nightly...")
            version = get_latest_dev_nightly_version()
            log_info(f"Auto-detected nightly target version: {version}")
            return version
        elif env_var.upper() == 'CANDIDATE':
            log_info("TARGET_VERSION=CANDIDATE detected, using latest candidate...")
            version = get_latest_candidate_version()
            log_info(f"Auto-detected candidate target version: {version}")
            return version
        # Check if this is a minor version (X.Y format) that needs resolution
        elif env_var.count('.') == 1:
            log_info(f"Resolving target minor version from TARGET_VERSION env: {env_var}")
            version = get_latest_candidate_version(dev_version=env_var)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using target version from TARGET_VERSION env: {env_var}")
            return env_var
    else:
        log_info("Auto-detecting target version from latest candidate...")
        version = get_latest_candidate_version()
        log_info(f"Auto-detected target version: {version}")
        return version
