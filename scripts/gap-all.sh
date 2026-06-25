#!/bin/bash
# Run all gap analyses
# Orchestrates execution of all individual gap analysis scripts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/logging.sh"
source "${SCRIPT_DIR}/lib/openshift-releases.sh"
source "${SCRIPT_DIR}/lib/ocm_auth.sh"

# Get project root (one level up from scripts/)
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
                           Available: aws,gcp,ocp,ocm-version-gate,feature-gates
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

# OCM authentication if credentials are available
if ! ocm_authenticate; then
    log_error "OCM authentication failed"
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

        if [[ "$step" != "aws" ]] && [[ "$step" != "gcp" ]] && [[ "$step" != "ocp" ]] && [[ "$step" != "ocm-version-gate" ]] && [[ "$step" != "feature-gates" ]]; then
            log_error "Invalid step: $step"
            log_error "Valid steps are: aws, gcp, ocp, ocm-version-gate, feature-gates"
            exit 1
        fi
    done

    log_info "Steps to run: ${STEPS_ARRAY[*]}"
else
    # Default: run all steps
    STEPS_ARRAY=("aws" "gcp" "ocp" "ocm-version-gate" "feature-gates")
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
        log_info "Steps to run: all (aws, gcp, ocp, ocm-version-gate, feature-gates)"
    fi
    log_info "========================================="
    log_info "Exiting without running gap analysis"
    exit 0
fi

# Build flags for gap scripts
VERBOSE_FLAG=""
if [[ "$VERBOSE" == "true" ]]; then
    VERBOSE_FLAG="--verbose"
fi


