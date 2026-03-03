# Claude Code Sessions Tracker

Track, snapshot, and recover [Claude Code](https://docs.anthropic.com/en/docs/claude-code) terminal sessions. Restore your entire workspace after a reboot, power outage, or account switch.

## The Problem

Claude Code saves conversations locally as `.jsonl` files in `~/.claude/projects/`. But:

- File names are UUIDs — impossible to know which conversation is which
- Folder names are derived from the working directory path — if you rename a folder, you lose the link
- `claude --continue` only resumes the last session in the current directory
- No built-in way to see all your active sessions at a glance
- Switching accounts (quota limits) loses track of open sessions

If you juggle multiple Claude Code sessions across projects, terminals, or accounts, finding and resuming the right one is painful.

## The Solution

A single bash script that:

1. **Lists** recent sessions with human-readable previews (first/last message, project, working dir)
2. **Snapshots** currently active sessions before you switch accounts or close terminals
3. **Saves workspace** with a restore script (opens Terminal.app tabs) + Obsidian session map + JSON for automation
4. **Restores** your entire workspace — all sessions reopened in separate Terminal tabs
5. **Searches** across all sessions by content
6. **Multi-account aware** — scans all `~/.claude*/projects/` directories

## Installation

```bash
git clone https://github.com/valeriodiaco/claude-sessions-tracker.git
cd claude-sessions-tracker
chmod +x claude-sessions.sh
```

### Requirements

- macOS (uses `stat -f`, AppleScript for Terminal.app tabs)
- Python 3 (for JSONL parsing)
- Claude Code installed (`~/.claude/projects/` must exist)

## Usage

```bash
# List today's sessions
./claude-sessions.sh

# List sessions from the last 7 days
./claude-sessions.sh list 7

# Quick snapshot of active sessions (last 4 hours)
./claude-sessions.sh snapshot

# Full workspace save: restore script + Obsidian map + JSON
./claude-sessions.sh workspace

# Workspace with custom name
./claude-sessions.sh workspace pre-account-switch

# Restore all sessions (opens Terminal.app tabs)
./claude-sessions.sh restore

# Restore specific sessions only
./claude-sessions.sh restore restore.sh 1 3 7

# List sessions in a restore file without opening them
bash snapshots/workspace_*/restore.sh --list

# Search sessions by content
./claude-sessions.sh find "authentication bug"

# Open Claude's built-in interactive picker
./claude-sessions.sh resume
```

## Workspace Save & Restore

The `workspace` command generates three files:

| File | Purpose |
|------|---------|
| `restore.sh` | Bash script that opens each session in a Terminal.app tab via AppleScript |
| `session_map.md` | Markdown with YAML frontmatter — open in Obsidian, copy `claude --resume` commands |
| `session_map.json` | Machine-readable JSON for automation/EVA integration |

### Typical workflow

```bash
# 1. Before switching accounts / shutting down
./claude-sessions.sh workspace pre-switch

# 2. Switch account
claude logout && claude login

# 3. Restore everything
./claude-sessions.sh restore
# → opens 20+ Terminal.app tabs, each resuming a session
```

### Obsidian Integration

The `session_map.md` includes EVA-compatible frontmatter:

```yaml
---
class: session-map
owner: v
status: active
created: 2026-03-03
tags: [claude-code, session-tracker, workspace-restore]
---
```

Each session entry has a ready-to-use resume command:

```bash
claude --resume f1b0924e-d0e2-4247-bdde-5cdfa622b525
```

### JSON for Automation

The `session_map.json` can be consumed by other tools (EVA ingestion, n8n workflows, etc.):

```json
{
  "workspace": "pre-switch",
  "created": "2026-03-03T14:35:36Z",
  "sessions": [
    {
      "session_id": "f1b0924e-...",
      "cwd": "/Users/v/my-project",
      "first_msg": "Fix the auth bug in...",
      "messages": 45,
      "resume": "claude --resume f1b0924e-..."
    }
  ]
}
```

## Multi-Account Support

The script automatically discovers all Claude Code config directories:

- `~/.claude/projects/` (default)
- `~/.claude-auto/projects/` (automation account)
- `~/.claude-main/projects/` (main account)
- Any other `~/.claude-*/projects/` directories

Works with [claude-code-multi-account](https://github.com/valeriodiaco/claude-code-multi-account) and [claude-code-dual-account](https://github.com/valeriodiaco/claude-code-dual-account).

## Related Tools

| Tool | Description |
|------|-------------|
| [claude-code-multi-account](https://github.com/valeriodiaco/claude-code-multi-account) | Run 2-5 Claude Max accounts with load balancing |
| [claude_code_usage_watchdog](https://github.com/valeriodiaco/claude_code_usage_watchdog) | Monitor API usage, kill automation on threshold |
| [claude-code-token-counter](https://github.com/valeriodiaco/claude-code-token-counter) | Track token usage and costs per session |

## How Claude Code Stores Sessions

- **Location:** `~/.claude/projects/<project-folder>/<uuid>.jsonl`
- **Project folder:** derived from the working directory path (slashes → dashes)
- **Format:** one JSON object per line, with `type: "user"` or `type: "assistant"`
- **Content:** in `obj.message.content` (string or list of content blocks)
- **Working dir:** in `obj.cwd` (first user message)
- **Resume:** `claude --resume <uuid>` from any directory

## License

MIT
