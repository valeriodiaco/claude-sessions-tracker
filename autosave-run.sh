#!/bin/bash
# Chiamato dal LaunchAgent ogni N minuti
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSAVE_DIR="$SCRIPT_DIR/workspaces/_autosave"
LOG="/tmp/claude-workspace-autosave.log"
KEEP=12

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# Verifica che Terminal.app sia attivo e raggiungibile
# (pgrep puo' fallire in contesti sandbox, usiamo ps come fallback)
if ! pgrep -q "Terminal" 2>/dev/null && ! ps aux | grep -q "[T]erminal.app"; then
    log "Terminal.app non attivo, skip"
    exit 0
fi

mkdir -p "$AUTOSAVE_DIR"
name="auto_$(date '+%Y%m%d_%H%M%S')"

if python3 "$SCRIPT_DIR/workspace-manager.py" save "$name" >> "$LOG" 2>&1; then
    [ -d "$SCRIPT_DIR/workspaces/$name" ] && mv "$SCRIPT_DIR/workspaces/$name" "$AUTOSAVE_DIR/$name"
    log "OK — $name"
else
    log "ERRORE"
fi

# Pulizia vecchi
ls -dt "$AUTOSAVE_DIR"/auto_* 2>/dev/null | tail -n +$((KEEP + 1)) | while read old; do
    rm -rf "$old"
done
