#!/usr/bin/env python3
"""
Claude Code Workspace Manager

Saves and restores the full Terminal.app workspace:
- Window positions, sizes
- Claude Code sessions (matched via TTY → PID → session ID)
- Non-Claude processes (watchdog, monitors, scripts)
- Generates restore script with AppleScript for exact window recreation

Usage:
    python3 workspace-manager.py save [name]        # Save current workspace
    python3 workspace-manager.py restore [name]     # Restore workspace
    python3 workspace-manager.py list               # List saved workspaces
    python3 workspace-manager.py status             # Show current window/session state
"""

import json
import os
import re
import subprocess
import sys
import glob
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORKSPACES_DIR = SCRIPT_DIR / "workspaces"
CLAUDE_PROJECTS_DIRS = []

# Find all Claude config dirs
for d in glob.glob(os.path.expanduser("~/.claude*/projects")):
    if os.path.isdir(d):
        CLAUDE_PROJECTS_DIRS.append(d)


def run_osascript(script: str) -> str:
    """Run AppleScript and return output."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def run_cmd(cmd: list[str], timeout=10) -> str:
    """Run shell command and return output."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def get_terminal_windows() -> list[dict]:
    """Get all Terminal.app windows with position, size, TTY, processes, custom title."""
    script = '''
tell application "Terminal"
    set output to ""
    repeat with i from 1 to count of windows
        set w to window i
        try
            set t to selected tab of w
            set wPos to position of w
            set wSize to size of w
            set wName to name of w
            set tTTY to tty of t
            set tBusy to busy of t
            set tProcs to processes of t as text
            set tTitle to custom title of t
            set output to output & "WIN_START" & return
            set output to output & "INDEX:" & i & return
            set output to output & "POS_X:" & item 1 of wPos & return
            set output to output & "POS_Y:" & item 2 of wPos & return
            set output to output & "SIZE_W:" & item 1 of wSize & return
            set output to output & "SIZE_H:" & item 2 of wSize & return
            set output to output & "TTY:" & tTTY & return
            set output to output & "BUSY:" & tBusy & return
            set output to output & "PROCS:" & tProcs & return
            set output to output & "TITLE:" & tTitle & return
            set output to output & "WNAME:" & wName & return
            set output to output & "WIN_END" & return
        end try
    end repeat
    return output
end tell
'''
    raw = run_osascript(script)
    windows = []
    current = {}

    for line in raw.split('\n'):
        line = line.strip()
        if line == "WIN_START":
            current = {}
        elif line == "WIN_END":
            if current:
                windows.append(current)
        elif ':' in line:
            key, _, val = line.partition(':')
            current[key.strip()] = val.strip()

    # Parse into structured data
    result = []
    for w in windows:
        result.append({
            "index": int(w.get("INDEX", 0)),
            "pos_x": int(w.get("POS_X", 0)),
            "pos_y": int(w.get("POS_Y", 0)),
            "size_w": int(w.get("SIZE_W", 800)),
            "size_h": int(w.get("SIZE_H", 600)),
            "tty": w.get("TTY", ""),
            "busy": w.get("BUSY", "false") == "true",
            "processes": w.get("PROCS", ""),
            "custom_title": w.get("TITLE", ""),
            "window_name": w.get("WNAME", ""),
        })

    return result


def get_claude_processes() -> dict:
    """Get all running claude processes mapped by TTY."""
    raw = run_cmd(["ps", "-eo", "pid,tty,comm"])
    procs = {}
    for line in raw.split('\n'):
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "claude":
            pid = parts[0]
            tty = parts[1]
            if tty != "??":
                procs[tty] = pid
    return procs


def get_non_claude_commands() -> dict:
    """Get the full command line for non-claude busy terminals (watchdog, monitors, etc.)."""
    raw = run_cmd(["ps", "-eo", "pid,tty,args"], timeout=5)
    commands = {}
    for line in raw.split('\n'):
        parts = line.split(None, 2)
        if len(parts) >= 3:
            pid, tty, cmd = parts
            if tty != "??" and "claude" not in cmd.split()[0]:
                if tty not in commands:
                    commands[tty] = []
                commands[tty].append({"pid": pid, "cmd": cmd})
    return commands


