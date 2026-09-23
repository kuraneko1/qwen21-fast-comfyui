"""One-node Qwen-Image-2.1 generation and editing for ComfyUI.

Composes the existing core nodes (UNETLoader / CLIPLoader / VAELoader /
TextEncodeQwenImage21 / EmptyLatentImage / KSampler / VAEDecode) instead of reimplementing
the model, so the graph stays correct when ComfyUI's model code changes.

Opinionated defaults, all measured on a 12 GB Ada card with the official int8_convrot
weights (see MEASUREMENTS.md in this repository):

    1024x1024 (1 MP), 12 steps        ->  ~10 s
    2048x2048 (4 MP), 20 steps        ->  ~90 s
    edit, one reference, 1024x1024    ->  ~17 s

cfg is fixed at 1.0 and the sampler at euler/simple because that is this model's official
setting: any cfg above 1.0 makes ComfyUI evaluate a second (unconditional) pass per step, and
at cfg 1.0 the negative conditioning is skipped entirely - which is why there is no negative
prompt input here. Loaded models are cached, since reloading the 7 GB DiT costs several
seconds per execution.
"""
import math
import time

import torch

import folder_paths
import nodes as comfy_nodes

# NOTE: the quantized prefix-KV cache (comfy_extras QwenImage21Cache) fails on this box
# with "aimdo memory compile error" for both int8 and int4, so it is not offered here.
from comfy_extras.nodes_qwen import TextEncodeQwenImage21

DEFAULT_UNET = "qwen_image_2.1_int8_convrot.safetensors"
DEFAULT_CLIP = "qwen3vl_8b_int8_convrot.safetensors"
DEFAULT_VAE = "qwen_image_2.1_vae_bf16.safetensors"

ASPECT_RATIOS = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3,
                 "16:9": 16 / 9, "9:16": 9 / 16}
MEGAPIXELS = ["0.5", "1", "2", "4"]
REF_FIT = ["match output", "keep original size"]
REF_TOOLTIP = ("Connect one or more references to switch to editing. Only the sockets you fill "
               "are used, renumbered 1, 2, 3, 4 in order (empty ones are skipped), so the prompt "
               "sees them in that order.")
SAMPLER, SCHEDULER, CFG = "euler", "simple", 1.0

_cache = {}


def _cached(kind, name, loader):
    # One component at a time: the replaced component is dropped, and the local reference to it
    # is deleted, BEFORE the new one is read - otherwise this function itself keeps the old
    # weights alive and a 12 GB card briefly holds two copies.
    hit = _cache.get(kind)
    if hit and hit[0] == name:
        return hit[1]
    _cache.pop(kind, None)
    del hit
    _cache[kind] = (name, loader(name))
    return _cache[kind][1]


def _load_unet(name):
    return _cached("model", name,
                   lambda n: comfy_nodes.UNETLoader().load_unet(n, "default")[0])


def _load_clip(name):
    return _cached("clip", name,
                   lambda n: comfy_nodes.CLIPLoader().load_clip(n, type="qwen_image")[0])


def _load_vae(name):
    return _cached("vae", name, lambda n: comfy_nodes.VAELoader().load_vae(n)[0])


def _size(aspect_ratio, megapixels):
    # 1 MP is the model's 1024x1024 and 4 MP its native 2048x2048, so a "megapixel" here is
    # 1024*1024 pixels rather than 1e6 (which would give 992x992).
    ratio = ASPECT_RATIOS[aspect_ratio]
    area = float(megapixels) * 1024 * 1024
    return (max(256, round(math.sqrt(area * ratio) / 32) * 32),
            max(256, round(math.sqrt(area / ratio) / 32) * 32))


