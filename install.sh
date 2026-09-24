#!/usr/bin/env bash
# Qwen-Image-2.1 on a 12 GB GPU with ComfyUI - one-shot setup.
#
#   ./install.sh                 install (downloads ~17 GB of weights)
#   ./install.sh --dry-run       print what would happen, touch nothing
#   ./install.sh --with-comfyui   also install ComfyUI into ~/ComfyUI (Linux + NVIDIA)
#
# Tested on Ubuntu 24.04 + RTX 4070 12 GB (sm_89) + ComfyUI 0.37.0 (torch 2.14/cu130).
set -euo pipefail

COMFY="${COMFY:-$HOME/ComfyUI}"                  # ComfyUI checkout
MODELS="${MODELS:-$HOME/qwen-image-2.1-models}"  # where the weights are downloaded
COMFY_SERVICE="${COMFY_SERVICE:-}"               # systemd --user unit to restart, if any
DRY=0
WITH_COMFYUI=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --with-comfyui) WITH_COMFYUI=1 ;;
    *) echo "Usage: ./install.sh [--dry-run] [--with-comfyui]" >&2; exit 2 ;;
  esac
done

DIT="diffusion_models/qwen_image_2.1_int8_convrot.safetensors"     # 7.26 GB
TE="text_encoders/qwen3vl_8b_int8_convrot.safetensors"             # 9.35 GB
VAE="vae/qwen_image_2.1_vae_bf16.safetensors"                      # 0.68 GB

run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }

place() {   # put $1 where ComfyUI looks ($2) without clobbering a file the user put there
  src="$1"; dst="$2"; target="$dst/$(basename "$src")"
  if [ "$DRY" = 1 ]; then echo "+ ln -f $src $dst/   (copy if that fails)"; return 0; fi
  mkdir -p "$dst"
  if [ -e "$target" ]; then
    # Same size means it is already the right file (a previous run's hardlink, a symlink to the
    # download, or the user's own copy), so leave it exactly as it is.
    if [ "$(stat -c %s "$src" 2>/dev/null)" = "$(stat -c %s "$target" 2>/dev/null)" ]; then
      echo "  = $(basename "$target") is already in place - leaving it alone"
      return 0
    fi
    if [ -L "$target" ]; then
      echo "  ! $target is a symlink to $(readlink "$target") with a different size - replacing the link"
    else
      echo "  ! $target exists and differs - keeping your file as $(basename "$target").bak"
      cp -f "$target" "$target.bak"
    fi
  fi
  ln -f "$src" "$dst/" 2>/dev/null || {
    echo "  ! cannot hardlink (different filesystem?) - copying"
    cp -f "$src" "$dst/"
  }
}

install_file() {   # copy $1 over $2, keeping a modified $2 as .bak
  src="$1"; dst="$2"
  if [ "$DRY" = 1 ]; then echo "+ cp -f $src $dst"; return 0; fi
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] && ! cmp -s "$src" "$dst"; then
    echo "  ! $(basename "$dst") was changed - keeping your version as $(basename "$dst").bak"
    cp -f "$dst" "$dst.bak"
  fi
  cp -f "$src" "$dst"
}

install_dir() {   # update shipped files without removing other files in $2
  src="$1"; dst="$2"
  run mkdir -p "$dst"
  if [ "$DRY" != 1 ] && [ -f "$dst/nodes.py" ] && ! cmp -s "$src/nodes.py" "$dst/nodes.py"; then
    echo "  ! $dst/nodes.py was changed - keeping your version as nodes.py.bak"
    cp -f "$dst/nodes.py" "$dst/nodes.py.bak"
  fi
  run cp -r "$src"/. "$dst"/
  # a stale .pyc left over from the previous version would be loaded instead of the new source
  if [ "$DRY" != 1 ]; then
    find "$dst" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  fi
}