def get_active_sessions() -> list[dict]:
    """Get all active Claude Code sessions from JSONL files (last 6 hours)."""
    jsonl_files = []
    for proj_dir in CLAUDE_PROJECTS_DIRS:
        result = subprocess.run(
            ["find", proj_dir, "-maxdepth", "2", "-name", "*.jsonl",
             "-not", "-path", "*/subagents/*", "-mmin", "-360", "-size", "+1k"],
            capture_output=True, text=True
        )
        jsonl_files.extend(f for f in result.stdout.strip().split('\n') if f)

    sessions = []
    for f in jsonl_files:
        try:
            session_id = ""
            cwd = ""
            first_msg = ""
            last_msg = ""
            msg_count = 0
            mtime = os.path.getmtime(f)

            with open(f) as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                        msg_type = obj.get('type', '')

                        if msg_type == 'user':
                            msg_count += 1
                            if not session_id:
                                session_id = obj.get('sessionId', '')
                                cwd = obj.get('cwd', '')

                            message = obj.get('message', {})
                            content = message.get('content', '') if isinstance(message, dict) else ''
                            if not content:
                                content = obj.get('content', '')

                            text = ''
                            if isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        text = item['text'].strip().replace('\n', ' ')[:120]
                                        break
                            elif isinstance(content, str):
                                text = content.strip().replace('\n', ' ')[:120]

                            if text:
                                if not first_msg:
                                    first_msg = text
                                last_msg = text

                        elif msg_type == 'assistant':
                            msg_count += 1

                    except (json.JSONDecodeError, KeyError):
                        pass

            if session_id:
                sessions.append({
                    "session_id": session_id,
                    "cwd": cwd,
                    "first_msg": first_msg or "(vuoto)",
                    "last_msg": last_msg or "(vuoto)",
                    "messages": msg_count,
                    "file": f,
                    "mtime": mtime,
                    "size_kb": os.path.getsize(f) // 1024,
                })
        except Exception:
            pass

    return sessions


def match_windows_to_sessions(windows, claude_procs, sessions):
    """Match Terminal windows to Claude sessions via TTY."""
    # Build session lookup by cwd for fallback matching
    sessions_by_cwd = {}
    for s in sessions:
        if s["cwd"] not in sessions_by_cwd:
            sessions_by_cwd[s["cwd"]] = []
        sessions_by_cwd[s["cwd"]].append(s)

    # Sort sessions by mtime desc within each cwd group
    for cwd in sessions_by_cwd:
        sessions_by_cwd[cwd].sort(key=lambda x: x["mtime"], reverse=True)

    matched = []
    used_sessions = set()

    for w in windows:
        tty_short = w["tty"].replace("/dev/", "")
        has_claude = tty_short in claude_procs
        is_claude_window = "claude" in w["processes"].lower() and has_claude

        entry = {
            "window": w,
            "type": "unknown",
            "session": None,
            "command": None,
        }

        if is_claude_window:
            entry["type"] = "claude"
            # Find best matching session
            # Strategy: most recently modified session for this cwd
            # that hasn't been matched yet
            best_session = None

            # Try to match by cwd
            for s in sessions:
                if s["session_id"] not in used_sessions:
                    # Direct match
                    if not best_session or s["mtime"] > best_session["mtime"]:
                        best_session = s

            # If we found a session, use the most recent unmatched one
            # But try to narrow by window title/name
            title = w.get("custom_title", "") + " " + w.get("window_name", "")
            for s in sessions:
                if s["session_id"] not in used_sessions:
                    # Check if cwd folder name appears in window title
                    cwd_last = os.path.basename(s["cwd"]) if s["cwd"] else ""
                    if cwd_last and cwd_last.lower() in title.lower():
                        best_session = s
                        break

            if best_session:
                entry["session"] = best_session
                used_sessions.add(best_session["session_id"])

        elif not w["busy"]:
            entry["type"] = "idle_shell"
        else:
            # Non-claude busy process (watchdog, monitor, etc.)
            entry["type"] = "script"
            # Extract the meaningful command from processes
            procs = w["processes"]
            if "bash" in procs and "sleep" in procs:
                entry["type"] = "monitor_script"
            elif "watchdog" in w["window_name"].lower():
                entry["type"] = "watchdog"

        matched.append(entry)

    return matched


