import os
import sys
from collections import OrderedDict

import numpy as np
import onnx
import torch
import torch.nn as nn

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "synccut", "ai", "light_asd_repo"))

try:
    from model.Model import ASD_Model
except ImportError as e:
    print(f"Failed to import ASD_Model. Error: {e}")
    sys.exit(1)

CKPT_PATH = os.path.join(BASE, "synccut", "ai", "models", "finetuning_TalkSet.model")
TEMP_ONNX = os.path.join(BASE, "temp_light_asd.onnx")
FINAL_ONNX = os.path.join(BASE, "synccut", "ai", "models", "light_asd.onnx")


# ---------------------------------------------------------------- load model
print("Loading PyTorch model...")
model = ASD_Model()
state_dict = torch.load(CKPT_PATH, map_location="cpu")

model_sd = OrderedDict()
fc_sd = OrderedDict()
for k, v in state_dict.items():
    if k.startswith("model."):
        model_sd[k[len("model."):]] = v
    elif k.startswith("lossAV.FC."):
        fc_sd[k[len("lossAV.FC."):]] = v  # final Linear(128 -> 2)

model.load_state_dict(model_sd, strict=True)
model.eval()

if not fc_sd:
    print("Could not find 'lossAV.FC.*' keys. Keys containing 'lossAV':")
    print([k for k in state_dict if "lossAV" in k])
    sys.exit(1)

fc = nn.Linear(128, 2)
fc.load_state_dict(fc_sd, strict=True)
fc.eval()


# ------------------------------------------------------------------ wrapper
class LightASDExport(nn.Module):
    """
    audio : (1, 4*T, 13)    MFCC features (4 MFCC steps per video frame)
    visual: (1, T, 112, 112) grayscale face crops, values 0..255 (float)
    output: (T, 2)          logits; speaking score = output[:, 1]
    """

    def __init__(self, model, fc):
        super().__init__()
        self.model = model
        self.fc = fc

    def forward(self, audio, visual):
        a = self.model.forward_audio_frontend(audio)    # (1, T, 128)
        v = self.model.forward_visual_frontend(visual)  # (1, T, 128)
        x = self.model.forward_audio_visual_backend(a, v)  # (T, 128)
        return self.fc(x)                               # (T, 2)


wrapper = LightASDExport(model, fc).eval()

# ------------------------------------------------------------ dummy inputs
T = 25  # video frames (1 second at 25 fps)
audio_input = torch.randn(1, T * 4, 13)
visual_input = torch.randint(0, 255, (1, T, 112, 112)).float()

with torch.no_grad():
    torch_out = wrapper(audio_input, visual_input)
print("PyTorch output shape:", tuple(torch_out.shape))  # expect (25, 2)


# ------------------------------------------- fix MaxPool3d on 4D inputs
# PyTorch lets MaxPool3d run on a 4D (unbatched) tensor, but ONNX treats a
# 4D input as 2D spatial, so the 3-value kernel/stride is invalid. Where the
# leading kernel dim is a no-op (k=1, s=1, p=0), swap in an equivalent MaxPool2d.
def _as_tuple3(v):
    return (v, v, v) if isinstance(v, int) else tuple(v)


pool_input_dims = {}
hooks = []
for name, m in wrapper.named_modules():
    if isinstance(m, nn.MaxPool3d):
        hooks.append(
            m.register_forward_pre_hook(
                lambda mod, inp, n=name: pool_input_dims.__setitem__(n, inp[0].dim())
            )
        )
with torch.no_grad():
    wrapper(audio_input, visual_input)
for h in hooks:
    h.remove()

for name, dim in pool_input_dims.items():
    if dim != 4:
        continue  # real 5D input: MaxPool3d is fine
    parent = wrapper
    parts = name.split(".")
    for p in parts[:-1]:
        parent = getattr(parent, p)
    old = getattr(parent, parts[-1])
    k, s, p_ = _as_tuple3(old.kernel_size), _as_tuple3(old.stride), _as_tuple3(old.padding)
    if k[0] == 1 and s[0] == 1 and p_[0] == 0:
        setattr(
            parent,
            parts[-1],
            nn.MaxPool2d(k[1:], stride=s[1:], padding=p_[1:], ceil_mode=old.ceil_mode),
        )
        print(f"Patched {name}: MaxPool3d{k} -> MaxPool2d{k[1:]}")
    else:
        print(f"WARNING: {name} is MaxPool3d k={k} s={s} p={p_} on a 4D input; "
              "cannot auto-convert. Paste Encoder.py and I'll fix it by hand.")

with torch.no_grad():
    patched_out = wrapper(audio_input, visual_input)
print("Patched model max diff vs original:",
      float((patched_out - torch_out).abs().max()))

# ------------------------------------------------------------------ export
print("Exporting to ONNX (legacy exporter)...")
torch.onnx.export(
    wrapper,
    (audio_input, visual_input),
    TEMP_ONNX,
    dynamo=False,
    opset_version=13,
    input_names=["audio_input", "visual_input"],
    output_names=["output"],
    dynamic_axes={
        "audio_input": {1: "audio_len"},    # must equal 4 * num_frames
        "visual_input": {1: "num_frames"},
        "output": {0: "num_frames"},
    },
)

# ------------------------------------------------------- fix MaxPool attrs
print("Fixing ONNX graph (MaxPool dilations)...")
onnx_model = onnx.load(TEMP_ONNX)
for node in onnx_model.graph.node:
    if node.op_type == "MaxPool":
        for attr in list(node.attribute):
            if attr.name == "dilations":
                node.attribute.remove(attr)

onnx.checker.check_model(onnx_model)
os.makedirs(os.path.dirname(FINAL_ONNX), exist_ok=True)
onnx.save(onnx_model, FINAL_ONNX)
if os.path.exists(TEMP_ONNX):
    os.remove(TEMP_ONNX)
print(f"Saved: {FINAL_ONNX}")

# ------------------------------------------------------------------ verify
try:
    import onnxruntime as ort

    sess = ort.InferenceSession(FINAL_ONNX, providers=["CPUExecutionProvider"])
    for t in (25, 50):  # includes a different length to test dynamic axes
        a = torch.randn(1, t * 4, 13)
        v = torch.randint(0, 255, (1, t, 112, 112)).float()
        with torch.no_grad():
            ref = wrapper(a, v).numpy()
        out = sess.run(None, {"audio_input": a.numpy(), "visual_input": v.numpy()})[0]
        diff = float(np.abs(ref - out).max())
        print(f"T={t}: output {out.shape}, max abs diff vs PyTorch = {diff:.2e}")
except ImportError:
    print("onnxruntime not installed; skipping verification (pip install onnxruntime).")

print("Done. Speaking score per frame = output[:, 1]")