#!/usr/bin/env python3
"""Smoke-test the Qwen21FastGenerate node through the ComfyUI HTTP API.

    python3 test_qwen21.py                # full matrix (the first case also makes the
                                          # reference image the edit cases reuse)
    python3 test_qwen21.py t2i_1mp        # a single case
    COMFY_DIR=~/ComfyUI python3 test_qwen21.py

Covers the node's surface: aspect ratio x megapixels, the automatic step counts, a
multi-image batch, and editing with and without reference resizing. Exits non-zero if any
case fails OR is skipped (a skipped case generated nothing), so it also works as a post-install
check. Run it without arguments so the first case produces the reference the edit cases reuse.
"""
import json
import os
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")
COMFY = Path(os.environ.get("COMFY_DIR", Path.home() / "ComfyUI"))
INPUT_DIR = COMFY / "input"

MODELS = dict(unet_name="qwen_image_2.1_int8_convrot.safetensors",
              clip_name="qwen3vl_8b_int8_convrot.safetensors",
              vae_name="qwen_image_2.1_vae_bf16.safetensors")

CASES = {
    "t2i_1mp": dict(prompt="a single glass teapot on a wooden table, soft window light, product photograph",
                    aspect="1:1", mp="1", seed=711),
    "t2i_16x9_2mp": dict(prompt="a coastal town at dusk seen from a hill, warm window lights, photograph",
                         aspect="16:9", mp="2", seed=712),
    "t2i_1mp_count3": dict(prompt="a cozy wooden cabin in a snowy pine forest at dusk",
                           aspect="1:1", mp="1", count=3, seed=713),
    "edit_match_output": dict(prompt="replace the tablecloth with a dark green linen, "
                                     "keep the teapot and cups exactly as they are",
                              aspect="1:1", mp="1", seed=714, ref=True),
    "edit_keep_size": dict(prompt="add a small vase of wildflowers behind the teapot, "
                                  "keep everything else unchanged",
                           aspect="1:1", mp="1", seed=715, ref=True,
                           reference_fit="keep original size"),
}


def post(path, payload):
    req = urllib.request.Request(HOST + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def get(path):
    return json.load(urllib.request.urlopen(HOST + path, timeout=60))


def run_case(name, case, ref_file=None):
    inputs = {"prompt": case["prompt"], "aspect_ratio": case.get("aspect", "1:1"),
              "megapixels": case.get("mp", "1"), "steps": 0, "seed": case.get("seed", 0),
              "count": case.get("count", 1),
              "reference_fit": case.get("reference_fit", "match output"), **MODELS}
    graph = {"qwen": {"class_type": "Qwen21FastGenerate", "inputs": inputs},
             "save": {"class_type": "SaveImage",
                      "inputs": {"images": ["qwen", 0],
                                 "filename_prefix": "qwen21_test_" + name}}}
    if case.get("ref"):
        if not ref_file:
            print("%-18s SKIP (no reference image available)" % name)
            return {"name": name, "status": "skipped"}
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ref_file, INPUT_DIR / "qwen21_ref.png")
        graph["load"] = {"class_type": "LoadImage",
                         "inputs": {"image": "qwen21_ref.png", "upload": "image"}}
        inputs["image_1"] = ["load", 0]

    started = time.time()
    pid = post("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})["prompt_id"]
    while True:
        time.sleep(1)
        history = get("/history/%s" % pid)
        if pid not in history:
            if time.time() - started > 900:
                print("%-18s TIMEOUT" % name)
                return {"name": name, "status": "timeout"}
            continue
        entry = history[pid]
        status = entry.get("status", {})
        marks = {m[0]: m[1].get("timestamp") for m in status.get("messages", []) if len(m) > 1}
        exec_s = (marks.get("execution_success", 0) - marks.get("execution_start", 0)) / 1000
        errors = [m[1].get("exception_message") for m in status.get("messages", [])
                  if m[0] == "execution_error"]
        images = [COMFY / "output" / i.get("subfolder", "") / i["filename"]
                  for node in entry.get("outputs", {}).values() for i in node.get("images", [])]
        ok = status.get("status_str") == "success"
        print("%-18s %-8s exec=%6.1fs wall=%6.1fs %s%s"
              % (name, status.get("status_str"), exec_s, time.time() - started,
                 ", ".join(p.name for p in images), (" !! " + str(errors[:1])) if errors else ""))
        return {"name": name, "status": "ok" if ok else "failed", "exec_s": exec_s,
                "images": images}


def main():
    wanted = sys.argv[1:] or list(CASES)
    unknown = [n for n in wanted if n not in CASES]
    if unknown:
        sys.exit("unknown case %s - choose from %s" % (", ".join(unknown), ", ".join(CASES)))
    results, ref = [], None
    for name in wanted:
        result = run_case(name, CASES[name], ref_file=ref)
        results.append(result)
        if name == "t2i_1mp" and result.get("images"):
            ref = str(result["images"][0])  # the edit cases reuse this render
    # Only "ok" counts as ok: a skipped case produced no image, so reporting it as a pass would
    # tell an agent (or a CI job) that everything worked when nothing was generated.
    ok = [r["name"] for r in results if r["status"] == "ok"]
    failed = [r["name"] for r in results if r["status"] not in ("ok", "skipped")]
    skipped = [r["name"] for r in results if r["status"] == "skipped"]
    print("\n%d/%d ok%s%s" % (len(ok), len(results),
                              ("  FAILED: " + ", ".join(failed)) if failed else "",
                              ("  SKIPPED: " + ", ".join(skipped)) if skipped else ""))
    if skipped:
        print("skipped cases generated nothing - run it without arguments so the first case "
              "makes the reference image they reuse")
    return 1 if failed or skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
