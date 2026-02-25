import gc

from quart import Blueprint

from utilities.memory import release_memory

kubernetes_bp = Blueprint('kubernetes_bp', __name__)


@kubernetes_bp.route('/api/health/alive')
def alive():
    return {'status': 'ok'}, 200


@kubernetes_bp.route('/api/health/ready')
def ready():
    return {'status': 'ok'}, 200


@kubernetes_bp.route('/api/diag/memory')
def memory_diagnostics():
    """Return current process memory usage for debugging leaks."""

    # Try reading /proc/self/status for RSS (Linux / K8s)
    rss_mb = None
    vms_mb = None
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    rss_mb = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith('VmSize:'):
                    vms_mb = round(int(line.split()[1]) / 1024, 1)
    except (FileNotFoundError, PermissionError):
        pass

    # Count objects by type (top 20)
    gc.collect()
    type_counts: dict[str, int] = {}
    for obj in gc.get_objects():
        t = type(obj).__name__
        type_counts[t] = type_counts.get(t, 0) + 1

    top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        'rss_mb': rss_mb,
        'vms_mb': vms_mb,
        'gc_tracked_objects': len(gc.get_objects()),
        'gc_stats': gc.get_stats(),
        'top_object_types': {k: v for k, v in top_types},
    }, 200


@kubernetes_bp.route('/api/diag/gc')
def force_gc():
    """Force a full garbage collection cycle and malloc_trim, return stats."""
    before = len(gc.get_objects())
    result = release_memory()
    after = len(gc.get_objects())

    return {
        'gc_collected': result['gc_collected'],
        'malloc_trimmed': result['malloc_trimmed'],
        'objects_before': before,
        'objects_after': after,
        'freed': before - after,
    }, 200
