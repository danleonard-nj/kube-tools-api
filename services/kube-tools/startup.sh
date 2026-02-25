echo "Hello!  Starting up the server..."

# Tune glibc's malloc to return freed memory to the OS more aggressively.
# MALLOC_TRIM_THRESHOLD_: lower value = more frequent mmap trimming (default 128 KB).
# MALLOC_MMAP_THRESHOLD_: allocations above this go via mmap and are fully
#   returned on free (default 128 KB; 64 KB catches more numpy temporaries).
# MALLOC_ARENA_MAX: limit per-thread arenas to reduce fragmentation.
export MALLOC_TRIM_THRESHOLD_=65536
export MALLOC_MMAP_THRESHOLD_=65536
export MALLOC_ARENA_MAX=2

uvicorn --log-level=error --host 0.0.0.0 --port=80 --workers 2 app:app