#!/bin/bash
# Create EMA schedules and write one REDCap import file per event.
# Extra options are passed through, e.g.:
#   ./ema_populate_redcap.sh --dry-run
#   ./ema_populate_redcap.sh --today=2026-11-02 --seed=101   (testing)
set -euo pipefail

CWD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${CWD}/../.."
CONFIG_DIR="${BASE_DIR}/config"
DATA_DIR="${BASE_DIR}/examples"   # screening CSV and the EMA event CSVs
OUT_DIR="${BASE_DIR}/examples"      # import files are written here

# Output folder path
mkdir -p "${OUT_DIR}"

echo "Populating REDCap EMA"
ema-populate -v "$@" \
    "${DATA_DIR}/redcap__scr.csv" \
    "${CONFIG_DIR}/test_config.yaml" \
    "${OUT_DIR}"
