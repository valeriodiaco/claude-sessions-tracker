#!/bin/bash
# ============================================================
# Claude Code Sessions Tracker
#
# Traccia e recupera le sessioni Claude Code salvate localmente.
# Le conversazioni sono in ~/.claude/projects/ come file .jsonl.
# Per riprendere: claude --resume <SESSION_ID>
#
# Comandi:
#   ./claude-sessions.sh                       # lista sessioni di oggi
#   ./claude-sessions.sh list [giorni]         # lista sessioni (default: 1 giorno)
#   ./claude-sessions.sh snapshot [nome]       # salva snapshot sessioni attive
#   ./claude-sessions.sh workspace [nome]      # snapshot + restore script + obsidian links
#   ./claude-sessions.sh restore <file.sh>     # esegue un restore script
#   ./claude-sessions.sh find <testo>          # cerca nelle sessioni per contenuto
#   ./claude-sessions.sh resume                # mostra picker interattivo
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SNAPSHOTS_DIR="$SCRIPT_DIR/snapshots"
INDEX_FILE="$SCRIPT_DIR/INDEX.md"

# Trova TUTTI i config dir di Claude Code (multi-account support)
CLAUDE_CONFIG_DIRS=()
for d in "$HOME/.claude" "$HOME/.claude-"*; do
    if [ -d "$d/projects" ]; then
        CLAUDE_CONFIG_DIRS+=("$d/projects")
    fi
done

if [ ${#CLAUDE_CONFIG_DIRS[@]} -eq 0 ]; then
    echo "ERRORE: Nessuna cartella projects/ trovata in ~/.claude*"
    exit 1
fi

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---- Funzione: estrai info da un JSONL ----
extract_info() {
    local file="$1"
    python3 - "$file" << 'PYEOF'
import json, sys

jsonl_path = sys.argv[1]
first_user = ""
last_user = ""
user_count = 0
assistant_count = 0
cwd = ""
session_name = ""

try:
    with open(jsonl_path, 'r') as f:
        for line in f:
            try:
                obj = json.loads(line)
                msg_type = obj.get('type', '')

                # Grab cwd and session name from first user message
                if msg_type == 'user' and not cwd:
                    cwd = obj.get('cwd', '')

                if msg_type == 'summary' and not session_name:
                    session_name = obj.get('title', '') or obj.get('name', '')

                if msg_type == 'user':
                    user_count += 1
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
                        if not first_user:
                            first_user = text
                        last_user = text
                elif msg_type == 'assistant':
                    assistant_count += 1
            except (json.JSONDecodeError, KeyError):
                pass
except Exception:
    pass

total = user_count + assistant_count
print(f"{first_user or '(vuoto)'}|||{last_user or '(vuoto)'}|||{total}|||{user_count}|||{cwd}|||{session_name}")
PYEOF
}

# ---- Funzione: short project name ----
short_project() {
    echo "$1" | sed 's/^-Users-v-*//' | sed 's/--/\//g' | sed 's/-/ /g' | rev | cut -d'/' -f1-2 | rev
}

# ---- Funzione: trova tutti i JSONL recenti (multi-account) ----
find_sessions() {
    local time_filter="$1"  # -mtime or -mmin argument
    for proj_dir in "${CLAUDE_CONFIG_DIRS[@]}"; do
        find "$proj_dir" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" $time_filter -size +1k 2>/dev/null
    done | while read f; do echo "$(stat -f "%m" "$f") $f"; done | sort -rn | cut -d' ' -f2-
}

# ---- Funzione: ricostruisci il path originale dal nome cartella ----
reconstruct_path() {
    echo "$1" | sed 's/^-/\//g' | sed 's/--/-/g'
}

# ---- Comando: list ----
cmd_list() {
    local days="${1:-1}"
    local count=0

    echo -e "${BOLD}Claude Code Sessions — ultimi $days giorno/i${NC}"
    echo -e "Config dirs: ${#CLAUDE_CONFIG_DIRS[@]} ($(printf '%s ' "${CLAUDE_CONFIG_DIRS[@]}"))"
    echo -e "Aggiornato: $(date '+%Y-%m-%d %H:%M:%S')\n"

    cat > "$INDEX_FILE" << HEADER
# Claude Code Sessions — Indice

> Generato: $(date '+%Y-%m-%d %H:%M:%S')
> Range: ultimi $days giorno/i

| # | Data | Sessione | Primo messaggio | Messaggi | Resume |
|---|------|----------|-----------------|----------|--------|
HEADER

    while IFS= read -r jsonl_file; do
        session_id=$(basename "$jsonl_file" .jsonl)
        project_dir=$(basename "$(dirname "$jsonl_file")")
        mod_date=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$jsonl_file")
        file_size=$(stat -f "%z" "$jsonl_file")
        file_size_kb=$((file_size / 1024))
        short=$(short_project "$project_dir")

        info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0||||||")
        first_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $1}')
        last_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $2}')
        msg_count=$(echo "$info" | awk -F'\\|\\|\\|' '{print $3}')

        count=$((count + 1))

        echo -e "${CYAN}[$count]${NC} ${BOLD}$mod_date${NC} — ${GREEN}${first_msg:0:80}${NC}"
        echo -e "    ${YELLOW}$short${NC} | ${msg_count} msg | ${file_size_kb}KB"
        echo -e "    ${BLUE}claude --resume $session_id${NC}"
        echo ""

        first_msg_escaped=$(echo "$first_msg" | sed 's/|/\\|/g' | cut -c1-60)
        echo "| $count | $mod_date | \`${session_id:0:8}…\` | $first_msg_escaped | $msg_count | \`claude --resume $session_id\` |" >> "$INDEX_FILE"

    done < <(find_sessions "-mtime -$days")

    echo -e "\n---" >> "$INDEX_FILE"
    echo -e "\n**Totale: $count sessioni**" >> "$INDEX_FILE"

    echo -e "${BOLD}Totale: $count sessioni${NC}"
    echo -e "INDEX salvato in: $INDEX_FILE"
}

