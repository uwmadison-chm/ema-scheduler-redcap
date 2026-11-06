#!/bin/bash
# Create EMA schedules and write one REDCap import file per event.
# Extra options are passed through, e.g.:
#   ./ema_populate_redcap.sh --dry-run
#   ./ema_populate_redcap.sh --first-run      (only when no EMA data exists yet)
#   ./ema_populate_redcap.sh --today=2026-11-02 --seed=101   (testing)
set -euo pipefail

CWD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${CWD}/../.."
CONFIG_DIR="${BASE_DIR}/config"
DATA_DIR="${BASE_DIR}/examples"   # screening CSV and the four EMA event CSVs
OUT_DIR="${BASE_DIR}/output"      # import files are written here

# Relative output_csv paths in the config land here, check to make sure config has the same path defined.
mkdir -p "${OUT_DIR}"
cd "${OUT_DIR}"

echo "Populating REDCap EMA"
python -m ema_scheduler_redcap.ema_populate_redcap -v "$@" \
    "${DATA_DIR}/redcap__scr.csv" \
    "${CONFIG_DIR}/ema_config.yaml"