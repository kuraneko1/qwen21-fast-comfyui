#!/usr/bin/env python3
"""Edit an existing image with the installed Qwen21FastGenerate node (reference image input).

    python3 test_qwen21_edit.py <ref.png> "<edit prompt>" [megapixels] [keep] [--seed N]

The seed is random unless you pass --seed, so repeated runs give different images; the seed that
was used is printed, so a result you like can be reproduced with --seed.

The reference is copied into ComfyUI's input dir (LoadImage reads from there), then a graph
`LoadImage -> Qwen21FastGenerate(image_1=...) -> SaveImage` is submitted and timed.
In edit mode the output shape follows the FIRST reference and `megapixels` sets the area (the
aspect_ratio widget only feeds the automatic step count). Pass `keep` (reference_fit = "keep
original size") to leave the reference at its own size instead of matching the output.

Exits non-zero if the edit fails, so a caller can tell a failed run from a good one.
"""
import json
import os
import random
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")
INPUT_DIR = Path(os.environ.get("COMFY_DIR", Path.home() / "ComfyUI")) / "input"


def post(path, payload):
    r = urllib.request.Request(HOST + path, data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))


def get(path):
    return json.load(urllib.request.urlopen(HOST + path, timeout=60))


def edit(ref: str, prompt: str, megapixels: str = "1", fit: str = "match output",
         steps: int = 0, seed: int | None = None, prefix: str = "qwen21_edit"):
    if seed is None:
        seed = random.randrange(2 ** 32)
    src = Path(ref)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"qwen21ref_{src.stem}{src.suffix}"
    shutil.copyfile(src, INPUT_DIR / name)
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": name, "upload": "image"}},
        "2": {"class_type": "Qwen21FastGenerate", "inputs": {
            # The reference decides the output shape, megapixels sets the area, and aspect_ratio
            # only feeds the automatic step count - so 1:1 is the right widget value here.
            "prompt": prompt, "aspect_ratio": "1:1", "megapixels": megapixels,
            "steps": steps, "seed": seed, "count": 1, "reference_fit": fit,
            "unet_name": "qwen_image_2.1_int8_convrot.safetensors",
            "clip_name": "qwen3vl_8b_int8_convrot.safetensors",
            "vae_name": "qwen_image_2.1_vae_bf16.safetensors",
            "image_1": ["1", 0]}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": prefix}},
    }
    t0 = time.time()
    pid = post("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})["prompt_id"]
    while True:
        time.sleep(1)
        h = get("/history/%s" % pid)
        if pid in h:
            entry = h[pid]
            st = entry.get("status", {})
            marks = {m[0]: m[1].get("timestamp") for m in st.get("messages", []) if len(m) > 1}
            ex = marks.get("execution_success", 0) - marks.get("execution_start", 0)
            err = [m[1].get("exception_message") for m in st.get("messages", [])
                   if m[0] == "execution_error"]
            imgs = [i["filename"] for n in entry.get("outputs", {}).values()
                    for i in n.get("images", [])]
            print("%-8s ref=%s mp=%s fit=%s steps=%s seed=%d exec=%.1fs wall=%.1fs %s %s"
                  % (st.get("status_str"), src.name, megapixels, fit, steps or "auto", seed,
                     ex / 1000, time.time() - t0, ",".join(imgs), err[:1]))
            return st.get("status_str") == "success"
        if time.time() - t0 > 900:
            print("%-8s TIMEOUT after %.0fs - is ComfyUI running at %s?"
                  % ("timeout", time.time() - t0, HOST))
            return False


if __name__ == "__main__":
    # Pull --seed out first, wherever it sits, so "keep" keeps its position.
    args, seed, argv, i = [], None, sys.argv[1:], 0
    while i < len(argv):
        if argv[i] == "--seed":
            try:
                seed = int(argv[i + 1])
            except (IndexError, ValueError):
                sys.exit("--seed needs an integer")
            i += 2
            continue
        args.append(argv[i])
        i += 1
    if len(args) < 2:
        sys.exit(__doc__.strip())
    if len(args) > 4:
        sys.exit("too many arguments: %s" % " ".join(args[4:]))
    ref, prompt, rest = args[0], args[1], args[2:]
    mp, fit = "1", "match output"
    # "keep" is accepted before or after megapixels, so passing --seed between them cannot
    # silently turn "keep" into a megapixels value.
    if rest and rest[0] == "keep":
        fit, rest = "keep original size", rest[1:]
    elif rest:
        mp, rest = rest[0], rest[1:]
        if rest and rest[0] == "keep":
            fit, rest = "keep original size", rest[1:]
    if rest:
        sys.exit("unexpected argument(s): %s" % " ".join(rest))
    if mp not in ("0.5", "1", "2", "4"):
        sys.exit("megapixels must be 0.5, 1, 2 or 4 (got %r)" % mp)
    try:
        ok = edit(ref, prompt, megapixels=mp, fit=fit, seed=seed)
    except urllib.error.URLError as exc:
        sys.exit("cannot reach ComfyUI at %s (%s) - start it and retry" % (HOST, exc.reason))
    raise SystemExit(0 if ok else 1)
