#!/bin/bash
# ============================================================
# Installa il Claude Workspace Autosave come LaunchAgent
# Usa StartInterval di launchd (non loop bash) per chiamare
# workspace-manager.py save periodicamente.
#
# Uso:
#   ./install-autosave.sh          # default: ogni 5 minuti
#   ./install-autosave.sh 10       # ogni 10 minuti
# ============================================================

set -euo pipefail

INTERVAL_MIN="${1:-5}"
INTERVAL_SEC=$((INTERVAL_MIN * 60))
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.claude.workspace-autosave"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
SAVE_SCRIPT="$SCRIPT_DIR/autosave-run.sh"

# Crea lo script che launchd chiamera' ogni N minuti
cat > "$SAVE_SCRIPT" << 'SAVESCRIPT'
#!/bin/bash
# Chiamato dal LaunchAgent ogni N minuti
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSAVE_DIR="$SCRIPT_DIR/workspaces/_autosave"
LOG="/tmp/claude-workspace-autosave.log"
KEEP=12

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# Verifica che Terminal.app sia attivo e raggiungibile
if ! pgrep -q "Terminal"; then
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
SAVESCRIPT

chmod +x "$SAVE_SCRIPT"

# Ferma se già in esecuzione
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Il trucco: usiamo ProcessType=Interactive e AquaSessionID/LegacyTimers
# per garantire accesso alla GUI (osascript → Terminal.app)
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SAVE_SCRIPT}</string>
    </array>
    <key>StartInterval</key>
    <integer>${INTERVAL_SEC}</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>/tmp/claude-workspace-autosave.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/claude-workspace-autosave.log</string>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH"

echo "Autosave installato:"
echo "  Intervallo: ogni ${INTERVAL_MIN} minuti"
echo "  Plist: $PLIST_PATH"
echo "  Log: tail -f /tmp/claude-workspace-autosave.log"
echo ""
echo "Test immediato:"
echo "  bash $SAVE_SCRIPT"
echo ""
echo "Comandi:"
echo "  Stop:    launchctl unload $PLIST_PATH"
echo "  Rimuovi: ./uninstall-autosave.sh"

# Test immediato per verificare che funzioni
echo ""
echo "Test in corso..."
if bash "$SAVE_SCRIPT" 2>&1; then
    latest=$(ls -t "$SCRIPT_DIR/workspaces/_autosave/" 2>/dev/null | head -1)
    if [ -n "$latest" ]; then
        echo "Test OK — salvato: $latest"
    else
        echo "ATTENZIONE: il salvataggio potrebbe non essere riuscito."
        echo "Se appare un popup di autorizzazione per Terminal.app, concedilo."
        echo "Poi riesegui: bash $SAVE_SCRIPT"
    fi
else
    echo "Test fallito — controlla /tmp/claude-workspace-autosave.log"
fi
