#!/usr/bin/env bash
# Sync MCP packages and skills from the WSL repo to the Windows OpenClaw deployment.
#
# Run from WSL:  bash scripts/sync-to-openclaw.sh
# After sync, restart the OpenClaw gateway on Windows and verify:
#   openclaw gateway restart
#   openclaw mcp doctor education-resources --probe
#   openclaw mcp doctor session-manager  --probe
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO="/home/admin_quanxiao/projects/quanxiao/collector_flow_ver"
WIN_LOCAL="/mnt/c/Users/admin/AppData/Local/OpenClaw"
WIN_HOME="/mnt/c/Users/admin"

EDU_PKG="$WIN_LOCAL/packages/education-resources/0.2.0"
EDU_SRC="$EDU_PKG/source"
EDU_PY="$EDU_PKG/venv/Scripts/python.exe"

SES_PKG="$WIN_LOCAL/packages/session-manager/current"
SES_SRC="$SES_PKG/source"          # created by this script
SES_PY="$SES_PKG/venv/Scripts/python.exe"

LRF_SKILL_TARGET="$WIN_LOCAL/packages/learning-resource-flow/current/skill"

# session-login-flow is a symlink — resolve to the real dir.
SES_LOGIN_TARGET="$WIN_HOME/.openclaw/skills/session-login-flow"
if [ -L "$SES_LOGIN_TARGET" ]; then
    SES_LOGIN_TARGET="$(readlink -f "$SES_LOGIN_TARGET")"
fi

RSYNC_EXCLUDES=(
    --exclude __pycache__
    --exclude '*.pyc'
    --exclude .pytest_cache
    --exclude venv
    --exclude build
    --exclude '*.egg-info'
    --exclude database.sqlite
    --exclude '.git'
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
section() { echo -e "\n\033[1;34m▶ $1\033[0m"; }
ok()      { echo -e "  \033[32m✓\033[0m $1"; }
fail()    { echo -e "  \033[31m✗\033[0m $1"; exit 1; }

winpath() { wslpath -w "$1"; }

install_editable() {
    local python_executable="$1"
    local source_path="$2"
    local package_name="$3"
    local output status

    if output="$("$python_executable" -m pip install -e "$source_path" 2>&1)"; then
        printf '%s\n' "$output" | grep -E 'Successfully|error|ERROR|already satisfied' || true
        return 0
    else
        status=$?
        printf '%s\n' "$output" >&2
        printf '  pip install -e failed for %s (exit status %s)\n' "$package_name" "$status" >&2
        return "$status"
    fi
}

check_exists() {
    for p in "$@"; do
        if [ ! -e "$p" ]; then fail "Path not found: $p"; fi
    done
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
section "Pre-flight checks"
check_exists "$REPO/mcp/education-resources/src" \
             "$REPO/mcp/session-manager/src" \
             "$REPO/skills/learning-resource-flow/SKILL.md" \
             "$EDU_PY" "$SES_PY"
ok "All source and venv paths verified"

# ---------------------------------------------------------------------------
# 1. education-resources MCP
# ---------------------------------------------------------------------------
section "Syncing education-resources MCP"
rsync -av --delete "${RSYNC_EXCLUDES[@]}" \
    "$REPO/mcp/education-resources/" "$EDU_SRC/" \
    | grep -v '/$' || true      # don't print directory lines
ok "Source synced to $(winpath "$EDU_SRC")"

install_editable "$EDU_PY" "$(winpath "$EDU_SRC")" "education-resources"
ok "Package reinstalled in venv"

"$EDU_PY" -m pip check
ok "Dependency consistency check passed"
"$EDU_PY" "$(winpath "$EDU_SRC/scripts/verify_runtime_environment.py")"
ok "Runtime environment verification passed"

# Smoke test — verify new adapters load
"$EDU_PY" -c "
from education_resource_mcp.adapters.douyin import DouyinSearchAdapter, sign_a_bogus
from education_resource_mcp.adapters.douyin_download import DouyinDownloader
from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
print('  adapters: douyin, douyin_download, bilibili import OK')
" 2>&1 && ok "Import smoke test passed" || fail "Import smoke test FAILED"

# ---------------------------------------------------------------------------
# 2. session-manager MCP
# ---------------------------------------------------------------------------
section "Syncing session-manager MCP"
mkdir -p "$SES_SRC"
rsync -av --delete "${RSYNC_EXCLUDES[@]}" \
    --exclude distribution \
    "$REPO/mcp/session-manager/" "$SES_SRC/" \
    | grep -v '/$' || true
ok "Source synced to $(winpath "$SES_SRC")"

install_editable "$SES_PY" "$(winpath "$SES_SRC")" "session-manager"
ok "Package reinstalled in venv"

"$SES_PY" -m pip check
ok "Dependency consistency check passed"

# Smoke test — verify douyin registration
"$SES_PY" -c "
from session_manager.store import _PLATFORM_LIST
ids = [p.platform_id for p in _PLATFORM_LIST]
assert 'douyin' in ids, f'douyin not in {ids}'
print(f'  registered platforms: {ids}')
" 2>&1 && ok "Import smoke test passed" || fail "Import smoke test FAILED"

# ---------------------------------------------------------------------------
# 3. Skills
# ---------------------------------------------------------------------------
section "Syncing learning-resource-flow skill"
rsync -av --delete "${RSYNC_EXCLUDES[@]}" \
    "$REPO/skills/learning-resource-flow/" "$LRF_SKILL_TARGET/" \
    | grep -v '/$' || true
ok "Skill synced to $(winpath "$LRF_SKILL_TARGET")"

section "Syncing session-login-flow skill"
if [ -d "$REPO/mcp/session-manager/distribution/skills/session-login-flow" ]; then
    rsync -av --delete "${RSYNC_EXCLUDES[@]}" \
        "$REPO/mcp/session-manager/distribution/skills/session-login-flow/" "$SES_LOGIN_TARGET/" \
        | grep -v '/$' || true
    ok "Skill synced to $(winpath "$SES_LOGIN_TARGET")"
else
    echo "  (skipped — no session-login-flow in repo distribution)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section "Sync complete"
cat <<'EOF'

  Next steps (run in a Windows terminal):
    openclaw gateway restart
    openclaw mcp doctor education-resources --probe
    openclaw mcp doctor session-manager  --probe

  Or if OpenClaw is managed as a scheduled task, restart via Task Scheduler.
EOF
