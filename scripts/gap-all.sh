#!/bin/bash
# Run all gap analyses
# Orchestrates execution of all individual gap analysis scripts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/logging.sh"
source "${SCRIPT_DIR}/lib/openshift-releases.sh"

# Get project root (one level up from scripts/)
START_TIME=$(date +%s)
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASELINE=""
TARGET=""
VERSION=""
VERBOSE=false
DRY_RUN=false
REPORT_DIR="${REPORT_DIR:-reports}"
STEPS=""

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Run gap analysis between two OpenShift versions for both AWS and GCP platforms.
Validates target version structure in managed-cluster-config repository.
Exits 1 if target version validation fails (FAIL), exits 0 if validation passes (PASS).

Optional Arguments:
  --baseline <version>     Baseline version (must be used with --target)
  --target <version>       Target version (must be used with --baseline)
  --version <version>      Single version to analyze (auto-resolves baseline and target)
  --steps <steps>          Comma-separated list of steps to run (default: all)
                           Available: aws,gcp,ocp,feature-gates
                           Example: --steps aws,gcp (runs only AWS and GCP)
  --dry-run                Show resolved versions and exit without running analysis
  --verbose                Enable verbose logging
  --report-dir <path>      Directory to store reports (default: reports/)
  -h, --help               Show this help

Note: You must use either:
  - --version <version>              (auto-resolve baseline and target)
  - --baseline <ver> --target <ver>  (explicit control, both required)

Environment Variables:
  BASE_VERSION            Baseline version (must be used with TARGET_VERSION)
  TARGET_VERSION          Target version (must be used with BASE_VERSION)
                          Special values: NIGHTLY (dev nightly), CANDIDATE (dev candidate)
  OPENSHIFT_VERSION       Single version to analyze (auto-resolves baseline and target)
  REPORT_DIR              Directory to store reports (default: reports/)

Version Resolution Precedence (highest to lowest):
  1. --version flag (auto-resolve baseline and target)
  2. OPENSHIFT_VERSION env var (auto-resolve baseline and target)
  3. --baseline AND --target flags (explicit control, both required)
  4. BASE_VERSION AND TARGET_VERSION env vars (explicit control, both required)
  5. Auto-detected (latest stable for baseline, latest candidate for target)

Single Version Resolution (--version or OPENSHIFT_VERSION):
  For GA or older versions (≤ current GA):
    - Compares within same minor version (z-stream comparison)
    - BASE = previous z-stream, TARGET = latest z-stream
    - Example: --version 4.19 → BASE=4.19.21, TARGET=4.19.22

  For pre-GA versions (> current GA):
    - Compares across minor versions
    - BASE = latest from (version-1) using baseline precedence (stable > candidate > CI > nightly)
    - TARGET = latest for version using target precedence (candidate > CI > nightly)
    - Example: --version 4.23 → BASE=4.22.x (candidate), TARGET=4.23.0-rc.0 (candidate if available)

Examples:
  # Auto-detect versions (stable → candidate)
  $0

  # Single version (auto-resolve baseline and target) - RECOMMENDED
  $0 --version 4.21          # GA version: z-stream comparison (4.21.14 vs 4.21.15)
  $0 --version 4.22          # Pre-GA: cross-minor (4.21.15 vs 4.22.0-rc.3)
  $0 --version 4.19          # Older GA: z-stream comparison (4.19.21 vs 4.19.22)

  # Explicit baseline and target (both required)
  $0 --baseline 4.21 --target 4.22
  $0 --baseline 4.21.6 --target 4.22.0-ec.3 --verbose

  # Run specific steps only
  $0 --version 4.22 --steps aws,gcp         # Only AWS and GCP
  $0 --baseline 4.21 --target 4.22 --steps aws  # Only AWS
  $0 --steps feature-gates                  # Only Feature Gates (auto-detect versions)

  # Dry-run mode (show versions without running analysis)
  $0 --version 4.21 --dry-run
  $0 --baseline 4.21 --target 4.22 --dry-run
  $0 --dry-run               # Show auto-detected versions

  # Using environment variables
  OPENSHIFT_VERSION=4.22 $0                        # Same as --version 4.22
  BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 $0  # Both required
  BASE_VERSION=4.21 TARGET_VERSION=NIGHTLY $0      # Nightly target

Exit Codes:
  0 - All checks passed (PASS)
  1 - One or more checks failed (FAIL) OR execution failure

EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline) BASELINE="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --steps) STEPS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --verbose) VERBOSE=true; shift ;;
        --report-dir) REPORT_DIR="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) log_error "Unknown option: $1"; usage ;;
    esac
done

# Validate flag combinations
if [[ -n "$VERSION" ]] && ( [[ -n "$BASELINE" ]] || [[ -n "$TARGET" ]] ); then
    log_error "Cannot use --version together with --baseline or --target"
    log_error "Use either:"
    log_error "  --version <version>              (auto-resolve baseline and target)"
    log_error "  --baseline <ver> --target <ver>  (explicit control)"
    exit 1
fi

# Validate that --baseline and --target are used together, not individually
if ( [[ -n "$BASELINE" ]] && [[ -z "$TARGET" ]] ) || ( [[ -z "$BASELINE" ]] && [[ -n "$TARGET" ]] ); then
    if [[ -n "$BASELINE" ]]; then
        log_error "Cannot use --baseline without --target"
    else
        log_error "Cannot use --target without --baseline"
    fi
    log_error "Use either:"
    log_error "  --version <version>              (auto-resolve baseline and target)"
    log_error "  --baseline <ver> --target <ver>  (explicit control)"
    exit 1
fi

# Version Resolution with Precedence Order:
# 1. --version flag → auto-resolve both baseline and target
# 2. OPENSHIFT_VERSION env var → auto-resolve both baseline and target
# 3. --baseline AND --target (both required) → use explicit values
# 4. BASE_VERSION AND TARGET_VERSION env vars (both required) → use explicit values
# 5. Auto-detect both (default)

BASELINE_PULLSPEC=""
TARGET_PULLSPEC=""

# Check if using --version flag (auto-resolve both)
if [[ -n "$VERSION" ]]; then
    log_info "Resolving baseline and target from --version $VERSION..."
    resolve_result=$(resolve_openshift_version "$VERSION")
    resolve_exit_code=$?

    if [[ $resolve_exit_code -ne 0 ]]; then
        log_error "Failed to resolve versions from --version $VERSION"
        exit 1
    fi

    # Check for skip scenario
    if [[ "$resolve_result" == "SKIP SKIP" ]]; then
        log_info "Only one z-stream version available for $VERSION, skipping gap analysis"
        exit 0
    fi

    BASELINE=$(echo "$resolve_result" | awk '{print $1}')
    TARGET=$(echo "$resolve_result" | awk '{print $2}')
    log_info "Resolved from --version $VERSION: BASELINE=$BASELINE, TARGET=$TARGET"

# Check if using OPENSHIFT_VERSION env var (auto-resolve both)
elif [[ -n "${OPENSHIFT_VERSION:-}" ]]; then
    log_info "Resolving baseline and target from OPENSHIFT_VERSION=$OPENSHIFT_VERSION..."
    resolve_result=$(resolve_openshift_version "$OPENSHIFT_VERSION")
    resolve_exit_code=$?

    if [[ $resolve_exit_code -ne 0 ]]; then
        log_error "Failed to resolve versions from OPENSHIFT_VERSION=$OPENSHIFT_VERSION"
        exit 1
    fi

    # Check for skip scenario
    if [[ "$resolve_result" == "SKIP SKIP" ]]; then
        log_info "Only one z-stream version available for $OPENSHIFT_VERSION, skipping gap analysis"
        exit 0
    fi

    BASELINE=$(echo "$resolve_result" | awk '{print $1}')
    TARGET=$(echo "$resolve_result" | awk '{print $2}')
    log_info "Resolved from OPENSHIFT_VERSION=$OPENSHIFT_VERSION: BASELINE=$BASELINE, TARGET=$TARGET"

# Check if both --baseline AND --target are set (explicit control)
elif [[ -n "$BASELINE" ]] && [[ -n "$TARGET" ]]; then
    log_info "Using baseline and target from CLI: BASELINE=$BASELINE, TARGET=$TARGET"

