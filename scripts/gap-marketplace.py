#!/usr/bin/env python3
"""Marketplace Enablement Checks - AWS and GCP marketplace verification for ROSA/OCP versions."""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error, log_warning


def check_aws_marketplace_enablement(target_version):
    """Verify AWS marketplace enablement for ROSA Classic and ROSA HCP."""
    major_minor = ".".join(target_version.split(".")[:2])
    channels = ["stable", "fast", "candidate"]
    try:
        minor_val = int(major_minor.split(".")[1])
        if minor_val % 2 == 0:
            channels.append("eus")
    except Exception:
        pass

    rosa_path = shutil.which("rosa")
    if not rosa_path:
        log_warning("ROSA CLI binary missing in PATH. Skipped AWS Marketplace enablement check.")
        return {
            'status': 'WARN',
            'message': 'ROSA CLI binary missing in PATH. Skipped AWS Marketplace enablement check.',
            'channels': {}
        }

    log_info(f"Performing live AWS Marketplace verification using 'rosa' CLI across channels {channels}...")
    cli_results = {}
    for chan in channels:
        cli_results[chan] = {
            "rosa_classic": False,
            "rosa_hcp": False,
            "rosa_classic_output": "",
            "rosa_hcp_output": ""
        }

    for chan in channels:
        cmd_classic = ["rosa", "list", "versions", "--channel-group", chan]
        proc_classic = subprocess.run(cmd_classic, capture_output=True, text=True, check=False)
        if proc_classic.returncode != 0:
            log_warning(f"Failed to query 'rosa list versions' for channel group '{chan}' (is 'rosa' CLI logged in?).")
            return {
                'status': 'WARN',
                'message': f"Failed to query 'rosa list versions' (returncode={proc_classic.returncode}). Ensure 'rosa' CLI is logged in.",
                'channels': {}
            }

        for line in proc_classic.stdout.splitlines():
            parts = line.strip().split()
            if parts and (parts[0] == target_version or parts[0].startswith(major_minor)):
                cli_results[chan]["rosa_classic"] = True
                cli_results[chan]["rosa_classic_output"] = parts[0]
                break

        cmd_hcp = ["rosa", "list", "versions", "--hosted-cp", "--channel-group", chan]
        proc_hcp = subprocess.run(cmd_hcp, capture_output=True, text=True, check=False)
        if proc_hcp.returncode == 0:
            for line in proc_hcp.stdout.splitlines():
                parts = line.strip().split()
                if parts and (parts[0] == target_version or parts[0].startswith(major_minor)):
                    cli_results[chan]["rosa_hcp"] = True
                    cli_results[chan]["rosa_hcp_output"] = parts[0]
                    break

    all_passed = True
    for chan in channels:
        res = cli_results[chan]
        if not (res["rosa_classic"] and res["rosa_hcp"]):
            all_passed = False

    if all_passed:
        log_success(f"Successfully verified AWS Marketplace enablement via 'rosa' CLI across channels {channels}.")
        return {
            'status': 'PASS',
            'message': f"Successfully verified AWS Marketplace enablement across channels: {', '.join(channels)}.",
            'channels': cli_results
        }
    else:
        partially_enabled = False
        for chan in channels:
            res = cli_results[chan]
            if res["rosa_classic"] or res["rosa_hcp"]:
                partially_enabled = True
                break
        
        if partially_enabled:
            log_warning("AWS Marketplace enablement is partially complete. Some channels are missing.")
            return {
                'status': 'WARN',
                'message': "AWS Marketplace enablement is partially complete. Some channels are missing.",
                'channels': cli_results
            }
        else:
            log_error("AWS Marketplace enablement checks failed. No ROSA versions detected in any channel.")
            return {
                'status': 'FAIL',
                'message': "AWS Marketplace enablement checks failed. No ROSA versions detected in any channel.",
                'channels': cli_results
            }


def check_gcp_marketplace_enablement(target_version):
    """Verify GCP marketplace enablement."""
    major_minor = ".".join(target_version.split(".")[:2])
    channels = ["stable", "fast", "candidate"]
    try:
        minor_val = int(major_minor.split(".")[1])
        if minor_val % 2 == 0:
            channels.append("eus")
    except Exception:
        pass

    ocm_path = shutil.which("ocm")
    if not ocm_path:
        log_warning("OCM CLI binary missing in PATH. Skipped GCP Marketplace enablement check.")
        return {
            'status': 'WARN',
            'message': 'OCM CLI binary missing in PATH. Skipped GCP Marketplace enablement check.',
            'channels': {}
        }

    log_info(f"Performing live GCP Marketplace verification using 'ocm' CLI across channels {channels}...")
    cli_results = {}
    for chan in channels:
        cli_results[chan] = {
            "gcp_marketplace": False,
            "gcp_marketplace_output": ""
        }

    for chan in channels:
        cmd_gcp = ["ocm", "list", "versions", "--channel-group", chan, "--marketplace-gcp=true"]
        proc_gcp = subprocess.run(cmd_gcp, capture_output=True, text=True, check=False)
        if proc_gcp.returncode != 0:
            log_warning(f"Failed to query 'ocm' CLI versions for channel group '{chan}' (is 'ocm' CLI logged in?).")
            return {
                'status': 'WARN',
                'message': f"Failed to query 'ocm' CLI (returncode={proc_gcp.returncode}). Ensure 'ocm' CLI is logged in.",
                'channels': {}
            }

        for line in proc_gcp.stdout.splitlines():
            parts = line.strip().split()
            if parts and (parts[0] == target_version or parts[0].startswith(major_minor)):
                cli_results[chan]["gcp_marketplace"] = True
                cli_results[chan]["gcp_marketplace_output"] = parts[0]
                break

    all_passed = True
    for chan in channels:
        res = cli_results[chan]
        if not res["gcp_marketplace"]:
            all_passed = False

    if all_passed:
        log_success(f"Successfully verified GCP Marketplace enablement via 'ocm' CLI across channels {channels}.")
        return {
            'status': 'PASS',
            'message': f"Successfully verified GCP Marketplace enablement across channels: {', '.join(channels)}.",
            'channels': cli_results
        }
    else:
        partially_enabled = False
        for chan in channels:
            res = cli_results[chan]
            if res["gcp_marketplace"]:
                partially_enabled = True
                break
        
        if partially_enabled:
            log_warning("GCP Marketplace enablement is partially complete. Some channels are missing.")
            return {
                'status': 'WARN',
                'message': "GCP Marketplace enablement is partially complete. Some channels are missing.",
                'channels': cli_results
            }
        else:
            log_error("GCP Marketplace enablement checks failed. No GCP versions detected in any channel.")
            return {
                'status': 'FAIL',
                'message': "GCP Marketplace enablement checks failed. No GCP versions detected in any channel.",
                'channels': cli_results
            }