# ---- Comando: snapshot ----
cmd_snapshot() {
    local name="${1:-$(date '+%Y%m%d_%H%M')}"
    local snapshot_file="$SNAPSHOTS_DIR/snapshot_${name}.md"

    mkdir -p "$SNAPSHOTS_DIR"

    echo -e "${BOLD}Salvataggio snapshot: $name${NC}\n"

    cat > "$snapshot_file" << HEADER
# Snapshot: $name
> Creato: $(date '+%Y-%m-%d %H:%M:%S')
> Scopo: recuperare queste sessioni dopo cambio account / riavvio

## Sessioni attive

HEADER

    local count=0

    while IFS= read -r jsonl_file; do
        session_id=$(basename "$jsonl_file" .jsonl)
        project_dir=$(basename "$(dirname "$jsonl_file")")
        mod_date=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$jsonl_file")
        file_size_kb=$(($(stat -f "%z" "$jsonl_file") / 1024))
        short=$(short_project "$project_dir")

        info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0||||||")
        first_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $1}')
        last_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $2}')
        msg_count=$(echo "$info" | awk -F'\\|\\|\\|' '{print $3}')

        count=$((count + 1))

        echo -e "${CYAN}[$count]${NC} $mod_date — ${GREEN}${first_msg:0:60}${NC}"

        cat >> "$snapshot_file" << ENTRY