# Check if both BASE_VERSION AND TARGET_VERSION env vars are set (explicit control)
elif [[ -n "${BASE_VERSION:-}" ]] && [[ -n "${TARGET_VERSION:-}" ]]; then
    BASELINE="$BASE_VERSION"

    # Check if TARGET_VERSION is a special keyword
    if [[ "${TARGET_VERSION^^}" == "NIGHTLY" ]]; then
        log_info "TARGET_VERSION=NIGHTLY detected, using latest dev nightly..."
        TARGET=$(get_latest_dev_nightly_version)
        TARGET_PULLSPEC=$(get_latest_dev_nightly_pullspec)
        log_info "Auto-detected nightly target version: $TARGET"
        log_info "Auto-detected nightly target pullspec: $TARGET_PULLSPEC"
    elif [[ "${TARGET_VERSION^^}" == "CANDIDATE" ]]; then
        log_info "TARGET_VERSION=CANDIDATE detected, using latest candidate..."
        TARGET=$(get_latest_candidate_version)
        TARGET_PULLSPEC=$(get_latest_candidate_pullspec)
        log_info "Auto-detected candidate target version: $TARGET"
        log_info "Auto-detected candidate target pullspec: $TARGET_PULLSPEC"
    else
        TARGET="$TARGET_VERSION"
    fi
    log_info "Using baseline and target from env vars: BASELINE=$BASELINE, TARGET=$TARGET"

# Default: Auto-detect both
else
    log_info "Auto-detecting baseline version from latest stable..."
    BASELINE=$(get_latest_stable_version)
    BASELINE_PULLSPEC=$(get_latest_stable_pullspec)
    log_info "Auto-detected baseline version: $BASELINE"
    log_info "Auto-detected baseline pullspec: $BASELINE_PULLSPEC"

    log_info "Auto-detecting target version from latest candidate..."
    TARGET=$(get_latest_candidate_version)
    TARGET_PULLSPEC=$(get_latest_candidate_pullspec)
    log_info "Auto-detected target version: $TARGET"
    log_info "Auto-detected target pullspec: $TARGET_PULLSPEC"
fi

# Parse steps if provided
STEPS_ARRAY=()
if [[ -n "$STEPS" ]]; then
    # Split comma-separated steps
    IFS=',' read -ra STEPS_ARRAY <<< "$STEPS"

    # Validate each step
    for step in "${STEPS_ARRAY[@]}"; do
        # Trim whitespace
        step=$(echo "$step" | xargs)

        if [[ "$step" != "aws" ]] && [[ "$step" != "gcp" ]] && [[ "$step" != "ocp" ]] && [[ "$step" != "feature-gates" ]]; then
            log_error "Invalid step: $step"
            log_error "Valid steps are: aws, gcp, ocp, feature-gates"
            exit 1
        fi
    done

    log_info "Steps to run: ${STEPS_ARRAY[*]}"
else
    # Default: run all steps
    STEPS_ARRAY=("aws" "gcp" "ocp" "feature-gates")
fi

# Dry-run mode: show resolved versions and exit
if [[ "$DRY_RUN" == "true" ]]; then
    log_info ""
    log_info "========================================="
    log_info "  Dry-Run Mode (Version Resolution Only)"
    log_info "========================================="
    log_success "Baseline: $BASELINE"
    log_success "Target:   $TARGET"
    if [[ -n "$BASELINE_PULLSPEC" ]]; then
        log_info "Baseline pullspec: $BASELINE_PULLSPEC"
    fi
    if [[ -n "$TARGET_PULLSPEC" ]]; then
        log_info "Target pullspec: $TARGET_PULLSPEC"
    fi
    if [[ -n "$STEPS" ]]; then
        log_info "Steps to run: ${STEPS_ARRAY[*]}"
    else
        log_info "Steps to run: all (aws, gcp, ocp, feature-gates)"
    fi
    log_info "========================================="
    log_info "Exiting without running gap analysis"
    exit 0
fi

# Build verbose flag
VERBOSE_FLAG=""
if [[ "$VERBOSE" == "true" ]]; then
    VERBOSE_FLAG="--verbose"
fi

# Helper function for consistent result formatting
format_result() {
    local icon="$1"
    local check_num="$2"
    local check_name="$3"
    local status="$4"
    local details="$5"
    printf "%-4s CHECK #%d: %-25s - %-10s (%s)\n" "$icon" "$check_num" "$check_name" "$status" "$details"
}

