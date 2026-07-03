#!/usr/bin/env python3
"""
gap-ga-validation.py

ROSA Production GA Readiness Validation Script (ROSAENG-14225)
Author: Antigravity AI

This script automates the validation checklist required before a new OpenShift
Container Platform (OCP) release can be marked General Availability (GA) on ROSA.
"""

import argparse
import datetime
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Add shared lib directory and parent scripts directory to path
_scripts_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_scripts_dir / 'lib'))
sys.path.insert(0, str(_scripts_dir))
from common import (
    log_info,
    log_success,
    log_warning,
    log_error,
    check_command,
    is_pre_ga_version,
)
from openshift_releases import resolve_openshift_version
from reporters import generate_html_report, generate_json_report

_marketplace = importlib.import_module("gap-marketplace")
_ocm_gate = importlib.import_module("gap-ocm-version-gate")
_versions_channels = importlib.import_module("gap-versions-channels")


class GAReadinessValidator:
    def __init__(self, version: str, report_dir: str, baseline: str = None):
        self.version = version
        self.baseline = baseline
        self.report_dir = report_dir
        self.results = {}
        self.warnings = 0
        self.failures = 0
        self.critical_failures = 0

    def log_status(self, name: str, status: str, message: str, extra: dict = None):
        if status == "PASS":
            log_success(f"{name} - {message}")
        elif status == "WARN":
            log_warning(f"{name} - {message}")
            self.warnings += 1
        else:
            log_error(f"{name} - {message}")
            self.failures += 1

        entry = {
            "name": name,
            "status": status,
            "message": message
        }
        if extra:
            entry.update(extra)
        self.results[name] = entry

    # ==================== VALIDATION CHECKS ====================

    def check_channel_availability(self):
        """Verify channel availability (candidate, fast, stable)."""
        name = "Channel Availability"
        ocm_path = shutil.which("ocm")
        if not ocm_path:
            self.log_status(name, "WARN", "OCM CLI binary missing in PATH. Skipped channel availability check.")
            return

        query_version = self.version
        if query_version.count(".") == 1:
            query_version = f"{query_version}.0"

        try:
            search_query = (
                f"id='openshift-v{query_version}' or "
                f"id='openshift-v{query_version}-fast' or "
                f"id='openshift-v{query_version}-candidate'"
            )
            cmd = ["ocm", "get", f"/api/clusters_mgmt/v1/versions?search={search_query}"]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
            if proc.returncode != 0:
                err_msg = proc.stderr.strip() if proc.stderr else "No stderr output"
                self.log_status(name, "WARN", f"Failed to query OCM versions via 'ocm' CLI (exit code {proc.returncode}): {err_msg}")
                return

            versions_data = json.loads(proc.stdout)
            channels_found = set()
            if versions_data and "items" in versions_data:
                for v in versions_data["items"]:
                    channel_group = v.get("channel_group", "stable")
                    channels_found.add(channel_group)

            required_channels = {"candidate", "fast", "stable"}
            missing_channels = required_channels - channels_found

            if not missing_channels:
                self.log_status(name, "PASS", f"Version {self.version} is available in channels: {', '.join(required_channels)}.")
            else:
                self.critical_failures += 1
                self.log_status(name, "FAIL", f"Version {self.version} is missing from channels: {', '.join(missing_channels)} (Found: {', '.join(channels_found) or 'None'}).")
        except subprocess.TimeoutExpired:
            self.log_status(name, "WARN", "Query to OCM versions timed out (network issue or interactive login prompt). Skipped check.")
        except Exception as e:
            self.critical_failures += 1
            self.log_status(name, "FAIL", f"Failed checking version channel availability: {e}")

    def check_rosa_cli_compatibility(self):
        """Check ROSA CLI detection and listing across channels."""
        name = "ROSA CLI Compatibility"
        try:
            # Check if rosa is installed
            version_check = subprocess.run(["rosa", "version"], capture_output=True, text=True, check=False, timeout=15)
            if version_check.returncode != 0:
                err_msg = version_check.stderr.strip() if version_check.stderr else "No stderr output"
                self.critical_failures += 1
                self.log_status(name, "FAIL", f"ROSA CLI is not installed or execution failed (exit code {version_check.returncode}): {err_msg}")
                return

            cli_version = version_check.stdout.strip().split("\n")[0]
            
            channels = ["candidate", "fast", "stable"]
            found_channels = []
            missing_channels = []

            for channel in channels:
                list_versions = subprocess.run(["rosa", "list", "versions", "--channel-group", channel], capture_output=True, text=True, check=False, timeout=15)
                if list_versions.returncode != 0:
                    err_msg = list_versions.stderr.strip() if list_versions.stderr else "No stderr output"
                    self.log_status(name, "WARN", f"ROSA CLI ({cli_version}) failed to query channel '{channel}' (auth or network error, exit code {list_versions.returncode}): {err_msg}")
                    return
                if self.version in (list_versions.stdout or ""):
                    found_channels.append(channel)
                else:
                    missing_channels.append(channel)

            if not missing_channels:
                self.log_status(name, "PASS", f"ROSA CLI ({cli_version}) successfully detected target version {self.version} across all channels: {', '.join(channels)}.")
            elif found_channels:
                self.log_status(name, "WARN", f"ROSA CLI ({cli_version}) detected target version {self.version} in: {', '.join(found_channels)}, but missed in: {', '.join(missing_channels)}.")
            else:
                self.log_status(name, "WARN", f"ROSA CLI ({cli_version}) did not list version {self.version} in any channel group (candidate, fast, stable). Check channel status.")
        except subprocess.TimeoutExpired:
            self.log_status(name, "WARN", "ROSA CLI version query timed out (network issue or interactive login prompt). Skipped check.")
        except FileNotFoundError:
            self.critical_failures += 1
            self.log_status(name, "FAIL", "ROSA CLI binary not found. Please install ROSA CLI.")
        except Exception as e:
            self.critical_failures += 1
            self.log_status(name, "FAIL", f"ROSA CLI compatibility validation failed: {e}")

    def check_version_gates(self):
        """Verify OCM version gates are configured for the target release."""
        name = "Version Gates"
        major_minor = ".".join(self.version.split(".")[:2])

        try:
            gates = _ocm_gate.fetch_ocm_version_gates()
            if gates is None:
                self.log_status(name, "WARN", "Could not fetch OCM version gates (CLI missing or auth issue). Skipped check.")
                return

            target_pattern = re.compile(rf"\b{re.escape(major_minor)}\b")
            target_gates = [
                g for g in gates
                if major_minor == g.get("version_raw_id_prefix", "")
                or (g.get("value") and target_pattern.search(g["value"]))
            ]

            gate_items = [
                {
                    "label": g.get("label", "unknown"),
                    "description": g.get("description", "No description"),
                    "sts_only": g.get("sts_only", False),
                    "documentation_url": g.get("documentation_url", ""),
                    "warning_message": g.get("warning_message", ""),
                }
                for g in target_gates
            ]

            if target_gates:
                gate_details = [f"{gi['label']} (STS-only: {gi['sts_only']}) — {gi['description'][:100]}" for gi in gate_items]
                details_str = "\n   ".join(gate_details)
                self.log_status(
                    name, "PASS",
                    f"Found {len(target_gates)} version gate(s) for {major_minor}:\n   {details_str}",
                    extra={"gates": gate_items}
                )
            else:
                self.log_status(
                    name, "WARN",
                    f"No version gates found for {major_minor} in OCM. Gates may not be configured yet."
                )
        except Exception as e:
            self.critical_failures += 1
            self.log_status(name, "FAIL", f"Failed checking version gates: {e}")

    def check_upgrade_paths(self):
        """Verify upgrade paths from supported versions are available via Cincinnati."""
        name = "Upgrade Paths"

        try:
            from openshift_releases import extract_minor_version
            target_minor = extract_minor_version(self.version)
            baseline_minor = extract_minor_version(self.baseline) if self.baseline else target_minor

            is_z_stream = (baseline_minor == target_minor)
            baseline_full = self.baseline or self.version
            target_full = self.version

            upgrade_result = _versions_channels.analyze_upgrade_paths(
                baseline_minor, target_minor, baseline_full, target_full
            )

            total_paths = upgrade_result.get('total_paths', 0)
            channel_queried = upgrade_result.get('channel_queried', 'unknown')
            direct_path = upgrade_result.get('direct_path_exists', False)
            paths_to = upgrade_result.get('paths_to_target', 0)
            paths_from = upgrade_result.get('paths_from_baseline', 0)
            sample_paths = upgrade_result.get('sample_paths', [])[:10]

            upgrade_data = {
                "baseline": baseline_full,
                "target": target_full,
                "is_z_stream": is_z_stream,
                "channel_queried": channel_queried,
                "total_paths": total_paths,
                "paths_from_baseline": paths_from,
                "paths_to_target": paths_to,
                "direct_path_exists": direct_path,
                "sample_paths": sample_paths,
            }

            details = [f"Channel: {channel_queried}"]
            details.append(f"Total paths ({baseline_minor} \u2192 {target_minor}): {total_paths}")
            details.append(f"Paths from {baseline_full}: {paths_from}")
            details.append(f"Paths to {target_full}: {paths_to}")
            details.append(f"Direct {baseline_full} \u2192 {target_full}: {'Yes' if direct_path else 'No'}")
            if sample_paths:
                samples = [f"{p['from']} \u2192 {p['to']}" for p in sample_paths[:5]]
                details.append(f"Sample: {', '.join(samples)}")
            details_str = "\n   ".join(details)

            if total_paths > 0:
                self.log_status(
                    name, "PASS",
                    f"Found {total_paths} upgrade path(s) in {channel_queried}.\n   {details_str}",
                    extra={"upgrade": upgrade_data}
                )
            else:
                self.log_status(
                    name, "WARN",
                    f"No upgrade paths found in {channel_queried}. "
                    f"Version may not be in channel graph yet.\n   {details_str}",
                    extra={"upgrade": upgrade_data}
                )
        except Exception as e:
            self.log_status(name, "WARN", f"Upgrade paths check failed: {e}")

    def check_ci_job_status(self):
        """Check gap analysis Prow CI job status for the target version."""
        name = "CI Job Status"
        prow_url = "https://prow.ci.openshift.org"
        job_name = "periodic-ci-openshift-online-rosa-gap-analysis-main-nightly"

        try:
            history_url = f"{prow_url}/job-history/gs/test-platform-results/logs/{job_name}"
            req = Request(history_url, headers={'User-Agent': 'gap-analysis-script'})
            with urlopen(req, timeout=30) as response:
                html_content = response.read().decode('utf-8', errors='replace')

            match = re.search(r'var allBuilds = (\[.*?\]);', html_content, re.DOTALL)
            if not match:
                self.log_status(name, "WARN", f"Could not parse Prow job history from {history_url}. Page format may have changed.")
                return

            builds = json.loads(match.group(1))
            if not builds:
                self.log_status(name, "WARN", "No Prow job executions found.")
                return

            recent_builds = builds[:5]
            latest = recent_builds[0]
            latest_status = latest.get("Result", "UNKNOWN").upper()
            latest_id = latest.get("ID", "unknown")
            latest_started = latest.get("Started", "unknown")

            spyglass = latest.get("SpyglassLink", "")
            job_url = f"{prow_url}/{spyglass}" if spyglass else history_url

            ci_runs = []
            for b in recent_builds:
                b_status = b.get("Result", "UNKNOWN").upper()
                spy = b.get("SpyglassLink", "")
                ci_runs.append({
                    "id": b.get("ID", "?"),
                    "status": "PASS" if b_status == "SUCCESS" else "FAIL" if b_status in ("FAILURE", "ERROR") else b_status,
                    "started": b.get("Started", "?"),
                    "url": f"{prow_url}/{spy}" if spy else history_url,
                })

            ci_data = {
                "job_name": job_name,
                "history_url": history_url,
                "runs": ci_runs,
            }

            status_counts = {}
            for r in ci_runs:
                status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

            details = [f"#{r['id']} [{r['status']}] ({r['started']})" for r in ci_runs]
            details_str = "\n   ".join(details)

            if latest_status == "SUCCESS":
                self.log_status(
                    name, "PASS",
                    f"Latest Prow job #{latest_id} passed ({latest_started}). "
                    f"Last {len(ci_runs)} runs: {status_counts}.\n   {details_str}\n   Job: {job_url}",
                    extra={"ci": ci_data}
                )
            elif latest_status in ("FAILURE", "ERROR"):
                self.log_status(
                    name, "WARN",
                    f"Latest Prow job #{latest_id} failed ({latest_started}). "
                    f"Last {len(ci_runs)} runs: {status_counts}.\n   {details_str}\n   Job: {job_url}",
                    extra={"ci": ci_data}
                )
            else:
                self.log_status(
                    name, "WARN",
                    f"Latest Prow job #{latest_id} status: {latest_status} ({latest_started}). "
                    f"Last {len(ci_runs)} runs: {status_counts}.\n   {details_str}\n   Job: {job_url}",
                    extra={"ci": ci_data}
                )
        except (URLError, HTTPError) as e:
            self.log_status(name, "WARN", f"Could not reach Prow API ({e}). Network access to {prow_url} may be required.")
        except Exception as e:
            self.log_status(name, "WARN", f"CI job status check encountered an error: {e}")

    def check_documentation_status(self):
        """Verify SOPs and runbooks updates."""
        name = "SOP & Runbooks Update Status"
        major_minor = ".".join(self.version.split(".")[:2])
        target_url = "https://github.com/openshift/ops-sop/blob/master/v4/howto/gap-analysis.md"
        
        content = None
        source_info = f"remote git: {target_url}"
        mtime = 0
        
        git_urls = [
            "git@github.com:openshift/ops-sop.git",
            "https://github.com/openshift/ops-sop.git"
        ]
        
        git_errors = []
        for git_url in git_urls:
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    clone_cmd = [
                        "git", "clone", "--depth", "1", "--no-checkout", 
                        git_url, temp_dir
                    ]
                    proc_clone = subprocess.run(
                        clone_cmd, capture_output=True, text=True, check=False
                    )
                    if proc_clone.returncode != 0:
                        err_msg = proc_clone.stderr.strip() if proc_clone.stderr else "No stderr output"
                        git_errors.append(f"git clone {git_url} failed (exit code {proc_clone.returncode}): {err_msg}")
                        continue

                    # Try master branch first
                    show_cmd = ["git", "show", "origin/master:v4/howto/gap-analysis.md"]
                    proc_show = subprocess.run(
                        show_cmd, capture_output=True, text=True, check=False, cwd=temp_dir
                    )
                    if proc_show.returncode == 0:
                        content = proc_show.stdout
                    else:
                        err_msg_show = proc_show.stderr.strip() if proc_show.stderr else "No stderr output"
                        git_errors.append(f"git show origin/master failed (exit code {proc_show.returncode}): {err_msg_show}")
                        
                        show_cmd_main = ["git", "show", "origin/main:v4/howto/gap-analysis.md"]
                        proc_show_main = subprocess.run(
                            show_cmd_main, capture_output=True, text=True, check=False, cwd=temp_dir
                        )
                        if proc_show_main.returncode == 0:
                            content = proc_show_main.stdout
                        else:
                            err_msg_show_main = proc_show_main.stderr.strip() if proc_show_main.stderr else "No stderr output"
                            git_errors.append(f"git show origin/main failed (exit code {proc_show_main.returncode}): {err_msg_show_main}")

                    log_cmd = ["git", "log", "-1", "--format=%ct", "origin/master", "--", "v4/howto/gap-analysis.md"]
                    proc_log = subprocess.run(
                        log_cmd, capture_output=True, text=True, check=False, cwd=temp_dir
                    )
                    if proc_log.returncode == 0 and proc_log.stdout.strip():
                        mtime = int(proc_log.stdout.strip())
                    else:
                        err_msg_log = proc_log.stderr.strip() if proc_log.stderr else "No stderr output"
                        git_errors.append(f"git log origin/master failed (exit code {proc_log.returncode}): {err_msg_log}")
                        
                        log_cmd_main = ["git", "log", "-1", "--format=%ct", "origin/main", "--", "v4/howto/gap-analysis.md"]
                        proc_log_main = subprocess.run(
                            log_cmd_main, capture_output=True, text=True, check=False, cwd=temp_dir
                        )
                        if proc_log_main.returncode == 0 and proc_log_main.stdout.strip():
                            mtime = int(proc_log_main.stdout.strip())
                        else:
                            err_msg_log_main = proc_log_main.stderr.strip() if proc_log_main.stderr else "No stderr output"
                            git_errors.append(f"git log origin/main failed (exit code {proc_log_main.returncode}): {err_msg_log_main}")
                    
                    if content:
                        source_info = f"remote git: {git_url}"
                        break
                except Exception as e:
                    git_errors.append(f"Unexpected exception during git operations with {git_url}: {e}")
                    continue

        if not content:
            errors_str = " | ".join(git_errors)
            self.log_status(
                name, 
                "WARN", 
                f"Could not retrieve Gap Analysis SOP using remote git fetch. Details: {errors_str}"
            )
            return

        # Regular Expression Boundary Verification
        pattern = rf"(?<!\.)\b{re.escape(major_minor)}\b"
        regex_passed = bool(re.search(pattern, content))
        regex_status = "PASS" if regex_passed else "FAIL"
        
        # Fetch GA dates from Sippy API to determine version reference date
        ga_dates = {}
        try:
            from openshift_releases import fetch_sippy_ga_dates
            ga_dates = fetch_sippy_ga_dates() or {}
        except Exception:
            pass
        
        ga_date_str = ga_dates.get(major_minor)
        ref_time = None
        ref_name = "today"
        
        if ga_date_str:
            try:
                if ga_date_str.endswith("Z"):
                    ga_date_str = ga_date_str[:-1]
                ga_dt = datetime.datetime.fromisoformat(ga_date_str)
                ref_time = ga_dt.replace(tzinfo=datetime.timezone.utc).timestamp()
                ref_name = f"GA date ({ga_dt.strftime('%Y-%b-%d')})"
            except Exception:
                ref_time = None

        # Freshness Verification
        date_passed = False
        date_msg = ""
        
        if mtime > 0:
            file_dt = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
            file_date_str = file_dt.strftime('%Y-%b-%d')
            if ref_time:
                ga_end_time = ref_time + 16 * 30.5 * 86400
                ga_end_dt = datetime.datetime.fromtimestamp(ga_end_time, datetime.timezone.utc)
                ga_end_str = ga_end_dt.strftime('%Y-%b-%d')
                
                days_relative = (mtime - ref_time) / 86400
                date_passed = (days_relative >= -30) and (mtime <= ga_end_time)
                if date_passed:
                    if days_relative < 0:
                        date_msg = f"Updated {file_date_str}, which is {abs(days_relative):.1f} days before the {ref_name} (within the 30-day window) and before the GA end date ({ga_end_str})."
                    else:
                        days_to_end = (ga_end_time - mtime) / 86400
                        date_msg = f"Updated {file_date_str}, which is {days_relative:.1f} days after the {ref_name} and {days_to_end:.1f} days before the GA end date ({ga_end_str})."
                else:
                    if days_relative < -30:
                        date_msg = f"Updated {file_date_str}, which is {abs(days_relative):.1f} days before the {ref_name} (outside the 30-day window)."
                    else:
                        days_past_end = (mtime - ga_end_time) / 86400
                        date_msg = f"Updated {file_date_str}, which is {days_past_end:.1f} days past the GA end date ({ga_end_str})."
            else:
                now = datetime.datetime.now(datetime.timezone.utc)
                delta = now - file_dt
                days_since_update = delta.days + (delta.seconds / 86400)
                date_passed = days_since_update <= 30
                if date_passed:
                    date_msg = f"Updated {file_date_str}, which is {days_since_update:.1f} days ago (within 30 days of today)."
                else:
                    date_msg = f"Updated {file_date_str}, which is {days_since_update:.1f} days ago (outside 30 days of today)."
        else:
            date_msg = "Could not determine file commit timestamp from remote repository."
        
        date_status = "PASS" if date_passed else "FAIL"
        
        detailed_explanation = (
            f"\n   -> Check 1: Regex Version Boundary Check : {regex_status} (matches exact major/minor boundaries)"
            f"\n   -> Check 2: 30-Day Freshness Check        : {date_status} ({date_msg})"
        )
        
        if regex_passed and date_passed:
            self.log_status(
                name,
                "PASS",
                f"Verified '{major_minor}' is documented in Gap Analysis SOP ({source_info}).{detailed_explanation}"
            )
        else:
            self.log_status(
                name,
                "WARN",
                f"Gap Analysis SOP validation failed one or more criteria for '{major_minor}' ({source_info}).{detailed_explanation}"
            )

    def check_aws_marketplace_enablement(self):
        """Verify AWS marketplace enablement for ROSA Classic and ROSA HCP."""
        name = "AWS Marketplace Enablement"
        result = _marketplace.check_aws_marketplace_enablement(self.version)
        status = result.get('status', 'FAIL')
        message = result.get('message', 'Unknown error')
        channels = result.get('channels', {})

        if channels:
            details = []
            for chan, info in sorted(channels.items()):
                classic = "Yes" if info.get("rosa_classic") else "No"
                hcp = "Yes" if info.get("rosa_hcp") else "No"
                details.append(f"{chan}: Classic={classic}, HCP={hcp}")
            message += "\n   " + "\n   ".join(details)

        if status == 'FAIL':
            self.critical_failures += 1
        self.log_status(name, status, message, extra={"channels": channels} if channels else None)

    def check_gcp_marketplace_enablement(self):
        """Verify GCP marketplace enablement across channels."""
        name = "GCP Marketplace Enablement"
        result = _marketplace.check_gcp_marketplace_enablement(self.version)
        status = result.get('status', 'FAIL')
        message = result.get('message', 'Unknown error')
        channels = result.get('channels', {})

        if channels:
            details = []
            for chan, info in sorted(channels.items()):
                gcp = "Yes" if info.get("gcp_marketplace") else "No"
                details.append(f"{chan}: GCP={gcp}")
            message += "\n   " + "\n   ".join(details)

        if status == 'FAIL':
            self.critical_failures += 1
        self.log_status(name, status, message, extra={"channels": channels} if channels else None)

    def check_gcp_wif_compatibility(self):
        """Verify GCP WIF template compatibility in OCM wif-configs."""
        name = "GCP WIF Template Compatibility"
        ocm_path = shutil.which("ocm")
        if not ocm_path:
            self.log_status(name, "WARN", "OCM CLI binary missing in PATH. Skipped GCP WIF template compatibility check.")
            return

        major_minor = ".".join(self.version.split(".")[:2])
        target_wif_version = f"v{major_minor}"

        try:
            cmd = ["ocm", "gcp", "list", "wif-config"]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
            if proc.returncode != 0:
                err_msg = proc.stderr.strip() if proc.stderr else "No stderr output"
                self.log_status(name, "WARN", f"Failed to query OCM wif-configs via 'ocm' CLI (exit code {proc.returncode}): {err_msg}")
                return

            stdout = proc.stdout or ""
            supporting_configs = []

            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.search(r'\[([^\]]+)\]', line)
                if not match:
                    continue

                versions_str = match.group(1)
                versions = versions_str.split()

                if target_wif_version in versions:
                    # Parse config name
                    prefix = line.split('[')[0].strip()
                    parts = prefix.split()
                    config_id = parts[0] if len(parts) > 0 else "unknown_id"
                    config_name = parts[1] if len(parts) > 1 else "unknown_name"
                    supporting_configs.append(f"{config_name} ({config_id})")

            if supporting_configs:
                configs_str = ", ".join(supporting_configs)
                self.log_status(name, "PASS", f"GCP WIF template version '{target_wif_version}' is supported by active wif-config configurations: {configs_str}.")
            else:
                self.critical_failures += 1
                self.log_status(name, "FAIL", f"GCP WIF template version '{target_wif_version}' is not supported by any active GCP wif-config configurations.")
        except subprocess.TimeoutExpired:
            self.log_status(name, "WARN", "Query to OCM wif-configs timed out (network issue or interactive login prompt). Skipped check.")
        except Exception as e:
            self.critical_failures += 1
            self.log_status(name, "FAIL", f"Failed checking GCP WIF template compatibility: {e}")

    # ==================== RUN & REPORT ====================

    def execute(self) -> str:
        log_info(f"Starting ROSA GA Readiness Validation for version {self.version}")
        log_info("=========================================")

        all_checks = {
            "Channel Availability": self.check_channel_availability,
            "ROSA CLI Compatibility": self.check_rosa_cli_compatibility,
            "AWS Marketplace Enablement": self.check_aws_marketplace_enablement,
            "GCP Marketplace Enablement": self.check_gcp_marketplace_enablement,
            "Version Gates": self.check_version_gates,
            "Upgrade Paths": self.check_upgrade_paths,
            "CI Job Status": self.check_ci_job_status,
            "SOP & Runbooks Update Status": self.check_documentation_status,
            "GCP WIF Template Compatibility": self.check_gcp_wif_compatibility,
        }

        for name, check_fn in all_checks.items():
            log_info(f"Executing: {check_fn.__doc__.strip().splitlines()[0]}...")
            check_fn()

        validation_result = "PASS" if self.critical_failures == 0 else "FAIL"
        
        now = datetime.datetime.now(datetime.timezone.utc)
        report_data = {
            "type": "GA Readiness Validation",
            "baseline": self.baseline,
            "target": self.version,
            "env": os.environ.get("OCM_ENV", os.environ.get("OCM_ENVIRONMENT", "local CLI")),
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "validation_result": validation_result,
            "metrics": {
                "total": len(all_checks),
                "passed": len(all_checks) - self.failures - self.warnings,
                "warnings": self.warnings,
                "failures": self.failures,
                "critical_failures": self.critical_failures
            },
            "results": self.results
        }

        # Generate standard JSON report
        os.makedirs(self.report_dir, exist_ok=True)
        timestamp_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        json_file = os.path.join(self.report_dir, f"gap-analysis-ga-validation_GA_readiness_{self.version}_{timestamp_str}.json")
        generate_json_report(report_data, json_file)
        log_info(f"JSON report generated: {json_file}")

        # Generate HTML report
        html_file = os.path.join(self.report_dir, f"gap-analysis-ga-validation_GA_readiness_{self.version}_{timestamp_str}.html")
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

        return validation_result


