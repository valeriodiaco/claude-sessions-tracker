# Claude Code Sessions Tracker

Track, snapshot, and recover [Claude Code](https://docs.anthropic.com/en/docs/claude-code) terminal sessions.

## The Problem

Claude Code saves conversations locally as `.jsonl` files in `~/.claude/projects/`. But:

- File names are UUIDs — impossible to know which conversation is which
- Folder names are derived from the working directory path — if you rename a folder, you lose the link
- `claude --continue` only resumes the last session in the current directory
- No built-in way to see all your active sessions at a glance

If you juggle multiple Claude Code sessions (across projects, terminals, or accounts), finding and resuming the right one is painful.

## The Solution

A single bash script that:

1. **Lists** recent sessions with human-readable previews (first/last message, project name, message count)
2. **Snapshots** currently active sessions before you switch accounts or close terminals
3. **Searches** across all sessions by content
4. **Generates** a Markdown index for easy browsing

## Installation

```bash
git clone https://github.com/YOUR_USER/claude-sessions-tracker.git
cd claude-sessions-tracker
chmod +x claude-sessions.sh
```

Or just download the script:

```bash
curl -O https://raw.githubusercontent.com/YOUR_USER/claude-sessions-tracker/main/claude-sessions.sh
chmod +x claude-sessions.sh
```

### Requirements

- macOS or Linux (uses `stat`, `find`)
- Python 3 (for JSONL parsing)
- Claude Code installed (`~/.claude/projects/` must exist)

## Usage

```bash
# List today's sessions
./claude-sessions.sh

# List sessions from the last 7 days
./claude-sessions.sh list 7

# Snapshot active sessions (modified in last 4 hours)
# Perfect before switching accounts or closing terminals
./claude-sessions.sh snapshot

# Snapshot with a custom name
./claude-sessions.sh snapshot pre-account-switch

# Search sessions by content
./claude-sessions.sh find "authentication bug"

# Open Claude's built-in interactive picker
./claude-sessions.sh resume
```

### Resuming a Session

The script shows the resume command for each session:

```bash
claude --resume <SESSION_ID>
```

This works from any directory — Claude Code will load the full conversation context from the local JSONL file.

## Typical Workflow

### Switching Claude Code accounts (quota limit)

1. Run `./claude-sessions.sh snapshot pre-switch` to save all active sessions
2. `claude logout && claude login` with new account
3. Open `snapshots/snapshot_pre-switch.md` to see all your sessions
4. `claude --resume <SESSION_ID>` for each session you need

### Finding a lost session

```bash
# Search by something you discussed
./claude-sessions.sh find "refactor database"

# Or browse recent sessions
./claude-sessions.sh list 30
```

## How Claude Code Stores Sessions

- **Location:** `~/.claude/projects/<project-folder>/<uuid>.jsonl`
- **Project folder:** derived from the working directory path (slashes → dashes)
- **Format:** one JSON object per line, with `type: "user"` or `type: "assistant"`
- **Resume:** `claude --resume <uuid>` or `claude --continue` (last session in current dir)

## Output

### Terminal
Colored, scannable output with session previews:

```
[1] 2026-03-03 11:42 — Dobbiamo partire a sviluppare la parte di adam
    Project EVA Self Knowledge Base Build | 45 msg | 614KB
    claude --resume f1b0924e-d0e2-4247-bdde-5cdfa622b525
```

### INDEX.md
A Markdown table generated alongside terminal output, for browsing in any editor.

### Snapshots
Saved in `snapshots/` with full resume commands for each session.

## License

MIT
