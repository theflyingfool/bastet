#!/usr/bin/env bash
# Drive the real `bastet` CLI end to end against a throwaway sandbox: its own config, data dir and
# inventory, never yours. Usage:
#   .claude/skills/run-bastet/smoke.sh            # full flow, prints each step, keeps the sandbox
#   .claude/skills/run-bastet/smoke.sh shell      # just print the env exports for a sandbox to use by hand
# Exit code is non-zero on the first step that doesn't behave as expected.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
SANDBOX="${SANDBOX:-$(mktemp -d "${TMPDIR:-/tmp}/bastet-sandbox.XXXX")}"
export BASTET_CONFIG="$SANDBOX/cfg/bastet.yml"   # config + Bastet's SSH key live here
export XDG_DATA_HOME="$SANDBOX/data"             # snapshots, .bastet bookkeeping
export XDG_RUNTIME_DIR="$SANDBOX/run"            # SSH control sockets
LAB="$SANDBOX/lab"                               # the inventory (an Obsidian vault + git repo)
B=(uv run --quiet --project "$REPO" bastet)

if [[ "${1:-}" == "shell" ]]; then
  echo "export BASTET_CONFIG=$BASTET_CONFIG XDG_DATA_HOME=$XDG_DATA_HOME XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
  echo "alias bastet='uv run --quiet --project $REPO bastet'   # inventory: $LAB"
  exit 0
fi

step() { echo; echo "### $*"; }
expect() {  # expect <exit-code> <text-or-empty> -- <bastet args...>
  local want_rc=$1 want_text=$2; shift 3
  local out rc
  out=$(cd "$LAB" 2>/dev/null || cd "$SANDBOX"; "${B[@]}" "$@" 2>&1); rc=$?
  echo "$out" | tail -n 15
  if [[ $rc -ne $want_rc ]]; then echo "FAIL: bastet $* exited $rc (wanted $want_rc)"; exit 1; fi
  if [[ -n "$want_text" && "$out" != *"$want_text"* ]]; then echo "FAIL: bastet $* output lacks: $want_text"; exit 1; fi
}

echo "sandbox: $SANDBOX"

step "init (non-interactive; this machine not managed)"
expect 0 "Bastet's public key" -- init -y --inventory "$LAB" --lab-name Lab

step "add hosts: an unmanaged device and a VPS (example data only)"
expect 0 "" -- add host ps5-1 --type other --ip 10.1.0.40 -y
expect 0 "" -- add host vps1 --type vps --provider linode --ip 203.0.113.10 -y

step "show: the inventory list, then one host, then a selector"
expect 0 "vps1" -- show
expect 0 "Gathered facts" -- show vps1
expect 0 "ps5-1" -- show @other

step "add role: packages for the whole lab"
expect 0 "" -- add role packages --to lab -y

step "run -c: check every host. ps5-1 (type other) is skipped; vps1 can't be reached from here"
expect 1 "not managed by Bastet" -- run -c

step "run -g on an address that answers nothing: reported per host, nothing written"
expect 0 "nothing answered" -- run -g vps1 -y   # an unreachable host is reported, but the run still exits 0

step "doctor: everything wrong, read-only"
expect 0 "" -- doctor

step "selector errors"
expect 1 "no group or type named" -- run -c @nope
expect 1 "matches no host" -- run -c "zz-*"

step "refresh (hidden command) and the generated notes"
expect 0 "" -- refresh
for f in "_bastet/docs/Bastet guide.md" "_bastet/groups/vps.md" "_templates/Host - other.md" "_bastet/facts/vps1 facts.md"; do
  [[ -f "$LAB/$f" ]] && echo "ok: $f" || { echo "FAIL: missing $f"; exit 1; }
done

step "git history: one commit per command"
git -C "$LAB" log --format='%h %s' | head -n 8

echo; echo "SMOKE OK  (sandbox kept at $SANDBOX)"
