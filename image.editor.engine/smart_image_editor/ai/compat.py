from __future__ import annotations

import sys
import types


def install_torchvision_functional_tensor_shim() -> None:
    """Shim for older BasicSR expecting torchvision.transforms.functional_tensor."""
    if "torchvision.transforms.functional_tensor" in sys.modules:
        return
    try:
        from torchvision.transforms.functional import rgb_to_grayscale
    except Exception:
        return
    module = types.ModuleType("torchvision.transforms.functional_tensor")
    module.rgb_to_grayscale = rgb_to_grayscale
    sys.modules["torchvision.transforms.functional_tensor"] = module