def save_workspace(name: str = None):
    """Save the current workspace state."""
    if not name:
        name = datetime.now().strftime("%Y%m%d_%H%M%S")

    ws_dir = WORKSPACES_DIR / name
    ws_dir.mkdir(parents=True, exist_ok=True)

    print(f"Salvando workspace: {name}\n")

    # Collect data
    print("  Scansione finestre Terminal.app...")
    windows = get_terminal_windows()
    print(f"  {len(windows)} finestre trovate")

    print("  Scansione processi Claude...")
    claude_procs = get_claude_processes()
    print(f"  {len(claude_procs)} processi claude attivi")

    print("  Scansione sessioni JSONL...")
    sessions = get_active_sessions()
    print(f"  {len(sessions)} sessioni recenti")

    print("  Correlazione finestre ↔ sessioni...")
    matched = match_windows_to_sessions(windows, claude_procs, sessions)

    claude_count = sum(1 for m in matched if m["type"] == "claude")
    script_count = sum(1 for m in matched if m["type"] in ("script", "monitor_script", "watchdog"))
    idle_count = sum(1 for m in matched if m["type"] == "idle_shell")
    print(f"  Claude: {claude_count} | Script: {script_count} | Idle: {idle_count}")

    # ---- Save workspace JSON ----
    workspace_data = {
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(),
        "total_windows": len(windows),
        "claude_sessions": claude_count,
        "entries": []
    }

    for m in matched:
        w = m["window"]
        entry = {
            "type": m["type"],
            "pos_x": w["pos_x"],
            "pos_y": w["pos_y"],
            "size_w": w["size_w"],
            "size_h": w["size_h"],
            "custom_title": w["custom_title"],
            "window_name": w["window_name"],
            "tty": w["tty"],
        }

        if m["session"]:
            s = m["session"]
            entry["session_id"] = s["session_id"]
            entry["cwd"] = s["cwd"]
            entry["first_msg"] = s["first_msg"]
            entry["last_msg"] = s["last_msg"]
            entry["messages"] = s["messages"]
            entry["size_kb"] = s["size_kb"]

        workspace_data["entries"].append(entry)

    with open(ws_dir / "workspace.json", "w") as f:
        json.dump(workspace_data, f, indent=2, ensure_ascii=False)

    # ---- Generate restore.sh ----
    restore_lines = [
        '#!/bin/bash',
        '# ============================================================',
        f'# Workspace Restore: {name}',
        f'# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'# Windows: {len(matched)} | Claude sessions: {claude_count}',
        '#',
        '# Usage:',
        '#   bash restore.sh              # restore tutto',
        '#   bash restore.sh --list       # mostra senza aprire',
        '#   bash restore.sh --claude     # solo sessioni Claude',
        '#   bash restore.sh 1 3 5        # solo finestre specifiche',
        '# ============================================================',
        '',
        'set -euo pipefail',
        '',
        'MODE="all"',
        'INDICES=()',
        'for arg in "$@"; do',
        '    case "$arg" in',
        '        --list|-l) MODE="list" ;;',
        '        --claude|-c) MODE="claude" ;;',
        '        [0-9]*) INDICES+=("$arg") ;;',
        '    esac',
        'done',
        '',
        'open_window() {',
        '    local x="$1" y="$2" w="$3" h="$4" cmd="$5" title="$6"',
        '    osascript << ASCRIPT',
        'tell application "Terminal"',
        '    activate',
        '    set newWin to do script "${cmd}"',
        '    set winObj to window 1',
        '    set position of winObj to {${x}, ${y}}',
        '    set size of winObj to {${w}, ${h}}',
        '    -- Set custom title',
        '    tell winObj',
        '        set custom title of selected tab to "${title}"',
        '    end tell',
        'end tell',
        'ASCRIPT',
        '    sleep 0.3',
        '}',
        '',
    ]

    # Add each window
    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = w["custom_title"] or w["window_name"] or f"Window {idx}"
        title_escaped = title.replace('"', '\\"').replace("'", "\\'")

        if m["type"] == "claude" and m["session"]:
            s = m["session"]
            # Escape single quotes in path for bash
            safe_cwd = s['cwd'].replace("'", "'\\''")
            cmd = f"cd '{safe_cwd}' && claude --resume {s['session_id']}"
            label = f"[CLAUDE] {title_escaped}"
            desc = f"{s['first_msg'][:60]}"
        elif m["type"] == "idle_shell":
            cwd = "/Users/v"  # default
            cmd = f"cd '{cwd}'"
            label = f"[SHELL] {title_escaped}"
            desc = "idle shell"
        else:
            label = f"[SCRIPT] {title_escaped}"
            cmd = "echo 'Manual restart needed for this window'"
            desc = w["processes"]

        # Use heredoc for CMD to avoid quoting issues with paths containing ()'"
        restore_lines.extend([
            f'# --- Window {idx}: {label} ---',
            f'# {desc}',
            f'W{idx}_TYPE="{m["type"]}"',
            f'W{idx}_X={w["pos_x"]}',
            f'W{idx}_Y={w["pos_y"]}',
            f'W{idx}_W={w["size_w"]}',
            f'W{idx}_H={w["size_h"]}',
            f'W{idx}_TITLE="{title_escaped}"',
            f'read -r -d \'\' W{idx}_CMD << \'CMDEOF\' || true',
            cmd,
            'CMDEOF',
            '',
        ])

    # Add restore logic
    total = len(matched)
    restore_lines.extend([
        f'TOTAL={total}',
        '',
        'if [ "$MODE" = "list" ]; then',
        '    echo "Workspace: ' + name + '"',
        f'    echo "Finestre: {total} ({claude_count} Claude, {script_count} script, {idle_count} idle)"',
        '    echo ""',
    ])

    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = w["custom_title"] or w["window_name"] or f"Window {idx}"
        stype = m["type"].upper()
        if m["session"]:
            restore_lines.append(
                f'    echo "  [{idx}] [{stype}] {title} — {m["session"]["first_msg"][:50]}"'
            )
        else:
            restore_lines.append(
                f'    echo "  [{idx}] [{stype}] {title}"'
            )

    restore_lines.extend([
        '    exit 0',
        'fi',
        '',
        'echo "Ripristino workspace: ' + name + '"',
        f'echo "{total} finestre da aprire..."',
        'echo ""',
        '',
        'OPENED=0',
    ])

    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = (w["custom_title"] or w["window_name"] or f"Window {idx}").replace('"', '\\"').replace("'", "\\'")

        cond_start = ""
        cond_end = ""

        if m["type"] == "claude":
            cond_start = 'if [ "$MODE" = "all" ] || [ "$MODE" = "claude" ]; then'
            cond_end = "fi"
        else:
            cond_start = 'if [ "$MODE" = "all" ]; then'
            cond_end = "fi"

        restore_lines.extend([
            f'# Window {idx}',
            'SKIP=false',
            'if [ ${{#INDICES[@]}} -gt 0 ]; then',
            '    SKIP=true',
            '    for i in "${INDICES[@]}"; do',
            f'        [ "$i" = "{idx}" ] && SKIP=false',
            '    done',
            'fi',
            f'{cond_start}',
            'if ! $SKIP; then',
            f'    echo "  [{idx}] Opening: {title}"',
            f'    open_window "$W{idx}_X" "$W{idx}_Y" "$W{idx}_W" "$W{idx}_H" "$W{idx}_CMD" "$W{idx}_TITLE"',
            '    OPENED=$((OPENED + 1))',
            'fi',
            f'{cond_end}',
            '',
        ])

    restore_lines.extend([
        'echo ""',
        'echo "Aperte $OPENED finestre"',
    ])

    with open(ws_dir / "restore.sh", "w") as f:
        f.write('\n'.join(restore_lines))
    os.chmod(ws_dir / "restore.sh", 0o755)

    # ---- Generate session_map.md for Obsidian ----
    md_lines = [
        '---',
        'class: session-map',
        'owner: v',
        'status: active',
        f'created: {datetime.now().strftime("%Y-%m-%d")}',
        f'updated: {datetime.now().isoformat()}',
        'tags: [claude-code, session-tracker, workspace-restore]',
        '---',
        '',
        f'# Workspace Map — {name}',
        '',
        f'> Salvato: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'> Finestre: {len(matched)} ({claude_count} Claude, {script_count} script, {idle_count} idle)',
        f'> Restore: `bash restore.sh`',
        '',
    ]

    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = w["custom_title"] or w["window_name"] or f"Window {idx}"
        pos = f"{w['pos_x']},{w['pos_y']}"
        size = f"{w['size_w']}x{w['size_h']}"

        if m["type"] == "claude" and m["session"]:
            s = m["session"]
            md_lines.extend([
                f'## {idx}. [{m["type"].upper()}] {title}',
                '',
                '| Campo | Valore |',
                '|-------|--------|',
                f'| **Session ID** | `{s["session_id"]}` |',
                f'| **Working dir** | `{s["cwd"]}` |',
                f'| **Primo msg** | {s["first_msg"][:80]} |',
                f'| **Ultimo msg** | {s["last_msg"][:80]} |',
                f'| **Messaggi** | {s["messages"]} |',
                f'| **Size** | {s["size_kb"]}KB |',
                f'| **Posizione** | {pos} |',
                f'| **Dimensione** | {size} |',
                '',
                '```bash',
                f'claude --resume {s["session_id"]}',
                '```',
                '',
                '---',
                '',
            ])
        else:
            md_lines.extend([
                f'## {idx}. [{m["type"].upper()}] {title}',
                '',
                f'- **Posizione:** {pos}',
                f'- **Dimensione:** {size}',
                f'- **Processi:** {w["processes"]}',
                '',
                '---',
                '',
            ])

    with open(ws_dir / "session_map.md", "w") as f:
        f.write('\n'.join(md_lines))

    print(f"\nWorkspace salvato in: {ws_dir}/")
    print(f"  restore.sh      — ripristina finestre con posizioni esatte")
    print(f"  session_map.md  — mappa per Obsidian")
    print(f"  workspace.json  — dati strutturati")


