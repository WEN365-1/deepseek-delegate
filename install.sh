#!/bin/bash
# Install the deepseek-delegate skill for Claude Code.
#   1. copy skill/ to <claude config dir>/skills/deepseek-delegate
#   2. install the launcher to ~/.local/bin/ds-run.sh
#   3. add the allow rule "Bash(~/.local/bin/ds-run.sh:*)" to settings.json (backed up first)
# Re-running is safe: existing copies are backed up, the rule is added only once.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
skill_dir="$cfg/skills/deepseek-delegate"
bin_dir="$HOME/.local/bin"
settings="$cfg/settings.json"
stamp="$(date +%Y%m%d%H%M%S)"

py="$(command -v python3 || command -v python || true)"
[[ -n "$py" ]] || { echo "python3 or python is required to edit settings.json" >&2; exit 1; }

mkdir -p "$cfg/skills" "$bin_dir"
# back up outside skills/, otherwise Claude Code loads the backup as a second skill
if [[ -d "$skill_dir" ]]; then
  mkdir -p "$cfg/skill-backups"
  mv "$skill_dir" "$cfg/skill-backups/deepseek-delegate.bak_$stamp"
  echo "old skill backed up to $cfg/skill-backups/deepseek-delegate.bak_$stamp"
fi
cp -R "$here/skill" "$skill_dir"
echo "skill installed: $skill_dir"

if [[ -f "$bin_dir/ds-run.sh" ]]; then
  cp "$bin_dir/ds-run.sh" "$bin_dir/ds-run.sh.bak_$stamp"
fi
cp "$here/skill/scripts/ds-run.sh" "$bin_dir/ds-run.sh"
chmod +x "$bin_dir/ds-run.sh"
echo "launcher installed: $bin_dir/ds-run.sh"

[[ -f "$settings" ]] && cp "$settings" "$settings.bak_$stamp" || echo '{}' > "$settings"
"$py" - "$settings" <<'EOF'
import json, sys
p = sys.argv[1]
with open(p, encoding="utf-8") as f:
    d = json.load(f)
allow = d.setdefault("permissions", {}).setdefault("allow", [])
rule = "Bash(~/.local/bin/ds-run.sh:*)"
if rule not in allow:
    allow.append(rule)
with open(p, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
base = d.get("env", {}).get("ANTHROPIC_BASE_URL", "")
print("allow rule present in", p)
if "deepseek" not in base:
    print("NOTE: ANTHROPIC_BASE_URL in settings.json does not point to DeepSeek yet; see README step 1.")
EOF

case ":$PATH:" in *":$bin_dir:"*) ;; *) echo "NOTE: $bin_dir is not on PATH (the skill calls it by full path, so this is fine)";; esac
echo "done."
