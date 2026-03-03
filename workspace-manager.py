#!/usr/bin/env python3
"""
Claude Code Workspace Manager — Full Terminal.app state save/restore.

Captures and restores:
- Window positions and sizes (exact pixel coordinates)
- Claude Code sessions (matched via TTY → PID → session ID)
- Non-Claude processes (watchdog, monitors, automation scripts) with full commands
- Window custom titles (from /rename)
- Terminal.app profile per window

Usage:
    python3 workspace-manager.py save [name]        # Save current workspace
    python3 workspace-manager.py restore [name]     # Restore workspace (latest if no name)
    python3 workspace-manager.py restore --claude    # Restore only Claude sessions
    python3 workspace-manager.py restore --list      # Show without restoring
    python3 workspace-manager.py list                # List saved workspaces
    python3 workspace-manager.py status              # Show live window/session state
    python3 workspace-manager.py diff [name]         # Compare current state with saved workspace
"""

import json
import os
import re
import subprocess
import sys
import glob
import shlex
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORKSPACES_DIR = SCRIPT_DIR / "workspaces"

# Find all Claude config dirs (multi-account)
CLAUDE_CONFIG_DIRS = sorted(glob.glob(os.path.expanduser("~/.claude*/projects")))
CLAUDE_CONFIG_DIRS = [d for d in CLAUDE_CONFIG_DIRS if os.path.isdir(d)]


# ============================================================
# Data collection
# ============================================================

