try:
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
except ImportError as exc:
    # Typically an older ComfyUI: this node composes comfy_extras.nodes_qwen
    # .TextEncodeQwenImage21, which only recent versions ship. Registering nothing is
    # better than a bare traceback with no hint about the version.
    print("[qwen21_fast] node not loaded: %s" % exc)
    print("[qwen21_fast] needs ComfyUI 0.37 or newer "
          "(comfy_extras.nodes_qwen.TextEncodeQwenImage21) - update ComfyUI and restart.")
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
