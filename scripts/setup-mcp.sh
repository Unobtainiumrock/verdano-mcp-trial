#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Verdano MCP — one-command setup for Cursor and Claude Desktop
#
# Usage:  ./scripts/setup-mcp.sh
#
# Idempotent — safe to re-run at any time.
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── colours (disabled when piped) ─────────────────────────────────────
if [ -t 1 ]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'
  CYAN='\033[0;36m';  NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; CYAN=''; NC=''
fi

info()  { printf "${CYAN}[info]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[  ok]${NC}  %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$*"; }
fail()  { printf "${RED}[fail]${NC}  %s\n" "$*"; }

# ── pre-flight: uv must be installed ──────────────────────────────────
if ! command -v uv &>/dev/null; then
  fail "uv is not installed.  Install it first: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

# ── 1. install / sync dependencies ────────────────────────────────────
info "Running uv sync …"
(cd "$PROJECT_ROOT" && uv sync --quiet)
ok   "Dependencies installed"

# ── 2. .env setup ─────────────────────────────────────────────────────
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    info "Created .env from .env.example"
  else
    cat > "$ENV_FILE" <<'ENVEOF'
# Verdano ERP credentials — get the API key from the trial instructions.
VERDANO_ERP_BASE_URL=https://erp.corvera.ai
VERDANO_ERP_API_KEY=
ENVEOF
    info "Created .env template"
  fi
fi

# Prompt for API key if empty
if ! grep -qE '^VERDANO_ERP_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
  warn "VERDANO_ERP_API_KEY is not set in $ENV_FILE"
  printf "  Enter your ERP API key (or press Enter to skip): "
  read -r api_key
  if [ -n "$api_key" ]; then
    if grep -q '^VERDANO_ERP_API_KEY=' "$ENV_FILE"; then
      # Replace existing empty line
      python3 -c "
import re, pathlib
p = pathlib.Path('$ENV_FILE')
p.write_text(re.sub(r'^VERDANO_ERP_API_KEY=.*$', 'VERDANO_ERP_API_KEY=$api_key', p.read_text(), flags=re.M))
"
    else
      echo "VERDANO_ERP_API_KEY=$api_key" >> "$ENV_FILE"
    fi
    ok "API key saved to .env"
  else
    warn "Skipping — you can add it later by editing $ENV_FILE"
  fi
else
  ok ".env already has an API key"
fi

# ── 3. MCP config injection ──────────────────────────────────────────
# The JSON block we inject into each host's config file.
MCP_ENTRY_PYTHON="
import json, sys, pathlib

config_path = pathlib.Path(sys.argv[1])
project_root = '$PROJECT_ROOT'

entry = {
    'command': 'uv',
    'args': ['--directory', project_root, 'run', 'verdano-mcp'],
    'env': {'VERDANO_PROJECT_ROOT': project_root}
}

if config_path.exists():
    cfg = json.loads(config_path.read_text())
else:
    cfg = {}

# Cursor uses top-level 'mcpServers'; Claude uses 'mcpServers' too.
servers = cfg.setdefault('mcpServers', {})
servers['verdano'] = entry
config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(cfg, indent=2) + '\n')
"

inject_config() {
  local label="$1" config_file="$2"
  if python3 -c "$MCP_ENTRY_PYTHON" "$config_file" 2>/dev/null; then
    ok "$label config updated: $config_file"
  else
    warn "Could not update $label config at $config_file"
  fi
}

# Cursor
CURSOR_CONFIG="$HOME/.cursor/mcp.json"
inject_config "Cursor" "$CURSOR_CONFIG"

# Claude Desktop
case "$(uname -s)" in
  Darwin) CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
  *)      CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json" ;;
esac
inject_config "Claude Desktop" "$CLAUDE_CONFIG"

# ── 4. health check ──────────────────────────────────────────────────
info "Running health check …"
echo ""
if (cd "$PROJECT_ROOT" && VERDANO_PROJECT_ROOT="$PROJECT_ROOT" uv run verdano-mcp --health); then
  echo ""
  ok "Setup complete!"
else
  echo ""
  warn "Health check reported issues — see above. The MCP entry is configured; fix any remaining items and re-run."
fi

# ── 5. restart reminder ──────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────┐"
echo "│  Restart Cursor / Claude Desktop to load the new    │"
echo "│  MCP configuration.  Then ask:                      │"
echo "│                                                     │"
echo "│    \"Analyze Tesco week 2026-W20\"                    │"
echo "│                                                     │"
echo "│  to verify the tools are working.                   │"
echo "└─────────────────────────────────────────────────────┘"