def run_osascript(script: str) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def run_cmd(cmd: list[str], timeout=10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def get_terminal_windows() -> list[dict]:
    """Get all Terminal.app windows via AppleScript: position, size, TTY, title, profile."""
    script = '''
tell application "Terminal"
    set output to ""
    repeat with i from 1 to count of windows
        set w to window i
        try
            set t to selected tab of w
            set wPos to position of w
            set wSize to size of w
            set tTTY to tty of t
            set tBusy to busy of t
            set tProcs to processes of t as text
            set tTitle to custom title of t
            set wName to name of w
            set tProfile to current settings of t
            set profileName to name of tProfile
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
            set output to output & "PROFILE:" & profileName & return
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
        elif line == "WIN_END" and current:
            windows.append(current)
        elif ':' in line:
            key, _, val = line.partition(':')
            current[key.strip()] = val.strip()

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
            "profile": w.get("PROFILE", "Basic"),
        })

    return result


def get_claude_pids_by_tty() -> dict[str, str]:
    """Map TTY → claude PID."""
    raw = run_cmd(["ps", "-eo", "pid,tty,comm"])
    result = {}
    for line in raw.split('\n'):
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "claude":
            tty = parts[1].strip()
            if tty != "??":
                result[tty] = parts[0].strip()
    return result


def get_leaf_command_for_tty(tty_name: str) -> dict:
    """Get the deepest (leaf) command running on a TTY — the actual user-facing process."""
    raw = run_cmd(["ps", "-t", tty_name, "-o", "pid,ppid,args"])
    lines = raw.strip().split('\n')[1:]  # skip header

    if not lines:
        return {"cmd": "", "pid": "", "cwd": ""}

    # Build process tree
    procs = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 3:
            procs.append({"pid": parts[0], "ppid": parts[1], "cmd": parts[2]})
        elif len(parts) == 2:
            procs.append({"pid": parts[0], "ppid": parts[1], "cmd": ""})

    # Find leaf processes (PIDs that are not anyone's parent)
    all_pids = {p["pid"] for p in procs}
    parent_pids = {p["ppid"] for p in procs}
    leaf_pids = all_pids - parent_pids

    # Get the most interesting leaf (not sleep, not login)
    for p in reversed(procs):
        if p["pid"] in leaf_pids:
            cmd = p["cmd"]
            if cmd and not cmd.startswith("sleep") and not cmd.startswith("login"):
                return p

    # Fallback: last non-login process
    for p in reversed(procs):
        cmd = p["cmd"]
        if cmd and not cmd.startswith("login") and not cmd.startswith("-zsh"):
            return p

    return procs[-1] if procs else {"cmd": "", "pid": "", "cwd": ""}


def get_script_command_for_tty(tty_name: str) -> str:
    """Get the meaningful script command running on a TTY (for non-Claude windows).
    Returns the bash/script invocation, not the sleep or login."""
    raw = run_cmd(["ps", "-t", tty_name, "-o", "pid,ppid,args"])
    lines = raw.strip().split('\n')[1:]

    commands = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 3:
            cmd = parts[2]
            # Skip infrastructure processes
            if any(cmd.startswith(skip) for skip in ["login", "-zsh", "sleep"]):
                continue
            # Skip the bare claude process itself (we handle it separately)
            if cmd.strip() in ("claude", "claude "):
                continue
            commands.append(cmd)

    # Return the most meaningful command (usually a bash script or the main process)
    for cmd in commands:
        if "bash" in cmd or ".sh" in cmd or "python" in cmd or "node" in cmd:
            return cmd
    return commands[0] if commands else ""


def get_active_sessions(hours: int = 6) -> list[dict]:
    """Get all active Claude Code sessions from JSONL files."""
    jsonl_files = []
    for proj_dir in CLAUDE_CONFIG_DIRS:
        result = subprocess.run(
            ["find", proj_dir, "-maxdepth", "2", "-name", "*.jsonl",
             "-not", "-path", "*/subagents/*", "-mmin", f"-{hours * 60}", "-size", "+1k"],
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
            user_count = 0
            assistant_count = 0
            mtime = os.path.getmtime(f)

            with open(f) as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                        msg_type = obj.get('type', '')

                        if msg_type == 'user':
                            user_count += 1
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
                            assistant_count += 1

                    except (json.JSONDecodeError, KeyError):
                        pass

            if session_id:
                sessions.append({
                    "session_id": session_id,
                    "cwd": cwd,
                    "first_msg": first_msg or "(vuoto)",
                    "last_msg": last_msg or "(vuoto)",
                    "messages": user_count + assistant_count,
                    "user_messages": user_count,
                    "file": f,
                    "mtime": mtime,
                    "size_kb": os.path.getsize(f) // 1024,
                })
        except Exception:
            pass

    # Sort by most recent first
    sessions.sort(key=lambda x: x["mtime"], reverse=True)
    return sessions


# ============================================================
# Matching: Window ↔ Session
# ============================================================

def match_windows_to_sessions(windows, claude_pids, sessions):
    """Match Terminal windows to Claude sessions using multiple heuristics."""
    used_sessions = set()

    # Build lookup indices
    sessions_by_cwd = {}
    for s in sessions:
        sessions_by_cwd.setdefault(s["cwd"], []).append(s)

    matched = []

    for w in windows:
        tty_short = w["tty"].replace("/dev/", "")
        has_claude = tty_short in claude_pids
        procs_lower = w["processes"].lower()
        is_claude_window = "claude" in procs_lower and has_claude

        entry = {
            "window": w,
            "type": "unknown",
            "session": None,
            "command": "",
            "restartable": False,
        }

        if is_claude_window:
            entry["type"] = "claude"
            entry["restartable"] = True

            # Match session using multiple heuristics
            best_session = None
            best_score = -1

            title = (w.get("custom_title", "") + " " + w.get("window_name", "")).lower()

            for s in sessions:
                if s["session_id"] in used_sessions:
                    continue

                score = 0

                # Heuristic 1: cwd folder name in window title (strong signal)
                cwd_parts = s["cwd"].split("/")
                for part in cwd_parts:
                    if len(part) > 3 and part.lower() in title:
                        score += 10

                # Heuristic 2: session name keywords in title
                first_words = s["first_msg"].lower().split()[:5]
                for word in first_words:
                    if len(word) > 4 and word in title:
                        score += 5

                # Heuristic 3: recency (more recent = higher score, minor factor)
                score += s["mtime"] / 1e12  # tiny bonus for recency

                if score > best_score:
                    best_score = score
                    best_session = s

            if best_session:
                entry["session"] = best_session
                entry["command"] = f"cd {shlex.quote(best_session['cwd'])} && claude --resume {best_session['session_id']}"
                used_sessions.add(best_session["session_id"])

        elif not w["busy"]:
            entry["type"] = "idle_shell"
            entry["restartable"] = True
            entry["command"] = "# idle shell"

        else:
            # Non-Claude busy process — capture the actual command
            script_cmd = get_script_command_for_tty(tty_short)

            if "watchdog" in (script_cmd + w["window_name"]).lower():
                entry["type"] = "watchdog"
            elif "monitor" in (script_cmd + w["window_name"]).lower():
                entry["type"] = "monitor"
            elif "automation" in (script_cmd + w["window_name"]).lower() or "overnight" in script_cmd.lower():
                entry["type"] = "automation"
            else:
                entry["type"] = "script"

            entry["command"] = script_cmd
            entry["restartable"] = bool(script_cmd)

        matched.append(entry)

    return matched


# ============================================================
# Save workspace
# ============================================================

def save_workspace(name: str = None):
    if not name:
        name = datetime.now().strftime("%Y%m%d_%H%M%S")

    ws_dir = WORKSPACES_DIR / name
    ws_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Salvando workspace: {name}\n")

    # Collect all data
    print("  [1/4] Scansione finestre Terminal.app...")
    windows = get_terminal_windows()
    print(f"         {len(windows)} finestre")

    print("  [2/4] Scansione processi Claude...")
    claude_pids = get_claude_pids_by_tty()
    print(f"         {len(claude_pids)} processi claude")

    print("  [3/4] Scansione sessioni JSONL...")
    sessions = get_active_sessions(hours=8)
    print(f"         {len(sessions)} sessioni recenti")

    print("  [4/4] Correlazione finestre <-> sessioni...")
    matched = match_windows_to_sessions(windows, claude_pids, sessions)

    counts = {"claude": 0, "watchdog": 0, "monitor": 0, "automation": 0, "script": 0, "idle_shell": 0}
    for m in matched:
        t = m["type"]
        counts[t] = counts.get(t, 0) + 1

    print(f"         Claude: {counts['claude']} | Watchdog: {counts['watchdog']} | "
          f"Monitor: {counts['monitor']} | Automation: {counts['automation']} | "
          f"Script: {counts['script']} | Idle: {counts['idle_shell']}")

    # ---- workspace.json ----
    workspace_data = {
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(),
        "machine": os.uname().nodename,
        "total_windows": len(windows),
        "counts": counts,
        "config_dirs": CLAUDE_CONFIG_DIRS,
        "entries": [],
    }

    for m in matched:
        w = m["window"]
        entry = {
            "type": m["type"],
            "restartable": m["restartable"],
            "command": m["command"],
            "pos_x": w["pos_x"],
            "pos_y": w["pos_y"],
            "size_w": w["size_w"],
            "size_h": w["size_h"],
            "custom_title": w["custom_title"],
            "window_name": w["window_name"],
            "profile": w["profile"],
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

    # ---- restore.sh ----
    _generate_restore_script(ws_dir, name, matched, counts)

    # ---- session_map.md ----
    _generate_obsidian_map(ws_dir, name, matched, counts)

    print(f"\n  Workspace salvato: {ws_dir}/")
    print(f"    restore.sh       — ripristina finestre con posizioni esatte")
    print(f"    session_map.md   — mappa sessioni per Obsidian")
    print(f"    workspace.json   — dati strutturati per automazione")
    print(f"\n  Totale: {len(matched)} finestre salvate\n")


def _generate_restore_script(ws_dir: Path, name: str, matched: list, counts: dict):
    """Generate the restore.sh script with AppleScript window management."""
    lines = [
        '#!/bin/bash',
        '# ============================================================',
        f'# Workspace Restore: {name}',
        f'# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'# Windows: {len(matched)} | Claude: {counts.get("claude", 0)} | '
        f'Scripts: {counts.get("watchdog", 0) + counts.get("monitor", 0) + counts.get("automation", 0) + counts.get("script", 0)}',
        '#',
        '# Usage:',
        '#   bash restore.sh              # ripristina tutto',
        '#   bash restore.sh --list       # mostra senza aprire',
        '#   bash restore.sh --claude     # solo sessioni Claude',
        '#   bash restore.sh --scripts    # solo watchdog/monitor/automation',
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
        '        --scripts|-s) MODE="scripts" ;;',
        '        [0-9]*) INDICES+=("$arg") ;;',
        '    esac',
        'done',
        '',
        '# Open a new Terminal.app window at exact position and size',
        'open_window() {',
        '    local x="$1" y="$2" w="$3" h="$4" title="$5" profile="$6"',
        '    shift 6',
        '    local cmd="$*"',
        '',
        '    osascript << EOF',
        'tell application "Terminal"',
        '    activate',
        '    set newTab to do script "${cmd}"',
        '    delay 0.2',
        '    set winObj to window 1',
        '    set position of winObj to {${x}, ${y}}',
        '    set size of winObj to {${w}, ${h}}',
        '    tell winObj',
        '        set custom title of selected tab to "${title}"',
        '    end tell',
        'end tell',
        'EOF',
        '    sleep 0.4',
        '}',
        '',
    ]

    # Define all windows
    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = (w["custom_title"] or w["window_name"] or f"Window {idx}")
        title_safe = title.replace('"', '\\"').replace("'", "")
        profile = w.get("profile", "Basic")
        cmd = m.get("command", "")
        wtype = m["type"]

        lines.append(f'# --- [{idx}] [{wtype.upper()}] {title_safe} ---')

        if wtype == "claude" and m["session"]:
            s = m["session"]
            safe_cwd = shlex.quote(s["cwd"])
            lines.append(f'W{idx}_TYPE="claude"')
            lines.append(f'W{idx}_CMD="cd {safe_cwd} && claude --resume {s["session_id"]}"')
            lines.append(f'W{idx}_DESC="{s["first_msg"][:60].replace(chr(34), "")}"')
        elif wtype == "idle_shell":
            lines.append(f'W{idx}_TYPE="idle"')
            lines.append(f'W{idx}_CMD=""')
            lines.append(f'W{idx}_DESC="idle shell"')
        else:
            cmd_safe = cmd.replace('"', '\\"')
            lines.append(f'W{idx}_TYPE="{wtype}"')
            lines.append(f'W{idx}_CMD="{cmd_safe}"')
            lines.append(f'W{idx}_DESC="{wtype}: {title_safe}"')

        lines.append(f'W{idx}_X={w["pos_x"]}')
        lines.append(f'W{idx}_Y={w["pos_y"]}')
        lines.append(f'W{idx}_W={w["size_w"]}')
        lines.append(f'W{idx}_H={w["size_h"]}')
        lines.append(f'W{idx}_TITLE="{title_safe}"')
        lines.append(f'W{idx}_PROFILE="{profile}"')
        lines.append(f'W{idx}_RESTARTABLE={"true" if m["restartable"] else "false"}')
        lines.append('')

    total = len(matched)
    lines.append(f'TOTAL={total}')
    lines.append('')

    # List mode
    lines.append('if [ "$MODE" = "list" ]; then')
    lines.append(f'    echo "Workspace: {name}"')
    lines.append(f'    echo "Finestre: {total}"')
    lines.append('    echo ""')
    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = (w["custom_title"] or w["window_name"] or f"Window {idx}").replace('"', "")
        stype = m["type"].upper()
        restartable = "OK" if m["restartable"] else "MANUAL"
        desc = ""
        if m["session"]:
            desc = f' — {m["session"]["first_msg"][:50]}'
        elif m["command"]:
            desc = f' — {m["command"][:50]}'
        lines.append(f'    echo "  [{idx:2d}] [{stype:10s}] [{restartable:6s}] {title}{desc}"')
    lines.append('    echo ""')
    lines.append(f'    echo "Totale: {total} finestre"')
    lines.append('    exit 0')
    lines.append('fi')
    lines.append('')

    # Restore logic
    lines.append(f'echo ""')
    lines.append(f'echo "  Ripristino workspace: {name}"')
    lines.append(f'echo "  {total} finestre da aprire..."')
    lines.append(f'echo ""')
    lines.append('')
    lines.append('OPENED=0')
    lines.append('SKIPPED=0')
    lines.append('')

    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = (w["custom_title"] or w["window_name"] or f"Window {idx}").replace('"', '\\"').replace("'", "")
        profile = w.get("profile", "Basic")
        wtype = m["type"]

        # Mode filter
        if wtype == "claude":
            mode_check = '[ "$MODE" = "all" ] || [ "$MODE" = "claude" ]'
        elif wtype in ("watchdog", "monitor", "automation", "script"):
            mode_check = '[ "$MODE" = "all" ] || [ "$MODE" = "scripts" ]'
        else:
            mode_check = '[ "$MODE" = "all" ]'

        lines.extend([
            f'# Window {idx}',
            f'if {mode_check}; then',
            '    SKIP=false',
            '    if [ ${#INDICES[@]} -gt 0 ]; then',
            '        SKIP=true',
            '        for i in "${INDICES[@]}"; do',
            f'            [ "$i" = "{idx}" ] && SKIP=false',
            '        done',
            '    fi',
            '    if ! $SKIP; then',
        ])

        if not m["restartable"]:
            lines.append(f'        echo "  [{idx:2d}] SKIP (non-restartable): {title}"')
            lines.append('        SKIPPED=$((SKIPPED + 1))')
        else:
            lines.append(f'        echo "  [{idx:2d}] Opening [{wtype.upper()}]: {title}"')
            lines.append(f'        open_window "$W{idx}_X" "$W{idx}_Y" "$W{idx}_W" "$W{idx}_H" "$W{idx}_TITLE" "$W{idx}_PROFILE" "$W{idx}_CMD"')
            lines.append('        OPENED=$((OPENED + 1))')

        lines.extend([
            '    fi',
            'fi',
            '',
        ])

    lines.extend([
        'echo ""',
        'echo "  Aperte: $OPENED finestre | Saltate: $SKIPPED"',
        'echo ""',
    ])

    restore_path = ws_dir / "restore.sh"
    with open(restore_path, "w") as f:
        f.write('\n'.join(lines))
    os.chmod(restore_path, 0o755)


def _generate_obsidian_map(ws_dir: Path, name: str, matched: list, counts: dict):
    """Generate session_map.md for Obsidian."""
    total = len(matched)
    restore_cmd = f"bash {ws_dir / 'restore.sh'}"

    lines = [
        '---',
        'class: session-map',
        'owner: v',
        'status: active',
        f'created: {datetime.now().strftime("%Y-%m-%d")}',
        f'updated: {datetime.now().isoformat()}',
        'tags: [claude-code, session-tracker, workspace-restore]',
        '---',
        '',
        f'# Workspace — {name}',
        '',
        f'> Salvato: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'> Finestre: {total} (Claude: {counts.get("claude", 0)}, '
        f'Watchdog: {counts.get("watchdog", 0)}, Monitor: {counts.get("monitor", 0)}, '
        f'Automation: {counts.get("automation", 0)}, Idle: {counts.get("idle_shell", 0)})',
        '',
        '## Quick Restore',
        '',
        '```bash',
        f'# Tutto',
        f'{restore_cmd}',
        '',
        f'# Solo Claude',
        f'{restore_cmd} --claude',
        '',
        f'# Specifiche (es. #1, #5, #9)',
        f'{restore_cmd} 1 5 9',
        '```',
        '',
        '---',
        '',
    ]

    # Group by type
    for section, types in [
        ("Claude Code Sessions", ["claude"]),
        ("Watchdog & Monitors", ["watchdog", "monitor"]),
        ("Automation Scripts", ["automation", "script"]),
        ("Idle Shells", ["idle_shell"]),
    ]:
        entries = [(i, m) for i, m in enumerate(matched, 1) if m["type"] in types]
        if not entries:
            continue

        lines.append(f'## {section}')
        lines.append('')

        for idx, m in entries:
            w = m["window"]
            title = w["custom_title"] or w["window_name"] or f"Window {idx}"
            pos = f"{w['pos_x']},{w['pos_y']}"
            size = f"{w['size_w']}x{w['size_h']}"

            if m["type"] == "claude" and m["session"]:
                s = m["session"]
                lines.extend([
                    f'### {idx}. {title}',
                    '',
                    '| Campo | Valore |',
                    '|-------|--------|',
                    f'| **Session ID** | `{s["session_id"]}` |',
                    f'| **Working dir** | `{s["cwd"]}` |',
                    f'| **Primo msg** | {s["first_msg"][:80]} |',
                    f'| **Ultimo msg** | {s["last_msg"][:80]} |',
                    f'| **Messaggi** | {s["messages"]} ({s.get("user_messages", "?")} user) |',
                    f'| **Size** | {s["size_kb"]}KB |',
                    f'| **Posizione** | {pos} — {size} |',
                    f'| **Profilo** | {w["profile"]} |',
                    '',
                    '```bash',
                    f'claude --resume {s["session_id"]}',
                    '```',
                    '',
                ])
            else:
                cmd_display = m["command"][:100] if m["command"] else "(nessun comando)"
                lines.extend([
                    f'### {idx}. [{m["type"].upper()}] {title}',
                    '',
                    f'- **Posizione:** {pos} — {size}',
                    f'- **Comando:** `{cmd_display}`',
                    f'- **Profilo:** {w["profile"]}',
                    f'- **Restartable:** {"Si" if m["restartable"] else "No (riavvio manuale)"}',
                    '',
                ])

            lines.append('---')
            lines.append('')

    with open(ws_dir / "session_map.md", "w") as f:
        f.write('\n'.join(lines))


# ============================================================
# Restore workspace
# ============================================================

def restore_workspace(name: str = None, extra_args: list = None):
    if not name:
        if not WORKSPACES_DIR.exists():
            print("Nessun workspace salvato.")
            return
        ws_dirs = sorted(
            [d for d in WORKSPACES_DIR.iterdir() if d.is_dir() and (d / "restore.sh").exists()],
            reverse=True
        )
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

    args = extra_args or []
    os.execvp("bash", ["bash", str(restore_script)] + args)


# ============================================================
# List & Status
# ============================================================

def list_workspaces():
    if not WORKSPACES_DIR.exists():
        print("Nessun workspace salvato.")
        return

    print("\n  Workspaces salvati:\n")
    for ws_dir in sorted(WORKSPACES_DIR.iterdir(), reverse=True):
        json_file = ws_dir / "workspace.json"
        if ws_dir.is_dir() and json_file.exists():
            with open(json_file) as f:
                data = json.load(f)
            c = data.get("counts", {})
            print(f"  {ws_dir.name}")
            print(f"    Creato: {data.get('created', '?')}")
            print(f"    Claude: {c.get('claude', 0)} | Watchdog: {c.get('watchdog', 0)} | "
                  f"Monitor: {c.get('monitor', 0)} | Automation: {c.get('automation', 0)} | "
                  f"Script: {c.get('script', 0)} | Idle: {c.get('idle_shell', 0)}")
            print(f"    Restore: bash {ws_dir / 'restore.sh'}")
            print()


def show_status():
    windows = get_terminal_windows()
    claude_pids = get_claude_pids_by_tty()
    sessions = get_active_sessions(hours=8)
    matched = match_windows_to_sessions(windows, claude_pids, sessions)

    counts = {}
    for m in matched:
        counts[m["type"]] = counts.get(m["type"], 0) + 1

    print(f"\n  Terminal.app: {len(windows)} finestre | Claude PIDs: {len(claude_pids)} | Sessioni JSONL: {len(sessions)}")
    print(f"  Config dirs: {', '.join(CLAUDE_CONFIG_DIRS)}")
    print()

    COLORS = {
        "claude": "\033[0;32m",      # green
        "watchdog": "\033[0;33m",    # yellow
        "monitor": "\033[0;33m",     # yellow
        "automation": "\033[0;35m",  # magenta
        "script": "\033[0;34m",      # blue
        "idle_shell": "\033[0;37m",  # gray
    }
    NC = "\033[0m"
    BOLD = "\033[1m"

    for idx, m in enumerate(matched, 1):
        w = m["window"]
        title = w["custom_title"] or w["window_name"] or "?"
        color = COLORS.get(m["type"], NC)
        stype = m["type"].upper()
        pos = f"({w['pos_x']},{w['pos_y']})"
        size = f"{w['size_w']}x{w['size_h']}"
        restart = "OK" if m["restartable"] else "!!"

        line = f"  [{idx:2d}] {color}[{stype:10s}]{NC} [{restart}] {BOLD}{title:35s}{NC} {pos:15s} {size:10s}"

        if m["session"]:
            sid = m["session"]["session_id"][:8]
            msg = m["session"]["first_msg"][:40]
            line += f" {sid}… {msg}"
        elif m["command"]:
            line += f" {m['command'][:50]}"

        print(line)

    print(f"\n  Riepilogo: " + " | ".join(f"{k}: {v}" for k, v in counts.items()))
    print()


# ============================================================
# Main
# ============================================================

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "save":
        save_workspace(arg)
    elif cmd == "restore":
        # Collect all args after "restore"
        extra = []
        name = None
        for a in sys.argv[2:]:
            if a.startswith("-"):
                extra.append(a)
            elif not name and not a.isdigit():
                name = a
            else:
                extra.append(a)
        restore_workspace(name, extra)
    elif cmd == "list":
        list_workspaces()
    elif cmd == "status":
        show_status()
    elif cmd in ("help", "-h", "--help"):
        print(__doc__)
    else:
        print(f"Comando sconosciuto: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
