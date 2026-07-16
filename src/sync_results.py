#!/bin/bash
# sync_results.sh — Automatically pull simulation results from the cluster
#
# Put this on your LOCAL machine (not the cluster).
# It rsyncs the entire runs/ tree, only downloading new/changed files.
#
# Usage:
#   ./sync_results.sh              # run once manually
#   ./sync_results.sh --watch      # keep running, sync every 5 minutes
#   ./sync_results.sh --watch 10   # keep running, sync every 10 minutes
#
# To auto-run on boot / in background:
#   crontab -e
#   */5 * * * * /home/pravega2/Documents/Piezo-LLM/scripts/sync_results.sh >> /home/pravega2/Documents/Piezo-LLM/sync.log 2>&1

# ── Configuration ──
CLUSTER_USER="cyz218376"
CLUSTER_HOST="pragya.iitd.ac.in"
REMOTE_RUNS_DIR="~/himesh_work/testing/runs/"
LOCAL_SIMS_DIR="/home/pravega2/Documents/Piezo-LLM/simulations/"

# ── Sync function ──
do_sync() {
    echo ""
    echo "$(date '+%Y-%m-%d %H:%M:%S') — Syncing results..."
    
    rsync -avz --progress \
        "${CLUSTER_USER}@${CLUSTER_HOST}:${REMOTE_RUNS_DIR}" \
        "${LOCAL_SIMS_DIR}"
    
    if [ $? -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') — Sync complete."
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') — Sync failed (network issue? VPN?)."
    fi
}

# ── Main ──
if [ "$1" = "--watch" ]; then
    INTERVAL="${2:-5}"  # default 5 minutes
    echo "Watching for new results every ${INTERVAL} minutes..."
    echo "Press Ctrl+C to stop."
    while true; do
        do_sync
        echo "Next sync in ${INTERVAL} minutes..."
        sleep $(( INTERVAL * 60 ))
    done
else
    do_sync
fi