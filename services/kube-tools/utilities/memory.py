"""Memory management utilities.

On Linux (glibc), CPython's pymalloc allocator and numpy both use
``malloc`` arenas that are *not* returned to the OS when objects are
freed.  The process RSS grows monotonically even though Python's GC
has reclaimed all references.

``release_memory()`` calls ``gc.collect()`` followed by glibc's
``malloc_trim(0)`` to compact the heap and return freed pages to the
OS.  This is critical for workloads that create large temporary numpy
arrays (e.g. audio DSP pipelines) — without it, a single 10-minute
audio transcription can permanently inflate RSS by 500 MB+.

On non-Linux platforms (Windows, macOS), ``malloc_trim`` is unavailable
and the function falls back to ``gc.collect()`` only.
"""

import ctypes
import gc
import sys

from framework.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Attempt to load glibc's malloc_trim (Linux only)
# ---------------------------------------------------------------------------
_malloc_trim = None
if sys.platform == 'linux':
    try:
        _libc = ctypes.CDLL('libc.so.6')
        _malloc_trim = _libc.malloc_trim
        _malloc_trim.argtypes = [ctypes.c_size_t]
        _malloc_trim.restype = ctypes.c_int
    except (OSError, AttributeError):
        _malloc_trim = None


def release_memory() -> dict:
    """Force Python GC and (on Linux) return freed heap pages to the OS.

    Returns a dict with diagnostics: GC objects collected, and whether
    malloc_trim was called.
    """
    collected = gc.collect()
    trimmed = False

    if _malloc_trim is not None:
        try:
            _malloc_trim(0)
            trimmed = True
        except Exception as exc:
            logger.debug("malloc_trim failed: %s", exc)

    logger.info(
        "release_memory: gc.collect freed %d objects, malloc_trim=%s",
        collected, trimmed,
    )
    return {'gc_collected': collected, 'malloc_trimmed': trimmed}
