#!/usr/bin/env python3
"""Write the Qwen21FastGenerate demo workflows into ComfyUI's workflow list.

Widget order is derived from the live /object_info, and every node also gets
widgets_values_named, so the workflow cannot drift out of sync with the node's inputs.
"""
import json
import os
import urllib.request
from pathlib import Path

WF_DIR = Path(os.environ.get("COMFY_DIR", Path.home() / "ComfyUI")) / "user/default/workflows"
HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")

DEFAULTS = {
    "prompt": "a ceramic teapot and two cups on a linen tablecloth, soft morning light, photograph",
    "width": 1024, "height": 1024, "steps": 0, "seed": 123456, "cfg": 1.0,
    "sampler_name": "euler", "scheduler": "simple",
    "unet_name": "qwen_image_2.1_int8_convrot.safetensors",
    "clip_name": "qwen3vl_8b_int8_convrot.safetensors",
    "vae_name": "qwen_image_2.1_vae_bf16.safetensors",
    "resolution": 1024, "negative_prompt": "",
}


def widget_values(node_id: str) -> tuple[list, dict]:
    """Widget order and defaults are read from the live node, so they cannot drift."""
    info = json.load(urllib.request.urlopen(f"{HOST}/object_info/{node_id}", timeout=20))[node_id]
    values, named = [], {}
    for section in ("required", "optional"):
        for name, spec in info["input"].get(section, {}).items():
            kind = spec[0]
            if not isinstance(kind, list) and kind not in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                continue  # link-only socket (IMAGE / MODEL / CLIP / VAE)
            default = spec[1].get("default", kind[0] if isinstance(kind, list) else None)
            values.append(default)
            named[name] = default
            if name == "seed":
                # Frontend-only widget. "randomize" so that pressing Run again gives a new
                # image instead of the cached same one; switch it to "fixed" to reproduce.
                values.append("randomize")
                named["control_after_generate"] = "randomize"   # the UI saves it under this name
    return values, named


def main() -> None:
    values, named = widget_values("Qwen21FastGenerate")
    WF_DIR.mkdir(parents=True, exist_ok=True)
    for edit in (False, True):
        nodes = []
        links = []
        if edit:
            nodes.append({
                "id": 1, "type": "LoadImage", "pos": [80, 120], "size": [320, 400],
                "flags": {}, "order": 0, "mode": 0, "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [1], "slot_index": 0},
                            {"name": "MASK", "type": "MASK", "links": None, "slot_index": 1}],
                "properties": {"Node name for S&R": "LoadImage"},
                "widgets_values": ["example.png", "image"]})
            links.append([1, 1, 0, 2, 0, "IMAGE"])  # target slot 0 = image_1
        nodes.append({
            "id": 2, "type": "Qwen21FastGenerate", "pos": [450, 120], "size": [430, 700],
            "flags": {}, "order": 1, "mode": 0,
            "inputs": ([{"name": "image_1", "type": "IMAGE", "link": 1}] if edit else []) +
                      [{"name": "model", "type": "MODEL", "link": None},
                       {"name": "clip", "type": "CLIP", "link": None},
                       {"name": "vae", "type": "VAE", "link": None}],
            "outputs": [{"name": "image", "type": "IMAGE", "links": [2], "slot_index": 0},
                        {"name": "info", "type": "STRING", "links": None, "slot_index": 1}],
            "properties": {"Node name for S&R": "Qwen21FastGenerate"},
            "widgets_values": values, "widgets_values_named": named})
        nodes.append({
            "id": 3, "type": "SaveImage", "pos": [920, 120], "size": [330, 270],
            "flags": {}, "order": 2, "mode": 0,
            "inputs": [{"name": "images", "type": "IMAGE", "link": 2}], "outputs": [],
            "properties": {"Node name for S&R": "SaveImage"},
            "widgets_values": ["qwen21_fast" + ("_edit" if edit else "")]})
        links.append([2, 2, 0, 3, 0, "IMAGE"])
        name = "qwen21_fast_edit" if edit else "qwen21_fast_t2i"
        path = WF_DIR / f"{name}.json"
        json.dump({"last_node_id": 3, "last_link_id": 2, "nodes": nodes, "links": links,
                   "groups": [], "config": {}, "extra": {}, "version": 0.4},
                  open(path, "w"), ensure_ascii=False, indent=1)
        print("wrote", path, "| widgets:", values)


if __name__ == "__main__":
    main()
