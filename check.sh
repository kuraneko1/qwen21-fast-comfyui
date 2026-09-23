#!/usr/bin/env bash
# Static checks: shell syntax, python syntax, workflow JSON validity.
set -uo pipefail
fail=0
say() { printf '%-42s %s\n' "$1" "$2"; }

for sh in install.sh check.sh; do
  if bash -n "$sh" 2>/dev/null; then say "bash -n $sh" OK; else say "bash -n $sh" FAIL; fail=1; fi
done

py=python3
[ -x "${COMFY_DIR:-$HOME/ComfyUI}/.venv/bin/python" ] && py="${COMFY_DIR:-$HOME/ComfyUI}/.venv/bin/python"
for f in make_qwen21_workflows.py test_qwen21.py test_qwen21_edit.py \
         docs/capture_ui.py \
         custom_nodes/qwen21_fast/nodes.py custom_nodes/qwen21_fast/__init__.py; do
  if "$py" -m py_compile "$f" 2>/dev/null; then say "py_compile $f" OK; else say "py_compile $f" FAIL; fail=1; fi
done

for j in workflows/*.json; do
  if "$py" -c "import json,sys;json.load(open(sys.argv[1]))" "$j" 2>/dev/null; then
    say "json $j" OK; else say "json $j" FAIL; fail=1; fi
done

find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
[ "$fail" = 0 ] && echo "ALL CHECKS PASSED" || echo "CHECKS FAILED"
exit "$fail"
