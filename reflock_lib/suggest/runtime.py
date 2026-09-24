"""The one module that touches the `[suggest]` extra.

Everything else in `reflock_lib.suggest` is standard library. Keeping the
third-party imports here, and only here, is what lets `cmd_suggest` find out
whether the extra is installed before doing any work, and name the install
command instead of dying on an ImportError half-way through.
"""
from __future__ import annotations

INSTALL_HINT = ("reflock suggest needs the model runtime, which reflock itself does not "
                "install:\n"
                "  pip install 'reflock[suggest]'\n"
                "  brew install a-grasso/tap/reflock-suggest")


class MissingRuntime(Exception):
    """The `[suggest]` extra is not installed."""


def require() -> None:
    """Raise MissingRuntime unless the runtime imports."""
    try:
        import numpy          # noqa: F401
        import onnxruntime    # noqa: F401
    except ImportError as e:
        raise MissingRuntime("%s\n(%s)" % (INSTALL_HINT, e)) from None


class Session:
    def __init__(self, path: str):
        import numpy as np
        import onnxruntime as ort

        self._np = np
        opts = ort.SessionOptions()
        opts.log_severity_level = 3       # onnxruntime warns about unused initializers
        self._s = ort.InferenceSession(path, sess_options=opts,
                                       providers=["CPUExecutionProvider"])

    def logits(self, ids: list[int], markers: list[int]) -> list[float]:
        np = self._np
        feed = {
            "input_ids": np.array([ids], dtype=np.int64),
            "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            "marker_pos": np.array([markers], dtype=np.int64),
            "marker_mask": np.ones((1, len(markers)), dtype=np.bool_),
            "qtype": np.zeros((1,), dtype=np.int64),       # 0 == choice
        }
        return [float(x) for x in self._s.run(None, feed)[0][0]]
