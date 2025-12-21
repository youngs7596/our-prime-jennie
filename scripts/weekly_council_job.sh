#!/bin/bash

# ==============================================================================
# Weekly Council Cron Job Helper
# ------------------------------------------------------------------------------
# Orchestrates the 3 Sages Council Workflow (Weekly Cadence):
# 1. Jennie (Data Sage): Build Weekly Packet (aggregates last 5 trading days)
# 2. Junho (Strategy Sage): Analyze Packet & Create Review/Patch Bundle
#
# Schedule: Run every Friday at 18:00 KST
# Crontab: 0 18 * * 5 /path/to/weekly_council_job.sh
# ==============================================================================

# Configuration
PROJECT_ROOT="/home/youngs75/projects/carbon-silicons-council"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python3"
LOG_DIR="$PROJECT_ROOT/logs/council"
WEEK=$(date +%Y-W%V)  # ISO Week number (e.g., 2025-W51)

# Ensure Directories Exist
mkdir -p "$LOG_DIR"

echo "=============================================================================="
echo "🚀 [Weekly Council] Starting Job for $WEEK at $(date)"
echo "=============================================================================="

# 1. Build Weekly Packet (Jennie)
echo ">> [Step 1] Running Jennie (Data Sage) - Building Weekly Packet..."
PACKET_FILE="$PROJECT_ROOT/runs/$WEEK/weekly_packet.json"
LOG_FILE_JENNIE="$LOG_DIR/build_packet_$WEEK.log"

mkdir -p "$PROJECT_ROOT/runs/$WEEK"

$VENV_PYTHON "$PROJECT_ROOT/scripts/build_weekly_packet.py" \
    --output "$PACKET_FILE" \
    >> "$LOG_FILE_JENNIE" 2>&1

if [ $? -ne 0 ]; then
    echo "❌ [Error] Jennie Failed! Check log: $LOG_FILE_JENNIE"
    exit 1
fi
echo "✅ Jennie Completed. Packet saved to $PACKET_FILE"

# 2. Run Weekly Council (Junho)
echo ">> [Step 2] Running Junho (Strategy Sage)..."
OUTPUT_DIR="$PROJECT_ROOT/reviews/$WEEK"
LOG_FILE_JUNHO="$LOG_DIR/run_council_$WEEK.log"

mkdir -p "$OUTPUT_DIR"

$VENV_PYTHON "$PROJECT_ROOT/scripts/run_weekly_council.py" \
    --input "$PACKET_FILE" \
    --output-dir "$OUTPUT_DIR" \
    >> "$LOG_FILE_JUNHO" 2>&1

if [ $? -ne 0 ]; then
    echo "❌ [Error] Junho Failed! Check log: $LOG_FILE_JUNHO"
    exit 1
fi

echo "✅ Junho Completed. Review saved to $OUTPUT_DIR"
echo "=============================================================================="
echo "✨ [Weekly Council] All Steps Completed Successfully at $(date)"
echo "👉 Next Step: Review $OUTPUT_DIR/junho_review.json and run apply_patch_bundle.py if needed."
echo "=============================================================================="
