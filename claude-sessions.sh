#!/bin/bash
# ============================================================
# Claude Code Sessions Tracker
#
# Traccia e recupera le sessioni Claude Code salvate localmente.
# Le conversazioni sono in ~/.claude/projects/ come file .jsonl.
# Per riprendere: claude --resume <SESSION_ID>
#
# Comandi:
#   ./claude-sessions.sh                  # lista sessioni di oggi
#   ./claude-sessions.sh list [giorni]    # lista sessioni (default: 1 giorno)
#   ./claude-sessions.sh snapshot [nome]  # salva snapshot sessioni attive
#   ./claude-sessions.sh find <testo>     # cerca nelle sessioni per contenuto
#   ./claude-sessions.sh resume           # mostra picker interattivo
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_PROJECTS="$HOME/.claude/projects"
SNAPSHOTS_DIR="$SCRIPT_DIR/snapshots"
INDEX_FILE="$SCRIPT_DIR/INDEX.md"

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Verifica
if [ ! -d "$CLAUDE_PROJECTS" ]; then
    echo -e "${RED}ERRORE: $CLAUDE_PROJECTS non trovata.${NC}"
    exit 1
fi

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

try:
    with open(jsonl_path, 'r') as f:
        for line in f:
            try:
                obj = json.loads(line)
                msg_type = obj.get('type', '')
                if msg_type == 'user':
                    user_count += 1
                    # Content can be in obj["message"]["content"] or obj["content"]
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
print(f"{first_user or '(vuoto)'}|||{last_user or '(vuoto)'}|||{total}|||{user_count}")
PYEOF
}

# ---- Funzione: short project name ----
short_project() {
    echo "$1" | sed 's/^-Users-v-*//' | sed 's/--/\//g' | sed 's/-/ /g' | rev | cut -d'/' -f1-2 | rev
}

# ---- Comando: list ----
cmd_list() {
    local days="${1:-1}"
    local count=0

    echo -e "${BOLD}Claude Code Sessions — ultimi $days giorno/i${NC}"
    echo -e "Aggiornato: $(date '+%Y-%m-%d %H:%M:%S')\n"

    # Genera anche INDEX.md
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

        info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0")
        first_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $1}')
        last_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $2}')
        msg_count=$(echo "$info" | awk -F'\\|\\|\\|' '{print $3}')

        count=$((count + 1))

        # Terminal output
        echo -e "${CYAN}[$count]${NC} ${BOLD}$mod_date${NC} — ${GREEN}${first_msg:0:80}${NC}"
        echo -e "    ${YELLOW}$short${NC} | ${msg_count} msg | ${file_size_kb}KB"
        echo -e "    ${BLUE}claude --resume $session_id${NC}"
        echo ""

        # INDEX.md output
        first_msg_escaped=$(echo "$first_msg" | sed 's/|/\\|/g' | cut -c1-60)
        echo "| $count | $mod_date | \`${session_id:0:8}…\` | $first_msg_escaped | $msg_count | \`claude --resume $session_id\` |" >> "$INDEX_FILE"

    done < <(find "$CLAUDE_PROJECTS" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" -mtime -"$days" -size +1k 2>/dev/null | \
        while read f; do echo "$(stat -f "%m" "$f") $f"; done | sort -rn | cut -d' ' -f2-)

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

    # Prendi solo sessioni modificate nelle ultime 4 ore (= probabilmente attive)
    while IFS= read -r jsonl_file; do
        session_id=$(basename "$jsonl_file" .jsonl)
        project_dir=$(basename "$(dirname "$jsonl_file")")
        mod_date=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$jsonl_file")
        file_size_kb=$(($(stat -f "%z" "$jsonl_file") / 1024))
        short=$(short_project "$project_dir")

        info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0")
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

    done < <(find "$CLAUDE_PROJECTS" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" -mmin -240 -size +1k 2>/dev/null | \
        while read f; do echo "$(stat -f "%m" "$f") $f"; done | sort -rn | cut -d' ' -f2-)

    echo -e "\n---\n" >> "$snapshot_file"
    echo "**Totale: $count sessioni attive**" >> "$snapshot_file"
    echo "" >> "$snapshot_file"
    echo "## Come recuperare" >> "$snapshot_file"
    echo '```bash' >> "$snapshot_file"
    echo '# Copia il comando "claude --resume <ID>" della sessione che vuoi riprendere' >> "$snapshot_file"
    echo '# Funziona da qualsiasi directory' >> "$snapshot_file"
    echo '```' >> "$snapshot_file"

    echo -e "\n${BOLD}Snapshot salvato: $snapshot_file${NC}"
    echo -e "${BOLD}Totale: $count sessioni${NC}"
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

            info=$(extract_info "$jsonl_file" 2>/dev/null || echo "(errore)||||(errore)||||0||||0")
            first_msg=$(echo "$info" | awk -F'\\|\\|\\|' '{print $1}')

            count=$((count + 1))
            echo -e "${CYAN}[$count]${NC} $mod_date — ${GREEN}${first_msg:0:80}${NC}"
            echo -e "    ${YELLOW}$short${NC}"
            echo -e "    ${BLUE}claude --resume $session_id${NC}"
            echo ""
        fi
    done < <(find "$CLAUDE_PROJECTS" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" -size +1k 2>/dev/null | \
        while read f; do echo "$(stat -f "%m" "$f") $f"; done | sort -rn | cut -d' ' -f2-)

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
    echo -e "  ${GREEN}./claude-sessions.sh${NC}                  Lista sessioni di oggi"
    echo -e "  ${GREEN}./claude-sessions.sh list [giorni]${NC}    Lista sessioni (default: 1)"
    echo -e "  ${GREEN}./claude-sessions.sh snapshot [nome]${NC}  Salva snapshot sessioni attive (ultime 4h)"
    echo -e "  ${GREEN}./claude-sessions.sh find <testo>${NC}     Cerca nelle sessioni"
    echo -e "  ${GREEN}./claude-sessions.sh resume${NC}           Picker interattivo Claude"
    echo -e "  ${GREEN}./claude-sessions.sh help${NC}             Questo messaggio"
    echo ""
    echo "Le sessioni Claude Code sono in ~/.claude/projects/*.jsonl"
    echo "Per riprendere: claude --resume <SESSION_ID>"
}

# ---- Main ----
case "${1:-list}" in
    list)
        cmd_list "${2:-1}"
        ;;
    snapshot)
        cmd_snapshot "${2:-}"
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
        # Se è un numero, trattalo come "list N"
        if [[ "$1" =~ ^[0-9]+$ ]]; then
            cmd_list "$1"
        else
            echo -e "${RED}Comando sconosciuto: $1${NC}"
            cmd_help
            exit 1
        fi
        ;;
esac