def list_workspaces():
    """List all saved workspaces."""
    if not WORKSPACES_DIR.exists():
        print("Nessun workspace salvato.")
        return

    print("Workspaces salvati:\n")
    for ws_dir in sorted(WORKSPACES_DIR.iterdir(), reverse=True):
        if ws_dir.is_dir() and (ws_dir / "workspace.json").exists():
            with open(ws_dir / "workspace.json") as f:
                data = json.load(f)
            print(f"  {ws_dir.name}")
            print(f"    Creato: {data.get('created', '?')}")
            print(f"    Finestre: {data.get('total_windows', '?')} | Claude: {data.get('claude_sessions', '?')}")
            print(f"    Restore: bash {ws_dir / 'restore.sh'}")
            print()


def show_status():
    """Show current workspace status."""
    windows = get_terminal_windows()
    claude_procs = get_claude_processes()
    sessions = get_active_sessions()
    matched = match_windows_to_sessions(windows, claude_procs, sessions)

    print(f"Terminal.app: {len(windows)} finestre")
    print(f"Claude processi: {len(claude_procs)}")
    print(f"Sessioni attive (6h): {len(sessions)}")
    print()

    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = w["custom_title"] or w["window_name"] or "?"
        stype = m["type"].upper()
        pos = f"({w['pos_x']},{w['pos_y']})"

        if m["session"]:
            sid = m["session"]["session_id"][:8]
            msg = m["session"]["first_msg"][:50]
            print(f"  [{idx:2d}] [{stype:8s}] {title:30s} {pos:15s} {sid}… {msg}")
        else:
            print(f"  [{idx:2d}] [{stype:8s}] {title:30s} {pos:15s}")


def restore_workspace(name: str = None):
    """Restore a workspace."""
    if not name:
        # Find most recent
        if not WORKSPACES_DIR.exists():
            print("Nessun workspace salvato.")
            return
        dirs = sorted(WORKSPACES_DIR.iterdir(), reverse=True)
        ws_dirs = [d for d in dirs if d.is_dir() and (d / "restore.sh").exists()]
        if not ws_dirs:
            print("Nessun workspace salvato.")
            return
        ws_dir = ws_dirs[0]
        name = ws_dir.name
    else:
        ws_dir = WORKSPACES_DIR / name

    restore_script = ws_dir / "restore.sh"
    if not restore_script.exists():
        print(f"Workspace '{name}' non trovato.")
        return

    print(f"Ripristino workspace: {name}")
    # Pass through any remaining args
    extra_args = sys.argv[3:] if len(sys.argv) > 3 else []
    os.execvp("bash", ["bash", str(restore_script)] + extra_args)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "save":
        save_workspace(arg)
    elif cmd == "restore":
        restore_workspace(arg)
    elif cmd == "list":
        list_workspaces()
    elif cmd == "status":
        show_status()
    else:
        print(__doc__)