def main():
    parser = argparse.ArgumentParser(
        description="Verify staging/production environment GA readiness prerequisites for ROSA releases.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
    openshift_version = args.version or os.environ.get('OPENSHIFT_VERSION')

    if openshift_version:
        log_info(f"Using single version: {openshift_version}")
        parts = openshift_version.split('.')
        if len(parts) >= 3 or '-' in openshift_version:
            target = openshift_version
            baseline = None
        else:
            baseline, target = resolve_openshift_version(openshift_version)
            if not baseline or not target:
                log_error(f"Failed to resolve versions from: {openshift_version}")
                sys.exit(1)
    elif args.baseline and args.target:
        baseline = args.baseline
        target = args.target
    else:
        # Auto-detect (fallback to individual resolution)
        from openshift_releases import resolve_baseline_version, resolve_target_version
        baseline = args.baseline or resolve_baseline_version()
        target = args.target or resolve_target_version()

    log_info("ROSA GA Readiness Validation")
    log_info("=========================================")
    log_info(f"Baseline version: {baseline}")
    log_info(f"Target version: {target}")
    log_info("=========================================")

    if args.dry_run:
        log_info("Dry-run mode enabled - exiting without performing validation.")
        sys.exit(0)

    # Validate the target version for GA readiness
    validator = GAReadinessValidator(
        version=target,
        report_dir=args.report_dir,
        baseline=baseline
    )

    result = validator.execute()

    if result == "FAIL":
        log_error("\n❌ FAILED - Target version GA readiness validation failed")
        sys.exit(1)
    else:
        log_success("\n✅ PASSED - Target version GA readiness validation successful")
        sys.exit(0)


if __name__ == "__main__":
    main()
