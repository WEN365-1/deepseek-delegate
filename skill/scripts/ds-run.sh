#!/bin/bash
# Run one task with the DeepSeek-backed terminal claude, restricted to a command whitelist.
# Usage: ds-run.sh <project directory> <instruction file or text> [extra claude args, e.g. --resume <session_id>]
# Set DS_ALLOW_PUSH=1 to allow git push for this one run only (when the user has authorized it).
set -euo pipefail
proj="$(cd "${1:?missing project directory}" && pwd -P)"; task="${2:?missing instruction}"; shift 2
[[ -f "$task" ]] && task="Read the instruction file $task and execute it strictly as written; write the report to the file it names."

allow=("Read" "Write" "Edit" "Glob" "Grep"
  "Bash(python:*)" "Bash(python3:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)"
  "Bash(tail:*)" "Bash(wc:*)" "Bash(date:*)" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)"
  "PowerShell(python:*)" "PowerShell(ls:*)" "PowerShell(Get-ChildItem:*)" "PowerShell(Get-Content:*)"
  "PowerShell(Test-Path:*)" "PowerShell(git status:*)" "PowerShell(git diff:*)" "PowerShell(git log:*)")
deny=("Bash(rm:*)" "Bash(sudo:*)" "PowerShell(Remove-Item:*)" "PowerShell(rm:*)" "PowerShell(del:*)")
if [[ "${DS_ALLOW_PUSH:-0}" == 1 ]]; then
  allow+=("Bash(git remote:*)" "Bash(git push:*)" "Bash(git branch:*)" "PowerShell(git remote:*)" "PowerShell(git push:*)" "PowerShell(git branch:*)")
else
  deny+=("Bash(git push:*)" "PowerShell(git push:*)")
fi

# Keep the proxy that env -i would drop. Only non-empty values, same value for both cases:
# Windows env names are case-insensitive, so an empty https_proxy would wipe HTTPS_PROXY.
proxy=()
for v in HTTP_PROXY HTTPS_PROXY NO_PROXY; do
  lc="$(printf '%s' "$v" | tr 'A-Z' 'a-z')"
  val="${!v:-${!lc:-}}"
  [[ -n "$val" ]] && proxy+=("$v=$val" "$lc=$val")
done

cd "$proj"
exec env -i HOME="$HOME" PATH="$PATH" USER="${USER:-${USERNAME:-}}" USERPROFILE="${USERPROFILE:-}" APPDATA="${APPDATA:-}" LOCALAPPDATA="${LOCALAPPDATA:-}" SYSTEMROOT="${SYSTEMROOT:-}" TEMP="${TEMP:-/tmp}" TMP="${TMP:-/tmp}" LANG=en_US.UTF-8 TERM=xterm \
  "${proxy[@]}" \
  timeout 1800 claude -p "$task" "$@" \
  --permission-mode dontAsk \
  --allowedTools "${allow[@]}" \
  --disallowedTools "${deny[@]}" \
  --output-format json
