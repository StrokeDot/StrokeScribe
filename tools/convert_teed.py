"""One-time conversion of TEED (MIT, Xavier Soria Poma) to ONNX for StrokeScribe.

Run in CI with PyTorch installed and the TEED repository cloned to ./TEED.
Writes models/teed.onnx (sigmoid edge probability, 1x1xHxW; H and W must be
multiples of 8) and verifies ONNX Runtime output against PyTorch.
"""
import sys
import numpy as np
import torch

sys.path.insert(0, 'TEED')
# ted.py imports a training helper module (needs cv2/kornia/skimage); the
# model itself only uses count_parameters from it, so provide a stand-in.
import types  # noqa: E402
_helpers = types.ModuleType('utils.img_processing')
_helpers.count_parameters = lambda model: sum(p.numel() for p in model.parameters())
sys.modules['utils.img_processing'] = _helpers
import utils.AF.Fsmish as fsmish_module  # noqa: E402


def smish(x):  # same math as TEED's TorchScript smish, exportable
    return x * torch.tanh(torch.log(1 + torch.sigmoid(x)))


fsmish_module.smish = smish
import utils.AF.Xsmish as xsmish_module  # noqa: E402
if hasattr(xsmish_module, 'Func'):
    xsmish_module.Func.smish = smish
for name in dir(xsmish_module):
    obj = getattr(xsmish_module, name)
    if callable(obj) and name == 'smish':
        setattr(xsmish_module, name, smish)
import ted  # noqa: E402
ted.Fsmish = smish


class Fused(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, x):
        return torch.sigmoid(self.model(x)[-1])


model = ted.TED()
model.load_state_dict(torch.load('TEED/checkpoints/BIPED/5/5_model.pth', map_location='cpu'))
model.eval()
wrapped = Fused(model).eval()
sample = torch.randn(1, 3, 256, 320) * 40
torch.onnx.export(wrapped, sample, 'models/teed.onnx', input_names=['image'],
                  output_names=['edges'], opset_version=17, dynamo=False,
                  dynamic_axes={'image': {2: 'h', 3: 'w'}, 'edges': {2: 'h', 3: 'w'}})

import onnxruntime as ort  # noqa: E402
session = ort.InferenceSession('models/teed.onnx', providers=['CPUExecutionProvider'])
for shape in ((1, 3, 256, 320), (1, 3, 512, 384)):
    x = torch.randn(*shape) * 40
    with torch.no_grad():
        expected = wrapped(x).numpy()
    got = session.run(None, {'image': x.numpy()})[0]
    diff = float(np.abs(expected - got).max())
    print('shape', shape, 'max diff', diff)
    assert got.shape == expected.shape and diff < 1e-3, diff
print('TEED ONNX ok')