if [ "$WITH_COMFYUI" = 1 ]; then
  [ "$(uname -s)" = Linux ] || { echo "--with-comfyui currently supports Linux only" >&2; exit 1; }
  for tool in git python3 nvidia-smi; do
    command -v "$tool" >/dev/null || { echo "Need $tool before installing ComfyUI" >&2; exit 1; }
  done
  nvidia-smi -L >/dev/null || { echo "NVIDIA GPU/driver not available to nvidia-smi" >&2; exit 1; }
  python3 -c 'import sys, venv, ensurepip; assert sys.version_info >= (3, 10)' || {
    echo "Need Python 3.10+ with venv support (on Ubuntu: install python3-venv)" >&2; exit 1;
  }
  marker="$COMFY/.qwen21-fast-bootstrap"
  if [ -e "$COMFY" ] && [ ! -f "$marker" ]; then
    echo "Found $COMFY but it was not created by --with-comfyui. Use ./install.sh for an existing ComfyUI." >&2
    exit 1
  fi
  echo "== set up ComfyUI (Linux + NVIDIA) -> $COMFY"
  if [ ! -d "$COMFY" ]; then
    run mkdir -p "$(dirname "$COMFY")"
    run git clone --depth 1 https://github.com/Comfy-Org/ComfyUI.git "$COMFY"
    if [ "$DRY" != 1 ]; then touch "$marker"; fi
  fi
  venv_python="$COMFY/.venv/bin/python"
  if [ ! -x "$venv_python" ]; then run python3 -m venv "$COMFY/.venv"; fi
  run "$venv_python" -m pip install --upgrade pip
  # Pinned to the versions this repository was measured with (the +cu130 builds): with only
  # --extra-index-url, pip may pick a different build from PyPI instead.
  run "$venv_python" -m pip install \
    "torch==2.14.0+cu130" "torchvision==0.29.0+cu130" "torchaudio==2.11.0+cu130" \
    --extra-index-url https://download.pytorch.org/whl/cu130
  run "$venv_python" -m pip install -r "$COMFY/requirements.txt"
  run "$venv_python" -m pip install --upgrade huggingface_hub
  if [ "$DRY" != 1 ] && ! "$venv_python" -c \
       'import torch; assert torch.version.cuda and torch.cuda.is_available()'; then
    echo "CUDA is unavailable in the new virtual environment. Check the NVIDIA driver and PyTorch installation." >&2
    exit 1
  fi
fi

if [ -n "${HF_CLI:-}" ]; then
  hf_cli="$HF_CLI"
elif [ "$WITH_COMFYUI" = 1 ]; then
  hf_cli="$COMFY/.venv/bin/hf"
elif [ -x "$COMFY/.venv/bin/hf" ]; then
  hf_cli="$COMFY/.venv/bin/hf"
else
  hf_cli="$(command -v hf || true)"
fi
if [ "$DRY" != 1 ] || [ "$WITH_COMFYUI" != 1 ]; then
  [ -n "$hf_cli" ] && [ -x "$hf_cli" ] || {
    echo "Need the 'hf' CLI: https://huggingface.co/docs/huggingface_hub/installation#install-the-hugging-face-cli" >&2
    exit 1
  }
  [ -d "$COMFY" ] || { echo "ComfyUI not found at $COMFY (set COMFY=..., or add --with-comfyui)" >&2; exit 1; }
  if [ ! -f "$COMFY/comfy_extras/nodes_qwen.py" ] ||
     ! grep -q 'class TextEncodeQwenImage21' "$COMFY/comfy_extras/nodes_qwen.py"; then
    echo "ComfyUI at $COMFY is missing TextEncodeQwenImage21 (update to ComfyUI 0.37+ first)" >&2
    exit 1
  fi
fi

echo "== 1/4 weights (~17 GB, resumable) -> $MODELS"
for f in "$DIT" "$TE" "$VAE"; do
  run "$hf_cli" download Comfy-Org/Qwen-Image-2.1 "$f" --local-dir "$MODELS"
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
for wf in "$here"/workflows/*.json; do
  install_file "$wf" "$COMFY/user/default/workflows/$(basename "$wf")"
done
install_file "$here/docs/demo/source.png" "$COMFY/input/qwen21_demo_source.png"

echo "== 4/4 start or restart ComfyUI"
# `|| true` keeps a no-match case non-fatal, and nothing here pipes into a consumer that stops
# reading early (grep -q would kill the producer with SIGPIPE and fail the script with 141 under
# `set -o pipefail`). Set COMFY_SERVICE if the unit name is not auto-detectable.
if [ "$WITH_COMFYUI" = 1 ]; then
  echo "  New ComfyUI installation: start it in a terminal with:"
  printf '  cd %q && %q main.py\n' "$COMFY" "$COMFY/.venv/bin/python"
else
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
