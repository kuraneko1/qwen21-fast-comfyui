**Japanese → [README.md](README.md)**

# Running Qwen-Image-2.1 on a 12GB GPU with ComfyUI (a beginner's notes)

> [!NOTE]
> **This repository does nothing special.** It is a set of notes where I (a beginner) wrote down the
> environment I put together on my own PC, exactly as it was, so I would not forget it. I would be happy
> if it helps someone trying the same thing, but **there is no guarantee it works** — it just means it
> worked on my machine.
> If something comes up, tell me on X at [@\_ryu15\_](https://x.com/_ryu15_) or in an issue on this repository.

Qwen-Image-2.1 (a 7.1B image generation model plus an 8B text encoder) is about 33GB as-is, so it needs a
big GPU. Using the official quantized weights brings it down to **17GB on disk**, and it can generate
**1024x1024 in about 10 seconds and 2K (2048x2048) in about 90 seconds on a 12GB RTX 4070**. You do not
have to write any Python — adding **a single node** to ComfyUI is all it takes.

> [!WARNING]
> **These instructions assume Linux (verified on Ubuntu 24.04).** They do not work as-is on Windows
> (use WSL2, or install by hand → [2-4](#2-4-this-assumes-linux-windows-needs-a-different-route)). Some commands
> differ on macOS too.

![the same reference image turned into 3 scenes](docs/collage_en.png)

*The same 1 reference image with only the surroundings changed, 3 ways (→ [2-9](#2-9-an-editing-demo-1-illustration-3-scenes)).*

## Table of contents

- [1. What runs, and what each piece is for](#1-what-runs-and-what-each-piece-is-for)
  - [1-1. What the weight files are, and where to get them](#1-1-what-the-weight-files-are-and-where-to-get-them)
  - [1-2. What each piece does](#1-2-what-each-piece-does)
  - [1-3. The exact names of the models used (down to the quantization)](#1-3-the-exact-names-of-the-models-used-down-to-the-quantization)
  - [1-4. Editing with reference images (up to 4 in this node)](#1-4-editing-with-reference-images-up-to-4-in-this-node)
- [2. Quick start (assuming you let an AI do it)](#2-quick-start-assuming-you-let-an-ai-do-it)
  - [2-1. The prompt to hand straight to an AI](#2-1-the-prompt-to-hand-straight-to-an-ai)
  - [2-2. (A) Install with the script (recommended)](#2-2-a-install-with-the-script-recommended)
  - [2-3. (B) Install by hand](#2-3-b-install-by-hand)
  - [2-4. This assumes Linux (Windows needs a different route)](#2-4-this-assumes-linux-windows-needs-a-different-route)
  - [2-5. Where it runs (the port)](#2-5-where-it-runs-the-port)
  - [2-6. You can also have an AI write the node](#2-6-you-can-also-have-an-ai-write-the-node)
  - [2-7. Verifying it works](#2-7-verifying-it-works)
  - [2-8. Environment variables (the only per-machine part)](#2-8-environment-variables-the-only-per-machine-part)
  - [2-9. An editing demo (1 illustration, 3 scenes)](#2-9-an-editing-demo-1-illustration-3-scenes)
- [3. Inside the node](#3-inside-the-node)
- [4. Measured numbers](#4-measured-numbers)
- [5. When you want better quality](#5-when-you-want-better-quality)
- [6. Troubleshooting](#6-troubleshooting)
- [7. Things that will bite you (I hit every one of them)](#7-things-that-will-bite-you-i-hit-every-one-of-them)
- [8. Files](#8-files)
- [9. License](#9-license)
- [10. Sources](#10-sources)


## 1. What runs, and what each piece is for

![the pipeline](docs/pipeline_en.png)

*The prompt and the reference image flow left to right: text encoder -> image generator -> VAE -> PNG.*

### 1-1. What the weight files are, and where to get them

> [!TIP]
> **You do not have to do this download by hand.** The `install.sh` in the
> [quick start](#2-quick-start-assuming-you-let-an-ai-do-it) below does it for you (that is the fast path).
> This section is for checking what gets downloaded, or for installing by hand.

You need three files, about 17GB in total. Download them with the `hf` command (installed by
`pip install -U huggingface_hub`).

```bash
hf download Comfy-Org/Qwen-Image-2.1 diffusion_models/qwen_image_2.1_int8_convrot.safetensors --local-dir ~/qwen-image-2.1-models
hf download Comfy-Org/Qwen-Image-2.1 text_encoders/qwen3vl_8b_int8_convrot.safetensors       --local-dir ~/qwen-image-2.1-models
hf download Comfy-Org/Qwen-Image-2.1 vae/qwen_image_2.1_vae_bf16.safetensors                 --local-dir ~/qwen-image-2.1-models
```

If you would rather grab them with a browser or `curl -L -O`, here are the three direct links.

| purpose | size | download link |
|---|---:|---|
| image generator | 7.26 GB | <https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors> |
| text encoder | 9.35 GB | <https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors> |
| VAE | 0.68 GB | <https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors> |

Put the files you downloaded in the following ComfyUI folders (do not rename them).

| file | where it goes |
|---|---|
| `qwen_image_2.1_int8_convrot.safetensors` | `ComfyUI/models/diffusion_models/` |
| `qwen3vl_8b_int8_convrot.safetensors` | `ComfyUI/models/text_encoders/` |
| `qwen_image_2.1_vae_bf16.safetensors` | `ComfyUI/models/vae/` |

(If you use `install.sh`, it does both of these for you automatically. → [2. Quick start](#2-quick-start-assuming-you-let-an-ai-do-it))

### 1-2. What each piece does

Only five things are involved. This repository provides **the bottom two**; the top ones are plain
ComfyUI and plain model files.

| piece | what it is | what it does | where it goes |
|---|---|---|---|
| text encoder | Qwen3-VL-8B (9.35 GB) | the one that "reads" the prompt. Reference images are also read here as visual information | `ComfyUI/models/text_encoders/` |
| image generator | DiT 7.1B (7.26 GB) | the one that actually "draws". It runs the loop that builds an image out of noise (12–20 steps). **This is the slowest part** | `ComfyUI/models/diffusion_models/` |
| VAE | decoder (0.68 GB) | converts the intermediate data (the latent representation) into a visible image (pixels) | `ComfyUI/models/vae/` |
| custom node | `custom_nodes/qwen21_fast/` (this repository) | loads the three above, runs the loop, returns the image. On the ComfyUI screen it is one box | `ComfyUI/custom_nodes/` |
| workflows | `workflows/*.json` (this repository) | a diagram of just "the node + image saving", ready to open and use | `ComfyUI/user/default/workflows/` |

**Why three files are needed**: Qwen-Image-2.1 is not distributed as "one file". You need the thing that
draws (the image generator), a separate model that reads the prompt (the text encoder, an 8B
vision-language model), and a VAE to turn it back into an image, each on its own. The VAE is **not
compatible** with the ones from the old Qwen-Image or Wan (mix them up and you get an error).

**Why I made a node**: you can also wire it up by hand in ComfyUI (`UNETLoader → CLIPLoader →
TextEncodeQwenImage21 → KSampler → VAEDecode`). But the settings you want to touch (size, step count,
how reference images are handled) are scattered across four boxes, so I bundled the settings I normally
use into one box. Inside it is just a combination of ComfyUI's standard nodes, so it keeps working even
when ComfyUI is updated.

### 1-3. The exact names of the models used (down to the quantization)

What I am using is **not the original that Qwen distributes, but the build that has been converted and
quantized for ComfyUI**.

| piece | exact name | quantization |
|---|---|---|
| image generator | **Qwen-Image-2.1** (distributed by: Comfy-Org) | **int8 tensorwise + convrot** (rotate the weights, then make them 8-bit. Keeps the quality loss down while being fast) |
| text encoder | **Qwen3-VL-8B-Instruct** | **int8 convrot** |
| VAE | **Qwen-Image-2.1 VAE** | no quantization (**bf16**) |

- The original upstream distribution (bf16, no quantization) is about 33GB and does not fit in 12GB of VRAM. Using the quantized version is what makes it fit in VRAM.
- Where the original and the ComfyUI format live: <https://huggingface.co/Qwen/Qwen-Image-2.1> /
  <https://huggingface.co/Comfy-Org/Qwen-Image-2.1>
- **Check the license yourself before you use this.** When I looked it was the research / non-commercial
  "Qwen Research License", but terms can change, so the original text is the only authority (especially if
  you are thinking about commercial use).
  - Original: <https://github.com/QwenLM/Qwen-Image-2.1/blob/main/LICENSE>

### 1-4. Editing with reference images (up to 4 in this node)

The node has inputs named `image_1` through `image_4`, and you can pass it **up to 4 reference images in this node**.
Connect a reference image and it stops being "generate from text" and becomes "edit the reference image"
(for example: "make the background of this photo night, keep the subject as it is").

> [!NOTE]
> **That 4 is the number of input slots in this node, not a limit of the model.** Qwen-Image-2.1 officially
> supports **up to 10 reference images** (ComfyUI's own `TextEncodeQwenImage21` node has more slots than this
> one). If you need five or more, add slots to this node or build the graph with the stock nodes.

**Each one you add makes it a little slower** (my measurements at 1024x1024, 12 steps):

| number of reference images | time |
|---|---:|
| 1 | 17.0 s |
| 2 | 25.9 s |
| 3 | 36.4 s |

The reason is that each reference image adds about 4096 tokens' worth of information to the text encoder
and the image generator. Budget roughly +9–10 seconds per image and you will be fine. When VRAM is tight,
setting `reference_fit` to `keep original size` uses the reference image without shrinking it, which saves
time only when the reference is larger than the output (at 1024x1024 the two modes measure the same,
15.9 s vs 16.7 s).

The bundled `workflows/qwen21_fast_edit.json` loads an image named `example.png`. Put your own image at
`ComfyUI/input/example.png`, or pick another file in the LoadImage node.

## 2. Quick start (assuming you let an AI do it)

> [!IMPORTANT]
> **These steps are written on the assumption that you have an AI (ChatGPT, Claude, a local agent, and so on) do them.**
> The reason is simple: that is how I put it together myself. You do not have to understand each command and type it in by hand.
> **You can do it manually too**, but it is easy to get stuck on the downloads and the path settings, so leaving it to an AI is more reliable and less trouble.
> (The steps themselves are written out both as [2-2. Install with the script](#2-2-a-install-with-the-script-recommended) and
> [2-3. Install by hand](#2-3-b-install-by-hand).)

### 2-1. The prompt to hand straight to an AI

Copy the box below and paste it into your AI. If it is an agent running in your environment (Ubuntu and so
on), it will just do it for you.

```
I want to add Qwen-Image-2.1 to ComfyUI using the steps in this repository.
https://github.com/kuraneko1/qwen21-fast-comfyui

What I want you to do:
1. git clone the repository above
2. Check what ./install.sh --dry-run would do, and if there is no problem, run ./install.sh
   (it downloads about 17GB of weights, so it takes a while)
3. Run ./check.sh for the syntax checks
4. Restart ComfyUI and run python3 test_qwen21.py to test generation
   (5/5 ok means it worked)

Assumptions: Linux (Ubuntu-family), ComfyUI is at ~/ComfyUI, and the hf command and python3 are available.
If your ComfyUI path is different, run install.sh with COMFY=/path/to/ComfyUI in front of it.
If there is anything you are unsure about, ask me before you run it.
```

### 2-2. (A) Install with the script (recommended)

```bash
git clone https://github.com/kuraneko1/qwen21-fast-comfyui.git
cd qwen21-fast-comfyui
./install.sh --dry-run    # just prints what it would do (changes nothing)
./install.sh              # actually do it
```

`install.sh` does these five things and nothing else.

1. Downloads the **three weight files** from the official repository into `$MODELS` (default `~/qwen-image-2.1-models`) (about 17GB, resumable)
2. **Hardlinks** them into the three ComfyUI folders (they just point at the same file, so the disk is not used twice)
3. Copies `custom_nodes/qwen21_fast` into `$COMFY/custom_nodes/` (that is, installing the node)
4. Copies `workflows/*.json` into `$COMFY/user/default/workflows/` (so they show up in the UI's workflow list)
5. Restarts ComfyUI (it finds and restarts the `systemd --user` service. If it does not find one it does
   nothing, so restart it the way you usually do. **Custom nodes are only read at startup**)

To change the paths, put them in front of the command.

```bash
COMFY=/opt/ComfyUI MODELS=/data/qwen21-models ./install.sh
COMFY_SERVICE=my-comfy.service ./install.sh     # when you want to name the service to restart
```

### 2-3. (B) Install by hand

<details>
<summary>the steps to install it by hand, without the script (click to open)</summary>

**B1. Download the weights** — run the three commands from [1-1](#1-1-what-the-weight-files-are-and-where-to-get-them).

**B2. Put them in place** (do not rename the files)

```bash
C=~/ComfyUI          # your ComfyUI folder
mv ~/qwen-image-2.1-models/diffusion_models/qwen_image_2.1_int8_convrot.safetensors $C/models/diffusion_models/
mv ~/qwen-image-2.1-models/text_encoders/qwen3vl_8b_int8_convrot.safetensors        $C/models/text_encoders/
mv ~/qwen-image-2.1-models/vae/qwen_image_2.1_vae_bf16.safetensors                  $C/models/vae/
```

**B3. Install the node** — clone this repository and copy the folder.

```bash
git clone https://github.com/kuraneko1/qwen21-fast-comfyui.git /tmp/qwen21-fast-comfyui
cp -r /tmp/qwen21-fast-comfyui/custom_nodes/qwen21_fast ~/ComfyUI/custom_nodes/
```

(Cloning this repository directly inside `custom_nodes/` is fine too. The only thing ComfyUI loads is `qwen21_fast` inside it)

**B4. Restart ComfyUI** — a running ComfyUI will not notice the new node. Be sure to restart it.

**B5. Run it** — start ComfyUI, open its URL in a browser (see [2-5](#2-5-where-it-runs-the-port)), and
either choose **Workflows → `qwen21_fast_t2i`** or build the following two nodes yourself.

```
Qwen 2.1 Fast Generate ──image──▶ SaveImage
```

To edit with a reference image, add a `LoadImage` and connect it to the node's `image_1`.

```
LoadImage ──IMAGE──▶ image_1
```

</details>

### 2-4. This assumes Linux (Windows needs a different route)

> [!WARNING]
> **This repository assumes Linux.** What I checked was Ubuntu 24.04. `install.sh` is a bash script, and
> the commands and the way paths are written all assume Linux.
>
> **On Windows you need one of the following two.**
>
> 1. **Use WSL2 (recommended)**: install Ubuntu inside Windows and run these steps as they are inside it.
>    ComfyUI would also go on the WSL side (it is a different thing from a ComfyUI installed on the Windows side).
> 2. **Do it by hand**: in the Windows version of ComfyUI, put the three weight files into
>    `ComfyUI\models\...` with Explorer and copy the node folder into `custom_nodes`
>    (do the contents of [2-3. Install by hand](#2-3-b-install-by-hand), reading the paths as Windows paths).
>    Note that Linux commands like `~/ComfyUI`, `mv` and `ln` will not work.
>
> macOS will not work with these commands as they are either (the `hf` and python parts are the same, but the paths and the way to restart are different).

### 2-5. Where it runs (the port)

ComfyUI listens on **`http://127.0.0.1:8188`** by default. **Just open that URL in your browser** and the
UI appears (`127.0.0.1` means "this very PC you are using", so you open it in a browser on the same PC).

```
ComfyUI UI      http://127.0.0.1:8188     ← open this in a browser
                ├── the node list: "Qwen 2.1 Fast Generate"
                ├── the workflows: Workflows ▸ qwen21_fast_t2i / qwen21_fast_edit
                └── the API the scripts use: http://127.0.0.1:8188/prompt, /history, /object_info
```

This is what it looks like when you open it.

![ComfyUI as it opens](docs/ui_workflow_en.png)

*Just this node and a Save Image node, wired together.*

Press Run and the result appears inside the Save Image node on the right (the shot below is
1024x1024 at 12 steps, right after the run finished). The **seed is randomized by default** (`control after generate` =
randomize, enabled by the node itself), so every run is a new image; switch it to `fixed` and keep
the seed if you want to reproduce one.

![right after a run](docs/ui_used_en.png)

The start command looks like this (the example from my environment).

```bash
python main.py --port 8188 --listen 127.0.0.1
```

**To change the port**, do one of these.

| method | how |
|---|---|
| Specify it in the start command | `python main.py --port 8288 --listen 127.0.0.1` (just change the number after `--port`) |
| If you run it with systemd | Rewrite the `--port` in `ExecStart=` in the unit file and `systemctl --user restart <service name>` (I keep mine in a unit file under `~/.config/systemd/user/`) |
| If you want to open it from another PC or a phone | Use `--listen 0.0.0.0` (be careful: everyone on the same LAN can see it) |
| On the verification script side | If you changed the port, pass it in like `COMFY_HOST=http://127.0.0.1:8288 python3 test_qwen21.py` |

### 2-6. You can also have an AI write the node

**This node is something I had an AI (an agent) write.** I did not write the code. If you ask in the same
way, you can have an AI write a node tailored to your environment. The three tips are these.

1. **Ask it "make me a ComfyUI custom node" in plain language, describing what you want**
   (for example: "I want a node that is already configured, where I put in a prompt and a reference image and it gives me back an image")
2. **Have it built by combining existing nodes** (that is what I did here too). If you make it reinvent
   ComfyUI's own model implementation, it breaks when ComfyUI itself is updated. It is safe to say "make it
   call ComfyUI's standard nodes (`UNETLoader` and so on) internally"
3. **Have it do a generation test on the real machine** (if you also have it write a verification script
   like `test_qwen21.py`, you can check later that you have not broken anything yourself)

`custom_nodes/qwen21_fast/nodes.py` in this repository is about 170 lines. When you want to change
something, the fastest way is to hand this file to an AI and ask it to "change this part like so".

### 2-7. Verifying it works

```bash
./check.sh                 # syntax checks on the files (nothing is executed)
python3 test_qwen21.py     # actually try generating (ComfyUI must be running)
```

`test_qwen21.py` **creates its own reference image** in the first test and then reuses it for the edit
test, so it works as-is even on a machine that has never generated a single image. On my environment the
output looks like this.

```
t2i_1mp            success  exec=  13.6s wall=  14.0s qwen21_test_t2i_1mp_00001_.png
t2i_16x9_2mp       success  exec=  30.7s wall=  31.0s qwen21_test_t2i_16x9_2mp_00001_.png
t2i_1mp_count3     success  exec=  24.2s wall=  25.0s qwen21_test_t2i_1mp_count3_00001_.png, ...
edit_match_output  success  exec=  15.9s wall=  16.1s qwen21_test_edit_match_output_00001_.png
edit_keep_size     success  exec=  16.7s wall=  17.0s qwen21_test_edit_keep_size_00001_.png

5/5 ok
```

To edit an image you already have, do this.

```bash
python3 test_qwen21_edit.py photo.png "make it snow, keep the subject unchanged"
```

### 2-8. Environment variables (the only per-machine part)

| variable | default | used by |
|---|---|---|
| `COMFY` | `$HOME/ComfyUI` | `install.sh` (where ComfyUI is) |
| `MODELS` | `$HOME/qwen-image-2.1-models` | `install.sh` (where the weights are downloaded) |
| `COMFY_SERVICE` | auto-detects a `systemd --user` service containing "comfy" | `install.sh` |
| `COMFY_DIR` | `$HOME/ComfyUI` | `test_qwen21.py` / `test_qwen21_edit.py` / `make_qwen21_workflows.py` / `check.sh` |
| `COMFY_HOST` | `http://127.0.0.1:8188` | `test_qwen21.py` / `test_qwen21_edit.py` / `make_qwen21_workflows.py` |
| `CHROME` | `/usr/bin/google-chrome` | `docs/capture_ui.py` / `docs/render_diagram.sh` (only when regenerating images) |

Paths, host names, device IDs and credentials are not written directly into the code: the ComfyUI location,
the ComfyUI URL, the service name and the browser path all come from the environment variables above.

### 2-9. An editing demo (1 illustration, 3 scenes)

Connect a reference image to `image_1` and you are in edit mode. This is the same 1 illustration with the
character's identity, outfit and art style kept while only the surroundings change (the collage at the top
is those 4 images).

| | scene | seed |
|---|---|---|
| original | a plain-background character illustration (1672x941) | — |
| 1 fire | clothes and surroundings engulfed in flames | 1030019892377945 |
| 2 underwater | water spiralling around her like a deep-sea empress | 274968494187645 |
| 3 rain | struck by torrential rain | 73346377262621 |

<details>
<summary>the 3 prompts in full</summary>

```text
Edit the reference image: keep the character clearly recognizable while placing her in a dramatic scene where her clothing and the space around her are engulfed in intense flames. Preserve her core identity, recognizable face, long blue gradient hair, blue eyes, maid outfit, whale-themed details, and overall anime style. Change her expression so that she looks slightly teary and on the verge of crying, with watery eyes and a distressed, trembling expression, while still remaining cute and expressive.

Add vivid fire surrounding her body, sleeves, skirt, and the air around her, with bright orange flames, glowing embers, smoke, sparks, heat distortion, and strong cinematic fire lighting. The flames should look powerful and visually striking, but do not show gore, injuries, or graphic burns. Keep the character as the clear focal point. Highly detailed, dramatic, emotional, and visually impactful.
```

```text
Edit the reference image: transform the character into a dramatic deep-sea empress scene while preserving her core identity, recognizable face, blue gradient long hair, bright blue eyes, playful smug expression, maid outfit, whale-themed details, and overall cute anime style. Surround her with a powerful vortex of ocean water, glowing bioluminescent particles, giant splashes, swirling currents, floating bubbles, and luminous deep-sea light rays. Add a majestic underwater atmosphere with translucent water ribbons spiraling around her body, as if she is commanding the sea. Enhance the whale/ocean motif with subtle spectral whale silhouettes and elegant aquatic energy. Make the scene highly dynamic, cinematic, magical, and visually striking, with strong motion, dramatic lighting, and rich blue tones. Keep the character as the clear focal point.
```

```text
Edit the reference image: place the character in an intense torrential rainstorm while preserving her core identity, recognizable face, long blue gradient hair, blue eyes, maid outfit, whale-themed details, and overall cute anime style. Change her expression slightly so that she looks teary and on the verge of crying, with watery eyes, a trembling mouth, and a sad, distressed but still cute expression.

Add extremely heavy pouring rain throughout the scene, with dense rain streaks, splashing water, mist, droplets, wet hair, soaked clothing, puddles, and strong storm atmosphere. Make it look like she is being struck by a violent downpour. Add visible rain in the foreground and background, dramatic water splashes, wet shine on the outfit, and cinematic storm lighting. Her hair and clothes should appear drenched and slightly affected by wind and rain, while keeping her original design clearly recognizable.

Make the final result highly detailed, emotional, cinematic, and visually striking. No gore, no injury, no burial, no extra characters. Keep the character as the clear focal point.
```
</details>

**Settings**: the reference is 1672x941 and the output is **1376x768** (same aspect ratio, 1 MP of area).
`aspect_ratio` 1:1 / `megapixels` 1 / `steps` 0 (auto = 12 steps) / `reference_fit` `match output` /
cfg 1.0 / euler simple. About **20 s per image** (RTX 4070 12GB, model resident; → [4. Measured numbers](#4-measured-numbers)).

**Prompt tips** (what these 3 images taught me)

1. **Name what must stay** - list `core identity, recognizable face, long blue gradient hair, blue eyes,
   maid outfit, whale-themed details, and overall anime style`. This is what decides whether it still looks
   like the same character
2. **An expression change is something you ask for** - fire and rain say `teary, on the verge of crying`,
   underwater says `playful smug expression`. You can steer the face deliberately while keeping the identity
3. **Write the environment in scene words** - `intense flames` / `vortex of ocean water` / `torrential
   rainstorm`, plus light (`cinematic lighting`) and motion (`swirling currents`)
4. **Say what must not happen** - `no gore, no injury, no burial, no extra characters`. Worth including so a
   viewer cannot misread the image
5. **To hold the framing, state the preservation explicitly** - environment words also move the composition
   (measured: a version that only said "a field of flames around him" pushed the top of the head from 2% to
   10% down the frame and widened the crop to the waist). For an exactly fixed frame, mask (inpaint) the
   background instead; this node has no mask input

The CLI equivalent:

```bash
python3 test_qwen21_edit.py ref.png "<prompt>" 1 --seed 1030019892377945
```

## 3. Inside the node

| in / out | name | meaning |
|---|---|---|
| input | `prompt` | the prompt |
| input | `aspect_ratio` × `megapixels` | aspect ratio (1:1 / 4:3 / 3:4 / 3:2 / 2:3 / 16:9 / 9:16) and size (0.5 / 1 / 2 / 4 MP). **1MP = 1024x1024, 4MP = 2048x2048**. With a reference connected the output takes the reference's aspect ratio, so `aspect_ratio` is ignored; `megapixels` then fixes the **area** (a 16:9 reference at `megapixels=2` comes out 1920x1088 - not 1440 wide, but about the same area as 1440x1440) |
| input | `steps` | 0 = automatic (**12 steps when the long side is 1024 px or less**, 20 above that. 1:1 at 1MP takes 12; 4:3 and 16:9 at 1MP have a 1184 / 1376 px long side, so they take 20) |
| input | `seed` | the random seed. **Randomized by default**: the node enables the frontend's `control after generate` widget, so both a freshly added node and the shipped workflows come up as `randomize` and every run gives a new image. Switch it to `fixed` and note the seed to reproduce one |
| input | `count` | how many to make at once (seed, seed+1, …). The results come back together |
| input | `reference_fit` | how reference images are handled (`match output` = match the output size / `keep original size` = keep the reference's original size. The latter is only lighter when the reference is bigger than the output; with a 1024x1024 reference the two measure the same, 15.9 s vs 16.7 s) |
| input | `unet_name` / `clip_name` / `vae_name` | which of the three weight files (the default is the three above) |
| input (optional) | `image_1` … `image_4` | reference images. Connect even one and it goes into edit mode (the 4 is this node's slot count, not the model's limit) |
| input (optional) | `model` / `clip` / `vae` | if you already have loaders in your graph, you can reuse them |
| output | `image` | the generated image (IMAGE) |
| output | `info` | one line with the settings and the elapsed time (real example: `t2i refs=0 1024x1024 12 steps cfg=1.0 euler/simple seeds=0..0 13.2s (13.2s each)`). In edit mode it prints the **real output size**, which follows the reference image's aspect ratio |

**I deliberately do not expose cfg (how closely it follows the prompt) or the sampler.** For this model
cfg 1.0 and euler/simple are the official settings, and anything else only makes it slower with no upside
(→ [7. Things that will bite you](#7-things-that-will-bite-you-i-hit-every-one-of-them)). There is no
negative prompt field either: at cfg 1.0 ComfyUI skips the unconditional pass entirely
(`math.isclose(cond_scale, 1.0)` in `comfy/samplers.py`), so anything typed there would do nothing.

## 4. Measured numbers

These are the numbers from my environment (RTX 4070 12GB, the official quantized weights). They are
compared with the same prompt and the same seed.

| case | time |
|---|---:|
| 1024x1024, 12 steps, cfg 1.0 | **9.6 s** (13–14 s right after a ComfyUI restart) |
| 1024x1024, 25 steps (equivalent to the official workflow) | 14.0 s |
| 1920x1088 (16:9, 2MP), 20 steps | 30.7 s |
| **2048x2048 (4MP), 20 steps** | **90.5 s** |
| 1024x1024, 3 images in one go (`count=3`) | 24.2 s (about 8 s per image) |
| edit with 1 reference image (1024x1024, 12 steps) | 17.0 s |
| edit with 3 reference images | 36.4 s |

- Per step: about 0.34 s at 1MP, about 4.3 s at 4MP
- The fixed cost (text encoding, VAE decoding, swapping models) is about 5 s
- The 17GB of weights do not fit entirely in 12GB of VRAM, so ComfyUI swaps in the parts it needs
  automatically. That is why only right after a restart it takes a few extra seconds, and why `count=3`
  is cheaper per image than running three separate times
- The raw log I measured: `MEASUREMENTS.md`

## 5. When you want better quality

- **Increase the step count** (`steps` from 0 → 20–30). The time grows about proportionally with the step count (about 0.34 s per step at 1MP, plus roughly 5 s of fixed cost; 12 → 25 steps is x1.5).
  12 steps is plenty clean already, but the more you add the more stable the fine details and text become
- **Increase the resolution** (`megapixels` from 1 → 4). The composition is less likely to fall apart and
  there is more detail, but the time becomes about 9 times longer (9.6 → 90.5 s at the default steps)
- **Change the seed and pick**. Setting `count` to 3–4 lets you get several at once, which makes choosing
  easier (and each one is a little cheaper)
- **Raise the resolution of the reference image, or set `reference_fit` to `match output`**. The fidelity of the edit goes up
- **Write the prompt carefully**. Splitting what you want changed from what you want kept, like "keep ~ as
  it is" or "only the background ~", works well
- **Do not touch cfg** (leave it at 1.0). Raising it only doubles the time, and the image becomes
  over-contrasted
- The official release also distributes a prompt-rewriting model (`Qwen-Image-2.1-PE-T2I`). I have not
  verified it, but it is said to be able to expand a short prompt into a detailed one and raise the quality

A rough guide to what changes what:

| what you change | time | VRAM | quality |
|---|---|---|---|
| steps 12 → 25 | ×1.5 (9.6 → 14.0 s; the fixed cost dominates, so it does not double) | about the same | a little better |
| resolution 1MP → 4MP | ×9.4 (9.6 → 90.5 s at the default steps; ×5.9 = 56.2 s if the step count is held at 12) | higher | better (composition is stable) |
| +1 reference image | +9–10 s | higher | the fidelity of the edit goes up |
| cfg 1.0 → 6.0 | ×2 | higher | worse (the image becomes too heavy) |

## 6. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| An error saying `mat1 and mat2 shapes cannot be multiplied (… x4096 and 1024x2048)` | CLIPLoader is reading another workflow's encoder (the 0.6B or 4B one) | Load `qwen3vl_8b_int8_convrot.safetensors` with type `qwen_image` |
| "Qwen 2.1 Fast Generate" does not appear in the node list | Custom nodes are only read at startup / the folder is in the wrong place | Restart ComfyUI. Check that `custom_nodes/qwen21_fast/nodes.py` exists |
| `size mismatch for encoder.conv_in.weight` in the VAELoader | The VAE inside unsloth's FP8 repository uses the **diffusers layout** (2D convolutions, `encoder.conv_in` / `decoder.conv_out`), while ComfyUI's Qwen-Image-2.1 expects the **modelspec layout** (3D convolutions, `encoder.conv1` / `decoder.head.2`) | Use Comfy-Org's `qwen_image_2.1_vae_bf16.safetensors` (675,509,688 bytes) |
| Roughly twice as slow as the measurements above | cfg is above 1.0 / you are using GGUF weights | Set cfg to 1.0 and use the int8_convrot weights |
| Running the same content finished in 0.1 seconds | ComfyUI is caching the identical graph (normal behaviour) | Change the seed when you measure the time |
| `aimdo memory compile error` | `QwenImage21Cache` (the prefix KV cache) int8/int4 does not work in this environment | Leave it at `default` (the node does not expose it) |
| It fails or is far too slow with 3–4 reference images | Each reference consumes about 4096 tokens | Set `reference_fit` to `keep original size` / use fewer images |
| "unknown model architecture" in a GGUF loader | GGUF re-packs of this model are missing metadata | Do not use GGUF here; use the int8_convrot safetensors |

## 7. Things that will bite you (I hit every one of them)

1. **Raising cfg above 1.0 doubles the computation.** The official setting is 1.0. Most of the sample code
   out there uses something like 6.0, and this was the biggest trap of all.
2. **The GGUF re-packs are slow in ComfyUI.** unsloth's **DiT GGUF carries no architecture information**
   (`kv_count=0`), so ComfyUI-GGUF falls back to its guessing path and reports `Unknown model architecture!`
   (adding a `qwen_image` signature to `tools/convert.py` makes it load). Once it loads, six runs per arm with
   the same prompt and seed give **11.8 s (int8) vs 24.3 s (GGUF) at 1024x1024 / 12 steps - a median ratio of
   about 2.0x**, and the sampler's own progress bar shows **0.52 vs 1.38 s/step (about 2.6x)**: ComfyUI cannot
   use its int8 kernels and dequantizes every step, while the fixed cost both arms pay (~6 s) dilutes the ratio
   at 12 steps. Note that the **text encoder GGUF does carry correct metadata**
   (`general.architecture=qwen3vl`, 45 keys) - it is not the cause; the DiT is.
   For reference, the **vendor's own app (Unsloth Desktop) was measured with the same GGUF**: on 12 GB it
   cannot select the int8 path (it wants everything resident - 34.9 GB - and cannot offload it), so it runs
   GGUF only, at **29.5 s** (section 3-2 of [MEASUREMENTS.md](MEASUREMENTS.md)).
3. **There are two kinds of VAE, and they differ in layout.** Both are **4-channel (alpha-capable)**; the
   difference is the shape of the weights. Comfy-Org's uses the **modelspec layout** (3D convolutions,
   `encoder.conv1` / `decoder.head.2`, kernel `[1,3,3]`), the one inside unsloth's FP8 repository uses the
   **diffusers layout** (2D convolutions, `encoder.conv_in` / `decoder.conv_out`, kernel `[3,3]`). ComfyUI
   expects the former, so picking the latter gives you a mountain of `size mismatch` (the 3-channel Qwen VAE
   belongs to **Qwen-Image 1.0** and is not interchangeable).
4. **ComfyUI caches the same graph.** With the same prompt and seed it returns in 0.1 seconds and the GPU
   does nothing.
5. **`QwenImage21Cache` (quantizing the prefix KV cache) does not work in this environment.** Both int8 and
   int4 die with `aimdo memory compile error`, so I did not put it in the node.
6. **Always use the Qwen-Image-2.1 encoder.** If you use a Qwen3-VL of the wrong size, you do not get an
   easy-to-understand error but a cross-attention shape error.

## 8. Files

```
install.sh                       download the weights, place them, install the node, restart
check.sh                         syntax checks (bash / python / workflow JSON)
MEASUREMENTS.md                  the raw measurement log
custom_nodes/qwen21_fast/        the node itself (a combination of ComfyUI's standard nodes)
workflows/qwen21_fast_t2i.json   the workflow that generates from a prompt
workflows/qwen21_fast_edit.json  the edit workflow with a reference image connected
make_qwen21_workflows.py         rebuild the workflows from the node's specification
test_qwen21.py                   verification (sizes, count, edit)
test_qwen21_edit.py              a one-off edit from the command line
docs/collage_en.png              the collage at the top (the original + 3 scenes)
docs/pipeline_en.png             the diagram in section 1 (an HTML render)
docs/ui_workflow_en.png          the ComfyUI screen as it opens
docs/ui_used_en.png              the same screen after a run (the node actually in use)
docs/diagram.html / .en.html     the diagram source (HTML, Japanese and English)
docs/render_diagram.sh           renders the diagram to PNG (headless Chrome, 2x scale)
docs/diagram-spec.md             the content spec for the diagram (no design brief)
docs/capture_ui.py               the script that takes the screenshot
```

Both images are generated: `./docs/render_diagram.sh` redraws the diagram from the HTML, and
`python3 docs/capture_ui.py docs --lang en --run` screenshots a running ComfyUI with the workflow loaded
(`ui_empty_en.png` as it opens, `ui_workflow_en.png` once the workflow is loaded, and with `--run` it
generates one image and also writes `ui_used_en.png`; `--lang ja` for the Japanese UI).

## 9. License

This node and these scripts are MIT. **The weights (model files) are not included in this repository** —
`install.sh` downloads them from the official repositories below, and the weights follow their own
respective licenses.

**Check the weights' license yourself.** When I looked it was a research / non-commercial one, but terms
change, so the original text is the only authority:
<https://github.com/QwenLM/Qwen-Image-2.1/blob/main/LICENSE>

## 10. Sources

| file | size | direct link |
|---|---:|---|
| image generator (int8 convrot) | 7.26 GB | <https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors> |
| text encoder (int8 convrot) | 9.35 GB | <https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors> |
| VAE (bf16) | 0.68 GB | <https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors> |

The same repository also has the unquantized `qwen_image_2.1_bf16.safetensors` (14.2 GB),
`qwen3vl_8b_bf16.safetensors` (17.5 GB), `qwen3vl_8b_w4a8.safetensors` (6.3 GB), and the prompt-rewriting
`qwen3.5_9b_qwen_image_2.1_pe_t2i` / `..._pe_i2i` (9.5 GB each).

- Model card (upstream): <https://huggingface.co/Qwen/Qwen-Image-2.1>
- Code and license: <https://github.com/QwenLM/Qwen-Image-2.1>
- ComfyUI-format distribution: <https://huggingface.co/Comfy-Org/Qwen-Image-2.1>
- GGUF re-packs (not used in these steps): <https://huggingface.co/unsloth/Qwen-Image-2.1-GGUF> ·
  <https://huggingface.co/leejet/Qwen-Image-2.1-GGUF>
- Official ComfyUI workflow: <https://github.com/Comfy-Org/workflow_templates>