main() {
    # Capture start time
    START_TIME=$(date +%s)
    START_TIME_FORMATTED=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

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
            ocm-version-gate) checks_desc="${checks_desc}OCM Version Gates, " ;;
            feature-gates) checks_desc="${checks_desc}Feature Gates, " ;;
        esac
    done
    # Remove trailing comma and space
    checks_desc="${checks_desc%, }"

    log_info "Gap Analysis checks: $checks_desc"
    log_info "Report Directory: $REPORT_DIR"
    log_info "========================================="

    # Use associative arrays to store check results
    declare -A check_results=(
        ["aws"]=0
        ["gcp"]=0
        ["ocp"]=0
        ["ocm-version-gate"]=0
        ["feature-gates"]=0
    )
    declare -A check_status=(
        ["aws"]=""
        ["gcp"]=""
        ["ocp"]=""
        ["ocm-version-gate"]=""
        ["feature-gates"]=""
    )
    declare -A check_message=(
        ["aws"]=""
        ["gcp"]=""
        ["ocp"]=""
        ["ocm-version-gate"]=""
        ["feature-gates"]=""
    )
    declare -A check_diff_count=(
        ["aws"]=0
        ["gcp"]=0
        ["ocp"]=0
        ["ocm-version-gate"]=0
        ["feature-gates"]=0
    )

    # Define check metadata (check_num, check_name, check_type)
    declare -A check_num=(
        ["aws"]=1
        ["gcp"]=2
        ["ocp"]=3
        ["ocm-version-gate"]=4
        ["feature-gates"]=5
    )
    declare -A check_name=(
        ["aws"]="AWS STS Policy Gap"
        ["gcp"]="GCP WIF Template Gap"
        ["ocp"]="OCP Admin Gate Acknowledgments"
        ["ocm-version-gate"]="OCM Version Gates"
        ["feature-gates"]="Feature Gates Gap"
    )
    declare -A check_type=(
        ["aws"]="standard"
        ["gcp"]="standard"
        ["ocp"]="standard"
        ["ocm-version-gate"]="informational"
        ["feature-gates"]="informational"
    )
    declare -A check_count_field=(
        ["aws"]="differences_count"
        ["gcp"]="differences_count"
        ["ocp"]="gates_count"
        ["ocm-version-gate"]="gates_count"
        ["feature-gates"]="total_changes"
    )

    # Set environment variable to skip individual reports (full report will be generated instead)
    if [[ "${GAP_FULL_REPORT:-1}" == "0" ]]; then
        unset GAP_FULL_REPORT
    else
        export GAP_FULL_REPORT=1
    fi

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

    # Helper function to read status file and populate check arrays
    read_check_status() {
        local step="$1"
        local num="${check_num[$step]}"
        local count_field="${check_count_field[$step]}"
        local status_file="${REPORT_DIR}/status-check-${num}.json"

        if [[ -f "$status_file" ]]; then
            check_status[$step]=$(jq -r '.status' "$status_file" 2>/dev/null || echo "UNKNOWN")
            check_message[$step]=$(jq -r '.details.message' "$status_file" 2>/dev/null || echo "status unavailable")
            check_diff_count[$step]=$(jq -r ".details.${count_field} // 0" "$status_file" 2>/dev/null || echo "0")
        else
            check_status[$step]="UNKNOWN"
            check_message[$step]="status file not found"
            check_diff_count[$step]=0
        fi
    }

    # Helper function to print individual check summary
    print_individual_check() {
        local step_name="$1"
        local check_num="$2"
        local check_name="$3"
        local result="$4"
        local diff_count="$5"
        local message="$6"
        local check_type="${7:-standard}"  # standard or informational

        if ! should_run_step "$step_name"; then
            return
        fi

        local symbol=""
        local status=""

        if [[ $result -eq 0 ]]; then
            # Check passed
            if [[ $diff_count -gt 0 ]]; then
                symbol="⚠ "
                status="WARNING"
            else
                symbol="✓ "
                if [[ "$check_type" == "informational" ]]; then
                    status="INFORMATIONAL"
                else
                    status="PASS"
                fi
            fi
        else
            # Check failed
            symbol="✗ "
            if [[ "$check_type" == "informational" ]]; then
                symbol="⚠ "
                status="ERROR"
            else
                status="FAIL"
            fi
        fi

        echo "[$symbol] CHECK #$check_num: $check_name - $status ($message)"
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
            check_results[aws]=0
        else
            local exit_code=$?
            check_results[aws]=1
            log_error "AWS STS analysis script failed with exit code $exit_code"
        fi

        # Read status file
        read_check_status "aws"
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
            check_results[gcp]=0
        else
            local exit_code=$?
            check_results[gcp]=1
            log_error "GCP WIF analysis script failed with exit code $exit_code"
        fi

        # Read status file
        read_check_status "gcp"
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
            check_results[ocp]=0
        else
            local exit_code=$?
            check_results[ocp]=1
            log_error "OCP Admin Gate Acknowledgment analysis script failed with exit code $exit_code"
        fi

        # Read status file
        read_check_status "ocp"
    fi

    # Run OCM Version Gate analysis (informational only - always passes on validation findings)
    if should_run_step "ocm-version-gate"; then
        log_info ""
        log_info "Running OCM Version Gate Gap Analysis..."
        if python3 "${SCRIPT_DIR}/gap-ocm-version-gate.py" \
            --baseline "$BASELINE" \
            --target "$TARGET" \
            --report-dir "$REPORT_DIR" \
            $VERBOSE_FLAG 2>&1; then
            check_results[ocm-version-gate]=0
            check_status[ocm-version-gate]="PASS"
            check_message[ocm-version-gate]="OCM version gate analysis passed"
        else
            local exit_code=$?
            check_results[ocm-version-gate]=1
            check_status[ocm-version-gate]="FAIL"
            check_message[ocm-version-gate]="OCM version gate analysis failed with exit code $exit_code"
        fi
        check_diff_count[ocm-version-gate]=0
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
            check_results[feature-gates]=0
        else
            local exit_code=$?
            check_results[feature-gates]=1
            log_error "Feature Gates analysis script failed with exit code $exit_code"
        fi

        # Read status file
        read_check_status "feature-gates"
    fi

    # Calculate duration
    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    local duration_formatted=$(printf '%dm %ds' $((duration / 60)) $((duration % 60)))

    # Generate combined report
    log_info ""
    log_info "Generating combined report..."
    local combined_exit_code=0
    python3 "${SCRIPT_DIR}/generate-combined-report.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" \
        ${BUILD_LOG:+--build-log "$BUILD_LOG"} 2>&1 || combined_exit_code=$?
    if [[ $combined_exit_code -ne 0 ]]; then
        log_warning "Failed to generate combined report (individual reports still available) with exit code $combined_exit_code"
    fi
    # Exit 1 if any check failed (only for steps that ran)
    # Note: feature gates are informational only and always pass (exit 0)
    # If feature_gates_result=1, it means script execution error, which should fail
    local should_exit_fail=false

    for step in aws gcp ocp ocm-version-gate feature-gates; do
        if should_run_step "$step" && [[ ${check_results[$step]} -eq 1 ]]; then
            should_exit_fail=true
            break
        fi
    done


    if [[ "$should_exit_fail" == "true" ]]; then
        log_error ""
        log_error "❌ FAILED"
        exit 1
    else
        log_success ""
        log_success "✅ PASSED"
    fi


    # Print comprehensive summary
    log_info ""
    echo "==============================================================================="
    echo "GAP ANALYSIS SUMMARY"
    echo "==============================================================================="

    # Job information (if running in CI)
    if [[ -z "${job:-}" ]]; then
        job="job123"
    fi
    if [[ -z "${buildid:-}" ]]; then
        buildid="build1234"
    fi

    echo "Baseline: ${BASELINE}"
    echo "Target: ${TARGET}"
    echo "Started: ${START_TIME_FORMATTED}"
    echo "Completed: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Duration: ${duration_formatted}"
    echo ""
    echo "RESULTS:"

    # Check if any validation checks failed (only for steps that ran)
    local any_failed=false
    for step in aws gcp ocp; do
        if should_run_step "$step" && [[ ${check_results[$step]} -eq 1 ]]; then
            any_failed=true
            break
        fi
    done

    # Print individual check results
    for step in aws gcp ocp ocm-version-gate feature-gates; do
        if should_run_step "$step"; then
            print_individual_check "$step" "${check_num[$step]}" "${check_name[$step]}" \
                "${check_results[$step]}" "${check_diff_count[$step]}" "${check_message[$step]}" \
                "${check_type[$step]}"
        fi
    done

    echo ""

    # Overall status with warnings
    local has_warnings=false
    for step in aws gcp ocp ocm-version-gate feature-gates; do
        if should_run_step "$step" && [[ ${check_results[$step]} -eq 0 ]] && [[ ${check_diff_count[$step]} -gt 0 ]]; then
            has_warnings=true
            break
        fi
    done

    if [[ "$any_failed" == "false" ]]; then
        if [[ "$has_warnings" == "true" ]]; then
            echo "OVERALL STATUS: SUCCESS (with warnings)"
        else
            echo "OVERALL STATUS: SUCCESS"
        fi
    else
        echo "OVERALL STATUS: FAILED"
    fi

    echo ""
    echo "ARTIFACTS:"
    echo "- Reports directory: ${REPORT_DIR}/"

    # List HTML reports if they exist
    local html_reports=$(find "${REPORT_DIR}" -maxdepth 1 -name "*.html" -type f 2>/dev/null | sort)
    if [[ -n "$html_reports" && -n "$job" && -n "$buildid" ]]; then
        echo "- HTML reports:"
        while IFS= read -r report; do
            local basename=$(basename "$report")
            echo "  • https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/logs/${job}/${buildid}/artifacts/test/artifacts/rosa-gap-analysis-reports/${basename}"
        done <<< "$html_reports"
    fi

    # Add build log if available
    if [[  -n "$job" && -n "$buildid" ]]; then
        echo "- Build log: https://prow.ci.openshift.org/view/gs/test-platform-results/logs/${job}/${buildid}/build-log.txt"
    fi

    echo "==============================================================================="

}

main "$@"