# Print executive summary to build log
print_summary() {
    local report_dir="$1"
    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    local duration_fmt=$(printf "%dm %ds" $((duration / 60)) $((duration % 60)))

    echo ""
    echo "==============================================================================="
    echo "GAP ANALYSIS SUMMARY"
    echo "==============================================================================="
    echo "Job:       ${JOB_NAME:-local-run}"
    echo "Run:       ${BUILD_ID:-$(date +%s)}"
    echo "Baseline:  $BASELINE"
    echo "Target:    $TARGET"
    echo "Started:   $(date -u -r "${START_TIME}" '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Completed: $(date -u -r "${end_time}" '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Duration:  $duration_fmt"
    echo ""
    echo "RESULTS:"
    
    # AWS Result (Check #1)
    local aws_icon="[ℹ]"
    local aws_status="SKIPPED"
    if should_run_step "aws"; then
        if [[ $aws_result -eq 0 ]]; then aws_icon="[✓]"; aws_status="PASS"; else aws_icon="[✗]"; aws_status="FAIL"; fi
    fi
    format_result "$aws_icon" 1 "AWS STS Policies" "$aws_status" ""

    # GCP Result (Check #2)
    local gcp_icon="[ℹ]"
    local gcp_status="SKIPPED"
    if should_run_step "gcp"; then
        if [[ $gcp_result -eq 0 ]]; then gcp_icon="[✓]"; gcp_status="PASS"; else gcp_icon="[✗]"; gcp_status="FAIL"; fi
    fi
    format_result "$gcp_icon" 2 "GCP WIF Policies" "$gcp_status" ""

    # OCP Result (Check #3)
    local ocp_icon="[ℹ]"
    local ocp_status="SKIPPED"
    if should_run_step "ocp"; then
        if [[ $ocp_gate_ack_result -eq 0 ]]; then ocp_icon="[✓]"; ocp_status="PASS"; else ocp_icon="[✗]"; ocp_status="FAIL"; fi
    fi
    format_result "$ocp_icon" 3 "OCP Admin Gates" "$ocp_status" ""

    # Feature Gates Result (Check #4)
    local fg_icon="[ℹ]"
    local fg_status="SKIPPED"
    if should_run_step "feature-gates"; then
        fg_icon="[✓]"
        fg_status="PASS"
    fi
    format_result "$fg_icon" 4 "Feature Gates" "$fg_status" "Informational"

    echo ""
    local overall="SUCCESS"
    if [[ "${should_exit_fail:-false}" == "true" ]]; then overall="FAILURE"; fi
    echo "OVERALL STATUS: $overall"
    echo ""
    echo "ARTIFACTS:"
    echo "- Reports: $report_dir/"
    echo "- Aggregated: $report_dir/aggregate-summary.html"
    echo "==============================================================================="
    echo ""
}

