"""Small boolean-mask helpers retained from the previous pipeline.

The VAD, mask shaping, gap merging, and SNR-adaptive silence detection
that used to live here have been removed — their job is now done by
Silero VAD + hysteresis in ``services.transcription.dsp.vad``.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np


def _find_mask_runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """Return ``[(start, end), ...]`` index pairs for contiguous True runs."""
    n = len(mask)
    if n == 0:
        return []
    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = mask
    padded[-1] = False
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return list(zip(starts.tolist(), ends.tolist()))
