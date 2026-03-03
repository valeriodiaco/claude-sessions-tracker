# Claude Code Sessions Tracker

Save and restore your entire Claude Code workspace — terminal windows, positions, sessions, scripts. Power goes out, you switch accounts, you reboot — one command brings everything back exactly as it was.

## What It Does

| Feature | Details |
|---------|---------|
| **Window positions & sizes** | Exact pixel coordinates via AppleScript |
| **Claude Code sessions** | Matched via TTY → PID → session ID correlation |
| **Watchdog & monitors** | Full command captured for auto-restart |
| **Automation scripts** | Captured and restartable |
| **Custom titles** | Preserved (from `/rename` in Claude Code) |
| **Terminal.app profile** | Per-window profile detection |
| **Multi-account** | Scans all `~/.claude*/projects/` directories |
| **Obsidian integration** | Session map with YAML frontmatter |
| **JSON export** | Machine-readable for EVA/n8n/automation |

## Quick Start

```bash
git clone https://github.com/valeriodiaco/claude-sessions-tracker.git
cd claude-sessions-tracker

# See current state
python3 workspace-manager.py status

# Save everything before switching accounts / shutting down
python3 workspace-manager.py save pre-switch

# After reboot / account switch — restore everything
python3 workspace-manager.py restore
```

### Requirements

- macOS with Terminal.app
- Python 3.9+
- Claude Code installed

## Commands

### workspace-manager.py (Full workspace — recommended)

```bash
# Live status — see all windows, sessions, processes
python3 workspace-manager.py status

# Save workspace (auto-named by timestamp)
python3 workspace-manager.py save

# Save with custom name
python3 workspace-manager.py save pre-switch

# Restore latest workspace (all windows at exact positions)
python3 workspace-manager.py restore

# Restore specific workspace
python3 workspace-manager.py restore pre-switch

# Restore only Claude sessions (skip watchdog/monitors/idle)
python3 workspace-manager.py restore --claude

# Restore only scripts (watchdog, monitors)
python3 workspace-manager.py restore --scripts

# Restore specific windows by number
python3 workspace-manager.py restore 1 5 9 16

# List without restoring
python3 workspace-manager.py restore --list

# List all saved workspaces
python3 workspace-manager.py list
```

### claude-sessions.sh (Lightweight session listing)

```bash
# List today's sessions
./claude-sessions.sh

# List last 7 days
./claude-sessions.sh list 7

# Quick snapshot (sessions only, no window positions)
./claude-sessions.sh snapshot pre-switch

# Search sessions by content
./claude-sessions.sh find "refactor auth"

# Claude's built-in interactive picker
./claude-sessions.sh resume
```

## Typical Workflows

### Switching Claude accounts (quota limit)

```bash
# 1. Save
python3 workspace-manager.py save pre-switch

# 2. Switch
claude logout && claude login

# 3. Restore — all 20+ windows reopen at exact positions
python3 workspace-manager.py restore
```

### Power outage / reboot

```bash
# If you saved before (or have a cron/hook saving periodically):
python3 workspace-manager.py restore

# If you didn't save — sessions are still in JSONL files:
./claude-sessions.sh list 1
# Then manually: claude --resume <SESSION_ID>
```

### Finding a lost session

```bash
./claude-sessions.sh find "database migration"
# or
python3 workspace-manager.py status
```

## Output Files

Each workspace save creates:

| File | Purpose |
|------|---------|
| `restore.sh` | Bash + AppleScript — opens Terminal.app windows at exact positions |
| `session_map.md` | Obsidian-compatible Markdown with YAML frontmatter, grouped by type |
| `workspace.json` | Full structured data for automation (EVA ingestion, n8n, etc.) |

### session_map.md format

```yaml
---
class: session-map
owner: v
status: active
created: 2026-03-03
tags: [claude-code, session-tracker, workspace-restore]
---
```

Each Claude session includes a ready-to-use resume command:
```bash
claude --resume f1b0924e-d0e2-4247-bdde-5cdfa622b525
```

## What Gets Captured

```
Terminal.app: 26 windows | Claude PIDs: 20 | Sessions: 52

  [ 1] [CLAUDE    ] [OK] ✳ ADAM_builder_ADMIN          (13,47)    563x1477   f1b0924e…
  [ 2] [CLAUDE    ] [OK] ✳ GEO_Proj_ADMIN              (7,32)     738x1505   0d28d5f6…
  [ 3] [CLAUDE    ] [OK] ✳ 1_Mirko_LSB                 (1323,32)  626x623    f5f87528…
  [12] [WATCHDOG  ] [OK] Terminal                       (550,488)  479x371    bash watchdog.sh -t 70
  [14] [MONITOR   ] [OK] Terminal                       (44,42)    500x441    bash monitor.sh --watch
  [18] [IDLE_SHELL] [OK] Terminal                       (2574,406) 423x973
```

## Multi-Account Support

Automatically discovers all Claude Code config directories:

```
~/.claude/projects/          # default account
~/.claude-auto/projects/     # automation account
~/.claude-main/projects/     # main account
```

Works with [claude-code-multi-account](https://github.com/valeriodiaco/claude-code-multi-account).

## Limitations

- **Desktop/Spaces**: macOS doesn't expose which Space (virtual desktop) a window belongs to via API. Windows restore on the current Space. Consider using [yabai](https://github.com/koekeishiya/yabai) for full Space management.
- **Non-Terminal apps**: Only tracks Terminal.app windows. Finder, n8n, browsers are not captured.
- **Session matching**: Uses heuristics (window title ↔ cwd ↔ session ID). With many similar sessions (e.g., 15 EVA Consolidation sessions), some may be matched to wrong session IDs.

## Related Tools

| Tool | Description |
|------|-------------|
| [claude-code-multi-account](https://github.com/valeriodiaco/claude-code-multi-account) | Run 2-5 Claude Max accounts with load balancing |
| [claude_code_usage_watchdog](https://github.com/valeriodiaco/claude_code_usage_watchdog) | Monitor usage, kill automation on threshold |
| [claude-code-token-counter](https://github.com/valeriodiaco/claude-code-token-counter) | Track token usage and costs per session |
| [eva-automation](https://github.com/valeriodiaco/eva-automation) | EVA knowledge system automation scripts |

## License

MIT
