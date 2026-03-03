#!/bin/bash
PLIST_PATH="$HOME/Library/LaunchAgents/com.claude.workspace-autosave.plist"
launchctl unload "$PLIST_PATH" 2>/dev/null
rm -f "$PLIST_PATH"
echo "Autosave rimosso."