class Qwen21FastGenerate:
    """Prompt (and optionally up to four reference images) in, image out."""

    DESCRIPTION = ("Qwen-Image-2.1 in one node: text to image, or image editing when a "
                   "reference is connected to image_1. cfg and sampler are fixed at the "
                   "model's official setting (1.0, euler/simple); size is aspect ratio x "
                   "megapixels; steps = 0 picks 12 when the long side is 1024 px or less "
                   "and 20 above that.")
    SEARCH_ALIASES = ["qwen", "qwen image", "qwen 2.1", "qwen21", "text to image",
                      "image edit", "fast"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True,
                                      "default": "a ceramic teapot and two cups on a linen "
                                                 "tablecloth, soft morning light, photograph"}),
                "aspect_ratio": (list(ASPECT_RATIOS), {"default": "1:1"}),
                "megapixels": (MEGAPIXELS, {"default": "1",
                                            "tooltip": "1 is about 1024x1024, 4 is 2048x2048 "
                                                       "(the model's native 2K). With a "
                                                       "reference connected the output keeps "
                                                       "the reference's aspect ratio and this "
                                                       "setting fixes the AREA instead of the "
                                                       "long side: a 16:9 reference at 2 MP "
                                                       "comes out 1920x1088, not 1440 wide."}),
                "steps": ("INT", {"default": 0, "min": 0, "max": 100,
                                  "tooltip": "0 = automatic: 12 steps when the long side is "
                                             "1024 px or less (1:1 at 1 MP and smaller), 20 "
                                             "above that (2 MP+, and 4:3 or 16:9 at 1 MP)."}),
                # control_after_generate=True is how a core node enables the seed's
                # "control after generate" widget; the frontend defaults that to randomize,
                # so a fresh node gives a new image each run and the shipped workflows store
                # randomize explicitly. Switch it to fixed to reproduce an image.
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff,
                                 "control_after_generate": True,
                                 "tooltip": "Randomized after every run by default (control "
                                            "after generate); set that to fixed to reproduce "
                                            "one. With count > 1 the batch uses seed, "
                                            "seed+1, ..."}),
                "count": ("INT", {"default": 1, "min": 1, "max": 8,
                                  "tooltip": "Images to generate in one run (seed, seed+1, ...), "
                                             "returned as one batch."}),
                "reference_fit": (REF_FIT, {"default": "match output",
                                            "tooltip": "How references are sized before they go "
                                                       "to the text encoder. A 1024 reference "
                                                       "costs ~4096 tokens. 'keep original size' "
                                                       "only saves time when the reference is "
                                                       "bigger than the output; at 1024x1024 the "
                                                       "two modes measure the same."}),
                "unet_name": (folder_paths.get_filename_list("diffusion_models"),
                              {"default": DEFAULT_UNET}),
                "clip_name": (folder_paths.get_filename_list("text_encoders"),
                              {"default": DEFAULT_CLIP}),
                "vae_name": (folder_paths.get_filename_list("vae"), {"default": DEFAULT_VAE}),
            },
            "optional": {
                # Only the connected sockets reach the text encoder, renumbered 1..N in socket
                # order, so "the second reference" means the second one you wired up.
                "image_1": ("IMAGE", {"tooltip": REF_TOOLTIP}),
                "image_2": ("IMAGE", {"tooltip": REF_TOOLTIP}),
                "image_3": ("IMAGE", {"tooltip": REF_TOOLTIP}),
                "image_4": ("IMAGE", {"tooltip": REF_TOOLTIP}),
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "vae": ("VAE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "info")
    FUNCTION = "generate"
    CATEGORY = "Qwen-Image-2.1"

    def generate(self, prompt, aspect_ratio, megapixels, steps, seed, count, reference_fit,
                 unet_name, clip_name, vae_name,
                 image_1=None, image_2=None, image_3=None, image_4=None,
                 model=None, clip=None, vae=None):
        started = time.perf_counter()
        if model is None:
            model = _load_unet(unet_name)
        if clip is None:
            clip = _load_clip(clip_name)
        if vae is None:
            vae = _load_vae(vae_name)

        refs = {f"image_{i}": im for i, im in enumerate((image_1, image_2, image_3, image_4), 1)
                if im is not None}
        width, height = _size(aspect_ratio, megapixels)
        if steps <= 0:
            # Measured defaults. The official edit template uses 25 steps; a same-seed A/B at
            # 12 vs 20 steps had 12 holding the subject slightly better and ~4 s faster, so the
            # same rule is used in both modes. Keyed on the long side, not the area, so 1 MP at
            # 4:3 or 16:9 (1184x896, 1376x768) also takes 20.
            steps = 12 if max(width, height) <= 1024 else 20
        # 0 tells the text encoder to leave each reference at its own size.
        ref_resolution = 0 if reference_fit == "keep original size" else max(width, height)

        (positive, negative, te_latent) = TextEncodeQwenImage21.execute(
            clip=clip, prompt=prompt, negative_prompt="",
            vae=vae if refs else None, resolution=ref_resolution, images=refs).result
        # With references the text encoder returns an empty latent at the reference size (that
        # is what makes it an edit); without them the aspect ratio decides.
        latent = te_latent if refs else comfy_nodes.EmptyLatentImage().generate(width, height, 1)[0]
        if refs:
            # In edit mode the latent comes from the text encoder and follows the first
            # reference's aspect ratio, so the aspect_ratio / megapixels widgets do not
            # decide the output size. Report what the latent really is.
            try:
                fmt = model.get_model_object("latent_format")
                ratio = int(fmt.spacial_downscale_ratio)
                height = int(latent["samples"].shape[-2] * ratio)
                width = int(latent["samples"].shape[-1] * ratio)
            except Exception as exc:   # never let reporting break the run, but say so
                print("[Qwen21FastGenerate] could not read the latent size (%r); "
                      "reporting the widget size instead" % (exc,))

        batch = []
        for i in range(count):
            # Wrap like ComfyUI's control_after_generate does: the seed widget allows
            # 2^64-1, and seed + i would overflow in torch on a count > 1 run.
            seed_i = (seed + i) % (2 ** 64)
            samples = comfy_nodes.KSampler().sample(
                model, seed_i, steps, CFG, SAMPLER, SCHEDULER, positive, negative,
                latent, denoise=1.0)[0]
            batch.append(comfy_nodes.VAEDecode().decode(vae, samples)[0])
            if count > 1:
                print("[Qwen21FastGenerate] %d/%d done (%.1fs elapsed)"
                      % (i + 1, count, time.perf_counter() - started))
        image = batch[0] if count == 1 else torch.cat(batch, dim=0)

        elapsed = time.perf_counter() - started
        info = ("%s refs=%d %dx%d %d steps cfg=%s %s/%s seeds=%d..%d %.1fs (%.1fs each)"
                % ("edit" if refs else "t2i", len(refs), width, height, steps, CFG, SAMPLER,
                   SCHEDULER, seed, (seed + count - 1) % (2 ** 64), elapsed, elapsed / count))
        print("[Qwen21FastGenerate] " + info)
        return (image, info)


NODE_CLASS_MAPPINGS = {"Qwen21FastGenerate": Qwen21FastGenerate}
NODE_DISPLAY_NAME_MAPPINGS = {"Qwen21FastGenerate": "Qwen 2.1 Fast Generate"}
