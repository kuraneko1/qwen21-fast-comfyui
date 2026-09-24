#!/usr/bin/env bash
# Qwen-Image-2.1 on a 12 GB GPU with ComfyUI - one-shot setup.
#
#   ./install.sh                 install (downloads ~17 GB of weights)
#   ./install.sh --dry-run       print what would happen, touch nothing
#
# Tested on Ubuntu 24.04 + RTX 4070 12 GB (sm_89) + ComfyUI 0.37.0 (torch 2.14/cu130).
set -euo pipefail

COMFY="${COMFY:-$HOME/ComfyUI}"                  # ComfyUI checkout
MODELS="${MODELS:-$HOME/qwen-image-2.1-models}"  # where the weights are downloaded
COMFY_SERVICE="${COMFY_SERVICE:-}"               # systemd --user unit to restart, if any
DRY=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY=1 ;;
  *) echo "Usage: ./install.sh [--dry-run]" >&2; exit 2 ;;
esac

DIT="diffusion_models/qwen_image_2.1_int8_convrot.safetensors"     # 7.26 GB
TE="text_encoders/qwen3vl_8b_int8_convrot.safetensors"             # 9.35 GB
VAE="vae/qwen_image_2.1_vae_bf16.safetensors"                      # 0.68 GB

run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }

place() {   # hardlink $1 into directory $2; copies instead across filesystems
  src="$1"; dst="$2"
  if [ "$DRY" = 1 ]; then echo "+ ln -f $src $dst/   (copy if that fails)"; return 0; fi
  mkdir -p "$dst"
  ln -f "$src" "$dst/" 2>/dev/null || {
    echo "  ! cannot hardlink (different filesystem?) - copying"
    cp -f "$src" "$dst/"
  }
}

install_dir() {   # update shipped files without removing other files in $2
  src="$1"; dst="$2"
  run mkdir -p "$dst"
  run cp -r "$src"/. "$dst"/
}

command -v hf >/dev/null || { echo "Need the 'hf' CLI: https://huggingface.co/docs/huggingface_hub/installation#install-the-hugging-face-cli"; exit 1; }
[ -d "$COMFY" ] || { echo "ComfyUI not found at $COMFY (set COMFY=...)"; exit 1; }
if [ ! -f "$COMFY/comfy_extras/nodes_qwen.py" ] ||
   ! grep -q 'class TextEncodeQwenImage21' "$COMFY/comfy_extras/nodes_qwen.py"; then
  echo "ComfyUI at $COMFY is missing TextEncodeQwenImage21 (update to ComfyUI 0.37+ first)" >&2
  exit 1
fi

echo "== 1/4 weights (~17 GB, resumable) -> $MODELS"
for f in "$DIT" "$TE" "$VAE"; do
  run hf download Comfy-Org/Qwen-Image-2.1 "$f" --local-dir "$MODELS"
  if [ "$DRY" != 1 ] && [ ! -f "$MODELS/$f" ]; then
    echo "download did not produce $MODELS/$f - stopping" >&2
    exit 1
  fi
done

echo "== 2/4 place them where ComfyUI looks (hardlinks, or copies across filesystems)"
place "$MODELS/$DIT" "$COMFY/models/diffusion_models"
place "$MODELS/$TE"  "$COMFY/models/text_encoders"
place "$MODELS/$VAE" "$COMFY/models/vae"

echo "== 3/4 custom node + workflows + demo image"
here="$(cd "$(dirname "$0")" && pwd)"
run mkdir -p "$COMFY/custom_nodes" "$COMFY/user/default/workflows" "$COMFY/input"
install_dir "$here/custom_nodes/qwen21_fast" "$COMFY/custom_nodes/qwen21_fast"
run cp -f "$here"/workflows/*.json "$COMFY/user/default/workflows/"
run cp -f "$here/docs/demo/source.png" "$COMFY/input/qwen21_demo_source.png"

echo "== 4/4 restart ComfyUI (systemd user unit; adjust if you run it another way)"
# `|| true` keeps a no-match case non-fatal, and nothing here pipes into a consumer that stops
# reading early (grep -q would kill the producer with SIGPIPE and fail the script with 141 under
# `set -o pipefail`). Set COMFY_SERVICE if the unit name is not auto-detectable.
if [ -z "$COMFY_SERVICE" ]; then
  # Service units only (a .timer/.socket whose name contains "comfy" is not ComfyUI), and a
  # running one first so we restart what is actually serving instead of a stopped file.
  COMFY_SERVICE="$(systemctl --user list-units --type=service --no-legend --plain 2>/dev/null \
                   | awk 'tolower($1) ~ /comfy/ {print $1; exit}' || true)"
  if [ -z "$COMFY_SERVICE" ]; then
    COMFY_SERVICE="$(systemctl --user list-unit-files --type=service --no-legend --plain 2>/dev/null \
                     | awk 'tolower($1) ~ /comfy/ {print $1; exit}' || true)"
  fi
fi
if [ -n "$COMFY_SERVICE" ]; then
  echo "  detected service: $COMFY_SERVICE"
  run systemctl --user restart "$COMFY_SERVICE"
else
  echo
  echo "  *** RESTART REQUIRED ***"
  echo "  No ComfyUI systemd --user service matched 'comfy', so nothing was restarted."
  echo "  Custom nodes and workflows are only read at startup - start or restart ComfyUI"
  echo "  yourself (or pass COMFY_SERVICE=<unit> on the next run), then reload its page."
fi

cat <<'EOF'

Done. In the ComfyUI UI, open one of these workflows and press Run:
  qwen21_fast_t2i                      text to image
  qwen21_fast_edit                     source to underwater (random seed)
  qwen21_fast_edit_underwater_fixed    source to underwater (fixed seed)

  first image, 1024x1024, 12 steps   ~10-15 s   (RTX 4070 12 GB)
  2048x2048 (4 MP), 20 steps         ~90 s

Keep cfg at 1.0 and use euler/simple: that is this model's official setting, and any cfg
above 1.0 makes ComfyUI run a second unconditional pass per step (2x the time) for a
contrastier image.
EOF