### $count. $mod_date — $first_msg
- **Session ID:** \`$session_id\`
- **Progetto:** \`$short\`
- **Ultimo msg:** $last_msg
- **Messaggi:** $msg_count | **Size:** ${file_size_kb}KB
- **Resume:**
  \`\`\`
  claude --resume $session_id
  \`\`\`

ENTRY

    done < <(find_sessions "-mmin -240")

    echo -e "\n---\n" >> "$snapshot_file"
    echo "**Totale: $count sessioni attive**" >> "$snapshot_file"

    echo -e "\n${BOLD}Snapshot salvato: $snapshot_file${NC}"
    echo -e "${BOLD}Totale: $count sessioni${NC}"
}

# ---- Comando: workspace (snapshot + restore + obsidian) ----
cmd_workspace() {
    local name="${1:-$(date '+%Y%m%d_%H%M')}"
    local ws_dir="$SNAPSHOTS_DIR/workspace_${name}"
    local restore_script="$ws_dir/restore.sh"
    local obsidian_map="$ws_dir/session_map.md"
    local json_map="$ws_dir/session_map.json"

    mkdir -p "$ws_dir"

    echo -e "${BOLD}Salvataggio workspace: $name${NC}\n"

    # ---- restore.sh header ----
    cat > "$restore_script" << 'RESTORE_HEADER'
#!/bin/bash
# ============================================================
# Claude Code Workspace Restore
# Riapre tutte le sessioni salvate nello snapshot in tab Terminal.app
#
# Uso:
#   bash restore.sh             # apre tutte le sessioni
#   bash restore.sh 1 3 5       # apre solo sessioni #1, #3, #5
#   bash restore.sh --list      # mostra le sessioni senza aprirle
# ============================================================

set -euo pipefail

SESSIONS=()

RESTORE_HEADER

    # ---- obsidian session map header ----
    cat > "$obsidian_map" << OBSHEADER
---
class: session-map
owner: v
status: active
created: $(date '+%Y-%m-%d')
updated: $(date '+%Y-%m-%dT%H:%M:%S')
tags: [claude-code, session-tracker, workspace-restore]
---

# Session Map — $name

> Workspace salvato: $(date '+%Y-%m-%d %H:%M:%S')
> Per riprendere una sessione, copia il comando \`claude --resume\` nel terminale.
> Per ripristinare TUTTO: \`bash restore.sh\`

OBSHEADER

    # ---- JSON map init ----
    echo '{"workspace":"'"$name"'","created":"'"$(date -u '+%Y-%m-%dT%H:%M:%SZ')"'","sessions":[' > "$json_map"

    local count=0
    local json_sep=""

    while IFS= read -r jsonl_file; do
        session_id=$(basename "$jsonl_file" .jsonl)
        project_dir=$(basename "$(dirname "$jsonl_file")")
        mod_date=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$jsonl_file")
        file_size_kb=$(($(stat -f "%z" "$jsonl_file") / 1024))
        short=$(short_project "$project_dir")

        info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0||||||")
        first_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $1}')
        last_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $2}')
        msg_count=$(echo "$info" | awk -F'\\|\\|\\|' '{print $3}')
        cwd=$(echo "$info" | awk -F'\\|\\|\\|' '{print $5}')
        session_name=$(echo "$info" | awk -F'\\|\\|\\|' '{print $6}')

        # Fallback cwd
        if [ -z "$cwd" ] || [ "$cwd" = "(vuoto)" ]; then
            cwd=$(reconstruct_path "$project_dir")
        fi

        count=$((count + 1))

        echo -e "${CYAN}[$count]${NC} $mod_date — ${GREEN}${first_msg:0:60}${NC}"
        echo -e "    ${YELLOW}cwd: $cwd${NC}"

        # ---- Aggiungi a restore.sh ----
        cat >> "$restore_script" << ENTRY
# Session $count: $first_msg
SESSIONS+=("$count|$session_id|$cwd|$(echo "$first_msg" | sed "s/'/\\\\'/g")")

ENTRY

        # ---- Aggiungi a session_map.md (Obsidian) ----
        cat >> "$obsidian_map" << OBSENTRY
## $count. ${session_name:-$first_msg}

| Campo | Valore |
|-------|--------|
| **Session ID** | \`$session_id\` |
| **Data** | $mod_date |
| **Working dir** | \`$cwd\` |
| **Progetto** | \`$short\` |
| **Ultimo msg** | ${last_msg:0:80} |
| **Messaggi** | $msg_count |
| **Size** | ${file_size_kb}KB |

\`\`\`bash
claude --resume $session_id
\`\`\`

---

OBSENTRY

        # ---- Aggiungi a session_map.json ----
        first_msg_json=$(echo "$first_msg" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip()))")
        last_msg_json=$(echo "$last_msg" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip()))")
        cat >> "$json_map" << JSONENTRY
${json_sep}{"index":$count,"session_id":"$session_id","date":"$mod_date","cwd":"$cwd","project":"$short","first_msg":$first_msg_json,"last_msg":$last_msg_json,"messages":$msg_count,"size_kb":$file_size_kb,"resume":"claude --resume $session_id"}
JSONENTRY
        json_sep=","

    done < <(find_sessions "-mmin -240")

    # ---- Chiudi JSON ----
    echo '],"total":'"$count"'}' >> "$json_map"

    # ---- Completa restore.sh con la logica di restore ----
    cat >> "$restore_script" << 'RESTORE_LOGIC'

# ---- Restore logic ----

list_sessions() {
    echo "Sessioni disponibili:"
    echo ""
    for s in "${SESSIONS[@]}"; do
        IFS='|' read -r idx sid cwd desc <<< "$s"
        echo "  [$idx] $desc"
        echo "       cwd: $cwd"
        echo "       claude --resume $sid"
        echo ""
    done
    echo "Totale: ${#SESSIONS[@]} sessioni"
}

open_session_in_tab() {
    local sid="$1"
    local cwd="$2"
    local desc="$3"
    local tab_idx="$4"

    # Usa AppleScript per aprire un nuovo tab in Terminal.app
    if [ "$tab_idx" -eq 1 ]; then
        # Primo: usa la finestra corrente (apri nuovo tab)
        osascript -e "
            tell application \"Terminal\"
                activate
                do script \"cd '$cwd' && echo '🔄 Resuming: $desc' && claude --resume $sid\" in front window
            end tell
        " 2>/dev/null || {
            # Fallback: nuova finestra
            osascript -e "
                tell application \"Terminal\"
                    activate
                    do script \"cd '$cwd' && claude --resume $sid\"
                end tell
            "
        }
    else
        osascript -e "
            tell application \"Terminal\"
                activate
                tell application \"System Events\" to keystroke \"t\" using command down
                delay 0.3
                do script \"cd '$cwd' && echo '🔄 Resuming: $desc' && claude --resume $sid\" in front window
            end tell
        " 2>/dev/null || {
            osascript -e "
                tell application \"Terminal\"
                    do script \"cd '$cwd' && claude --resume $sid\"
                end tell
            "
        }
    fi
}

# Parse args
if [ "${1:-}" = "--list" ] || [ "${1:-}" = "-l" ]; then
    list_sessions
    exit 0
fi

# Filter specific sessions if args provided
target_indices=()
if [ $# -gt 0 ]; then
    target_indices=("$@")
fi

echo "Ripristino workspace Claude Code..."
echo "Sessioni da aprire: ${#target_indices[@]:-${#SESSIONS[@]}}"
echo ""

tab_num=0
for s in "${SESSIONS[@]}"; do
    IFS='|' read -r idx sid cwd desc <<< "$s"

    # Se sono specificati indici, filtra
    if [ ${#target_indices[@]} -gt 0 ]; then
        skip=true
        for t in "${target_indices[@]}"; do
            if [ "$t" = "$idx" ]; then skip=false; break; fi
        done
        if $skip; then continue; fi
    fi

    tab_num=$((tab_num + 1))
    echo "  [$idx] Opening: ${desc:0:60}"
    open_session_in_tab "$sid" "$cwd" "$desc" "$tab_num"
    sleep 0.5  # Breve pausa tra i tab
done

echo ""
echo "✓ $tab_num sessioni aperte"
RESTORE_LOGIC

    chmod +x "$restore_script"

    # ---- Footer obsidian map ----
    cat >> "$obsidian_map" << OBSFOOTER

## Restore completo

Per ripristinare tutte le $count sessioni in tab Terminal.app separati:

\`\`\`bash
bash "$restore_script"
\`\`\`

Per ripristinare solo alcune (es. #1, #3, #7):

\`\`\`bash
bash "$restore_script" 1 3 7
\`\`\`

Per vedere la lista:

\`\`\`bash
bash "$restore_script" --list
\`\`\`
OBSFOOTER

    echo -e "\n${BOLD}Workspace salvato in: $ws_dir/${NC}"
    echo -e "  ${GREEN}restore.sh${NC}      — script per riaprire tutto in Terminal.app"
    echo -e "  ${GREEN}session_map.md${NC}  — mappa sessioni per Obsidian"
    echo -e "  ${GREEN}session_map.json${NC} — mappa JSON per integrazione EVA/automazione"
    echo -e "${BOLD}Totale: $count sessioni${NC}"
}

# ---- Comando: restore ----
cmd_restore() {
    local script="${1:-}"
    if [ -z "$script" ]; then
        # Trova l'ultimo workspace
        local latest=$(find "$SNAPSHOTS_DIR" -name "restore.sh" -type f 2>/dev/null | sort -r | head -1)
        if [ -z "$latest" ]; then
            echo -e "${RED}Nessun workspace trovato. Crea uno con: ./claude-sessions.sh workspace${NC}"
            exit 1
        fi
        script="$latest"
    fi

    if [ ! -f "$script" ]; then
        echo -e "${RED}File non trovato: $script${NC}"
        exit 1
    fi

    echo -e "${BOLD}Esecuzione restore da: $script${NC}"
    shift 2>/dev/null || true
    bash "$script" "$@"
}

# ---- Comando: find ----
cmd_find() {
    local search="$1"
    echo -e "${BOLD}Ricerca: \"$search\"${NC}\n"

    local count=0
    while IFS= read -r jsonl_file; do
        if grep -q "$search" "$jsonl_file" 2>/dev/null; then
            session_id=$(basename "$jsonl_file" .jsonl)
            project_dir=$(basename "$(dirname "$jsonl_file")")
            mod_date=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$jsonl_file")
            short=$(short_project "$project_dir")

            info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0||||||")
            first_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $1}')

            count=$((count + 1))
            echo -e "${CYAN}[$count]${NC} $mod_date — ${GREEN}${first_msg:0:80}${NC}"
            echo -e "    ${YELLOW}$short${NC}"
            echo -e "    ${BLUE}claude --resume $session_id${NC}"
            echo ""
        fi
    done < <(for proj_dir in "${CLAUDE_CONFIG_DIRS[@]}"; do
        find "$proj_dir" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" -size +1k 2>/dev/null
    done | while read f; do echo "$(stat -f "%m" "$f") $f"; done | sort -rn | cut -d' ' -f2-)

    echo -e "${BOLD}Trovate: $count sessioni${NC}"
}

# ---- Comando: resume (picker interattivo) ----
cmd_resume() {
    echo -e "${BOLD}Avvio picker interattivo di Claude Code...${NC}"
    claude --resume
}

# ---- Help ----
cmd_help() {
    echo -e "${BOLD}Claude Code Sessions Tracker${NC}"
    echo ""
    echo "Comandi:"
    echo -e "  ${GREEN}./claude-sessions.sh${NC}                       Lista sessioni di oggi"
    echo -e "  ${GREEN}./claude-sessions.sh list [giorni]${NC}         Lista sessioni (default: 1)"
    echo -e "  ${GREEN}./claude-sessions.sh snapshot [nome]${NC}       Salva snapshot sessioni attive (ultime 4h)"
    echo -e "  ${GREEN}./claude-sessions.sh workspace [nome]${NC}      Snapshot + restore script + Obsidian map"
    echo -e "  ${GREEN}./claude-sessions.sh restore [file.sh]${NC}     Esegue restore (default: ultimo workspace)"
    echo -e "  ${GREEN}./claude-sessions.sh find <testo>${NC}          Cerca nelle sessioni"
    echo -e "  ${GREEN}./claude-sessions.sh resume${NC}                Picker interattivo Claude"
    echo -e "  ${GREEN}./claude-sessions.sh help${NC}                  Questo messaggio"
    echo ""
    echo "Le sessioni Claude Code sono in ~/.claude*/projects/*.jsonl"
    echo "Per riprendere: claude --resume <SESSION_ID>"
    echo ""
    echo "Workflow tipico:"
    echo "  1. Prima di spegnere / cambiare account:  ./claude-sessions.sh workspace"
    echo "  2. Dopo il riavvio:                       ./claude-sessions.sh restore"
}

# ---- Main ----
case "${1:-list}" in
    list)
        cmd_list "${2:-1}"
        ;;
    snapshot)
        cmd_snapshot "${2:-}"
        ;;
    workspace|ws)
        cmd_workspace "${2:-}"
        ;;
    restore)
        shift
        cmd_restore "$@"
        ;;
    find|search)
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Uso: ./claude-sessions.sh find <testo>${NC}"
            exit 1
        fi
        cmd_find "$2"
        ;;
    resume)
        cmd_resume
        ;;
    help|-h|--help)
        cmd_help
        ;;
    *)
        if [[ "$1" =~ ^[0-9]+$ ]]; then
            cmd_list "$1"
        else
            echo -e "${RED}Comando sconosciuto: $1${NC}"
            cmd_help
            exit 1
        fi
        ;;
esac
