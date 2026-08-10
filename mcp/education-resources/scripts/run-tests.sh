#!/usr/bin/env bash
# Run education-resource-mcp tests in an isolated Linux-native temporary tree.
set -euo pipefail

SERVICE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_TMP_PARENT="${EDUCATION_RESOURCE_TEST_TMP_PARENT:-/tmp}"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 2
}

if [[ -n "${EDUCATION_RESOURCE_MCP_PYTHON:-}" ]]; then
    PYTHON_BIN="$EDUCATION_RESOURCE_MCP_PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${SERVICE_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${SERVICE_ROOT}/.venv/bin/python"
else
    fail "set EDUCATION_RESOURCE_MCP_PYTHON to the intended virtualenv interpreter"
fi

[[ -x "$PYTHON_BIN" ]] || fail "Python interpreter is not executable: $PYTHON_BIN"
[[ -d "$TEST_TMP_PARENT" ]] || fail "test tmp parent does not exist: $TEST_TMP_PARENT"
command -v findmnt >/dev/null 2>&1 || fail "findmnt is required to reject non-native test filesystems"
command -v setsid >/dev/null 2>&1 || fail "setsid is required for bounded test-process cleanup"

filesystem_type="$(findmnt -n -o FSTYPE -T "$TEST_TMP_PARENT" 2>/dev/null || true)"
[[ -n "$filesystem_type" ]] || fail "cannot determine filesystem type for $TEST_TMP_PARENT"
case "$filesystem_type" in
    9p|drvfs)
        fail "test tmp parent is $filesystem_type ($TEST_TMP_PARENT); use a native Linux filesystem such as /tmp"
        ;;
esac

case "${1:-all}" in
    all)
        test_args=(discover -s tests -v)
        ;;
    e2e)
        test_args=(discover -s tests -p 'test_e2e_*.py' -v)
        ;;
    *)
        fail "usage: $0 [all|e2e]"
        ;;
esac

TEST_ROOT="$(mktemp -d "${TEST_TMP_PARENT%/}/education-resource-mcp-tests.XXXXXXXX")"
active_child_pid=""
cleanup() {
    rm -rf -- "$TEST_ROOT"
}
stop_active_child() {
    if [[ -z "$active_child_pid" ]] || ! kill -0 "$active_child_pid" 2>/dev/null; then
        active_child_pid=""
        return
    fi
    # ``setsid`` makes the child PID its process-group ID, so this also stops
    # any MCP fixture descendants before their HOME/TMP/data root is removed.
    kill -TERM -- "-$active_child_pid" 2>/dev/null || true
    wait "$active_child_pid" 2>/dev/null || true
    active_child_pid=""
}
exit_for_signal() {
    local status="$1"
    trap - HUP INT TERM
    stop_active_child
    exit "$status"
}
run_isolated_child() {
    local status
    setsid "$@" &
    active_child_pid=$!
    if wait "$active_child_pid"; then
        status=0
    else
        status=$?
    fi
    active_child_pid=""
    return "$status"
}
trap cleanup EXIT
# A signal must stop the active process group before the EXIT trap removes live
# HOME/TMP/data; otherwise a fixture child can continue against deleted state.
trap 'exit_for_signal 129' HUP
trap 'exit_for_signal 130' INT
trap 'exit_for_signal 143' TERM

mkdir -p "$TEST_ROOT/tmp" "$TEST_ROOT/home" "$TEST_ROOT/default-data" \
    "$TEST_ROOT/default-library" "$TEST_ROOT/pycache" \
    "$TEST_ROOT/xdg-cache" "$TEST_ROOT/xdg-config" "$TEST_ROOT/xdg-data"

export HOME="$TEST_ROOT/home"
export XDG_CACHE_HOME="$TEST_ROOT/xdg-cache"
export XDG_CONFIG_HOME="$TEST_ROOT/xdg-config"
export XDG_DATA_HOME="$TEST_ROOT/xdg-data"
export TMPDIR="$TEST_ROOT/tmp"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
export EDUCATION_RESOURCE_MCP_DATA_DIR="$TEST_ROOT/default-data"
export EDUCATION_RESOURCE_MCP_LIBRARY_DIR="$TEST_ROOT/default-library"
export PYTHONPYCACHEPREFIX="$TEST_ROOT/pycache"
export EDUCATION_RESOURCE_TEST_PYCACHE_DIR="$PYTHONPYCACHEPREFIX"
# Bytecode is allowed only in the isolated run root.  The verifier, unittest
# process, and E2E children reuse this cache so a hermetic child does not pay a
# full dependency cold-compile cost inside the unchanged JSON-RPC timeout.
unset PYTHONDONTWRITEBYTECODE
export PYTHONHASHSEED=0
# Tests must not consume the developer's real session store or network backend.
unset EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR
unset EDUCATION_RESOURCE_MCP_SEARXNG_URL

printf 'Using interpreter: %s\n' "$PYTHON_BIN"
printf 'Using isolated test root: %s (%s)\n' "$TEST_ROOT" "$filesystem_type"
run_isolated_child "$PYTHON_BIN" "$SERVICE_ROOT/scripts/verify_runtime_environment.py"

cd "$SERVICE_ROOT"
run_isolated_child "$PYTHON_BIN" -m unittest "${test_args[@]}"