main() {
    # Create report directory if it doesn't exist
    mkdir -p "$REPORT_DIR"

    log_info "========================================="
    log_info "  OpenShift Gap Analysis Suite"
    log_info "========================================="
    log_info "Baseline: $BASELINE"
    log_info "Target:   $TARGET"

    # Build checks description based on steps
    local checks_desc=""
    for step in "${STEPS_ARRAY[@]}"; do
        case "$step" in
            aws) checks_desc="${checks_desc}AWS STS, " ;;
            gcp) checks_desc="${checks_desc}GCP WIF, " ;;
            ocp) checks_desc="${checks_desc}OCP Gate Acknowledgments, " ;;
            feature-gates) checks_desc="${checks_desc}Feature Gates, " ;;
        esac
    done
    # Remove trailing comma and space
    checks_desc="${checks_desc%, }"

    log_info "Gap Analysis checks: $checks_desc"
    log_info "Report Directory: $REPORT_DIR"
    log_info "========================================="

    local aws_result=0
    local gcp_result=0
    local feature_gates_result=0
    local ocp_gate_ack_result=0
    local aws_output=""
    local gcp_output=""
    local feature_gates_output=""
    local ocp_gate_ack_output=""

    # Set environment variable to skip individual reports (full report will be generated instead)

    # Helper function to check if a step should run
    should_run_step() {
        local step_name="$1"
        for step in "${STEPS_ARRAY[@]}"; do
            if [[ "$step" == "$step_name" ]]; then
                return 0
            fi
        done
        return 1
    }

    # Run AWS STS analysis
    if should_run_step "aws"; then
        log_info ""
        log_info "Running AWS STS Policy Gap Analysis..."
        if python3 "${SCRIPT_DIR}/gap-aws-sts.py" \
            --baseline "$BASELINE" \
            --target "$TARGET" \
            --report-dir "$REPORT_DIR" \
            $VERBOSE_FLAG 2>&1; then
            aws_result=0
        else
            aws_result=1
        fi
    fi

    # Run GCP WIF analysis
    if should_run_step "gcp"; then
        log_info ""
        log_info "Running GCP WIF Policy Gap Analysis..."
        if python3 "${SCRIPT_DIR}/gap-gcp-wif.py" \
            --baseline "$BASELINE" \
            --target "$TARGET" \
            --report-dir "$REPORT_DIR" \
            $VERBOSE_FLAG 2>&1; then
            gcp_result=0
        else
            gcp_result=1
        fi
    fi

    # Run OCP Gate Acknowledgment analysis
    if should_run_step "ocp"; then
        log_info ""
        log_info "Running OCP Admin Gate Acknowledgment Analysis..."
        if python3 "${SCRIPT_DIR}/gap-ocp-gate-ack.py" \
            --baseline "$BASELINE" \
            --target "$TARGET" \
            --report-dir "$REPORT_DIR" \
            $VERBOSE_FLAG 2>&1; then
            ocp_gate_ack_result=0
        else
            ocp_gate_ack_result=1
        fi
    fi

    # Run Feature Gates analysis (informational only - always passes)
    # IMPORTANT: Feature Gates should always be executed last, even if new checks are added in the future
    if should_run_step "feature-gates"; then
        log_info ""
        log_info "Running Feature Gates Gap Analysis..."
        if python3 "${SCRIPT_DIR}/gap-feature-gates.py" \
            --baseline "$BASELINE" \
            --target "$TARGET" \
            --report-dir "$REPORT_DIR" \
            $VERBOSE_FLAG 2>&1; then
            feature_gates_result=0
        else
            feature_gates_result=1
        fi
    fi

    # Print summary
    log_info ""
    log_info "========================================="
    log_info "  Gap Analysis Complete!"
    log_info "========================================="

    # Check if any validation checks failed (only for steps that ran)
    local any_failed=false
    if should_run_step "aws" && [[ $aws_result -eq 1 ]]; then
        any_failed=true
    fi
    if should_run_step "gcp" && [[ $gcp_result -eq 1 ]]; then
        any_failed=true
    fi
    if should_run_step "ocp" && [[ $ocp_gate_ack_result -eq 1 ]]; then
        any_failed=true
    fi

    if [[ "$any_failed" == "false" ]]; then
        log_success "All validation checks passed"
    else
        if should_run_step "aws" && [[ $aws_result -eq 1 ]]; then
            log_info "AWS STS: Target version validation failed (FAIL)"
        fi
        if should_run_step "gcp" && [[ $gcp_result -eq 1 ]]; then
            log_info "GCP WIF: Target version validation failed (FAIL)"
        fi
        if should_run_step "ocp" && [[ $ocp_gate_ack_result -eq 1 ]]; then
            log_info "OCP Gate Acknowledgments: Target version validation failed (FAIL)"
        fi
        if should_run_step "feature-gates"; then
            log_info "Feature Gates: Informational only (does not affect pass/fail)"
        fi
    fi

    # Generate combined report
    log_info ""
    log_info "Generating combined report..."
    python3 "${SCRIPT_DIR}/generate-combined-report.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" 2>&1 || {
        log_warning "Failed to generate combined report (individual reports still available)"
    }

    # Generate aggregated executive report
    log_info ""
    log_info "Generating aggregated executive report..."
    python3 "${SCRIPT_DIR}/gap-aggregate-report.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" \
        ${BUILD_LOG:+--build-log "$BUILD_LOG"} 2>&1 || {
        log_warning "Failed to generate aggregated executive report"
    }
    # Exit 1 if any check failed (only for steps that ran)
    # Note: feature gates are informational only and always pass (exit 0)
    # If feature_gates_result=1, it means script execution error, which should fail
    local should_exit_fail=false

    if should_run_step "aws" && [[ $aws_result -eq 1 ]]; then
        should_exit_fail=true
    fi
    if should_run_step "gcp" && [[ $gcp_result -eq 1 ]]; then
        should_exit_fail=true
    fi
    if should_run_step "ocp" && [[ $ocp_gate_ack_result -eq 1 ]]; then
        should_exit_fail=true
    fi
    if should_run_step "feature-gates" && [[ $feature_gates_result -eq 1 ]]; then
        should_exit_fail=true
    fi

    print_summary "$REPORT_DIR"

    if [[ "$should_exit_fail" == "true" ]]; then
        log_error ""
        log_error "❌ FAILED"
        exit 1
    else
        log_success ""
        log_success "✅ PASSED"
        exit 0
    fi
}

main "$@"
