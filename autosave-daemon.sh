#!/bin/bash
# ============================================================
# Claude Workspace Autosave Daemon
#
# Salva il workspace ogni N minuti in background.
# I salvataggi automatici vanno in workspaces/_autosave/
# I salvataggi manuali restano in workspaces/<nome>/
#
# Uso:
#   ./autosave-daemon.sh                  # ogni 5 minuti (default)
#   ./autosave-daemon.sh 10               # ogni 10 minuti
#   ./autosave-daemon.sh --once           # salva una volta ed esci
#
# Come LaunchAgent (auto-start al login):
#   ./install-autosave.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_MGR="$SCRIPT_DIR/workspace-manager.py"
AUTOSAVE_DIR="$SCRIPT_DIR/workspaces/_autosave"
LOG_FILE="/tmp/claude-workspace-autosave.log"
INTERVAL="${1:-5}"  # minuti
KEEP_LAST=12        # tiene gli ultimi 12 snapshot (= 1 ora a 5min)

# Se --once, salva e esci
if [ "${1:-}" = "--once" ]; then
    mkdir -p "$AUTOSAVE_DIR"
    name="auto_$(date '+%Y%m%d_%H%M%S')"
    python3 "$WORKSPACE_MGR" save "$name" > "$LOG_FILE" 2>&1
    # Sposta nella cartella autosave
    if [ -d "$SCRIPT_DIR/workspaces/$name" ]; then
        mv "$SCRIPT_DIR/workspaces/$name" "$AUTOSAVE_DIR/$name"
    fi
    echo "[$(date '+%H:%M:%S')] Autosave: $name"
    exit 0
fi

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log "Autosave daemon avviato — intervallo: ${INTERVAL}min, mantiene ultimi $KEEP_LAST"

while true; do
    # Verifica che Terminal.app sia in esecuzione
    if ! pgrep -q "Terminal"; then
        log "Terminal.app non attivo, skip"
        sleep $((INTERVAL * 60))
        continue
    fi

    # Conta le finestre Terminal attive
    win_count=$(osascript -e 'tell application "Terminal" to count of windows' 2>/dev/null || echo "0")
    if [ "$win_count" -lt 2 ]; then
        log "Solo $win_count finestre, skip"
        sleep $((INTERVAL * 60))
        continue
    fi

    # Salva
    mkdir -p "$AUTOSAVE_DIR"
    name="auto_$(date '+%Y%m%d_%H%M%S')"

    if python3 "$WORKSPACE_MGR" save "$name" >> "$LOG_FILE" 2>&1; then
        # Sposta nella cartella autosave
        if [ -d "$SCRIPT_DIR/workspaces/$name" ]; then
            mv "$SCRIPT_DIR/workspaces/$name" "$AUTOSAVE_DIR/$name"
        fi
        log "OK — $name ($win_count finestre)"
    else
        log "ERRORE nel salvataggio"
    fi

    # Pulizia: tieni solo gli ultimi N
    ls -dt "$AUTOSAVE_DIR"/auto_* 2>/dev/null | tail -n +$((KEEP_LAST + 1)) | while read old; do
        rm -rf "$old"
        log "Rimosso vecchio: $(basename "$old")"
    done

    sleep $((INTERVAL * 60))
done
