import contextvars
from contextlib import contextmanager
from threading import Lock

_SEQ_LOCK = Lock()
_SEQ = 0

_BUCKETS_LOCK = Lock()
_BUCKETS = {}

_CACHE_LOCK = Lock()

_CURRENT_DEPENDENCY = contextvars.ContextVar(
    "core_observe_current_dependency", default=("unknown", "unknown")
)


def get_current_dependency():
    return _CURRENT_DEPENDENCY.get()

def _normalize_dep_str(dep_str) -> str:
    if dep_str is None:
        return "unknown"
    t = str(dep_str).strip()
    return t or "unknown"


@contextmanager
def dependency_context(dep_name="unknown", dep_type="unknown"):
    dep_name = _normalize_dep_str(dep_name)
    dep_type = _normalize_dep_str(dep_type)

    ensure_dependency_bucket(dep_name, dep_type=dep_type)

    token = _CURRENT_DEPENDENCY.set((dep_name, dep_type))
    try:
        yield dep_name
    finally:
        _CURRENT_DEPENDENCY.reset(token)


def _linear_interpolate(sorted_vals, q: float):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    if q <= 0:
        return float(sorted_vals[0])
    if q >= 1:
        return float(sorted_vals[-1])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo]) + (float(sorted_vals[hi]) - float(sorted_vals[lo])) * frac


def _summarize_download_durations(count: int, sum_ms: int, durations_ms):
    if count <= 0:
        return {"count": 0}
    durations = sorted(durations_ms)
    avg = float(sum_ms) / float(count)
    out = {"count": int(count), "avgMs": avg}
    p50 = _linear_interpolate(durations, 0.5)
    p90 = _linear_interpolate(durations, 0.9)
    p95 = _linear_interpolate(durations, 0.95)
    if p50 is not None:
        out["p50Ms"] = p50
    if p90 is not None:
        out["p90Ms"] = p90
    if p95 is not None:
        out["p95Ms"] = p95
    return out


class _DownloadStats:
    def __init__(self):
        self.count = 0
        self.sum_ms = 0
        self._durations_ms = []

    def add(self, duration_ms: int):
        if duration_ms is None:
            return
        self.count += 1
        self.sum_ms += duration_ms
        self._durations_ms.append(duration_ms)

    def snapshot(self):
        return int(self.count), int(self.sum_ms), list(self._durations_ms)


_CACHE_ALL = {"hit": 0, "miss": 0}
_CACHE_BY_KIND = {}


class _DownloadBucket:
    def __init__(self, dep_name: str, dep_type: str = "unknown"):
        self.dep_name = dep_name
        self.dep_type = _normalize_dep_str(dep_type)
        self.lock = Lock()
        self.tasks = []
        self.stats = _DownloadStats()
        self.cached = False
        self.bytes_sum = 0
        self.span_duration_ms = 0


def _get_download_bucket(dep_name, dep_type=None):
    dep_key = _normalize_dep_str(dep_name)
    with _BUCKETS_LOCK:
        bucket = _BUCKETS.get(dep_key)
        if bucket is None:
            bucket = _DownloadBucket(dep_key, dep_type or "unknown")
            _BUCKETS[dep_key] = bucket
        return bucket


def ensure_dependency_bucket(dep_name, dep_type=None):
    _get_download_bucket(dep_name, dep_type=dep_type)


def reset_download_profiling():
    global _SEQ
    global _BUCKETS
    global _CACHE_ALL, _CACHE_BY_KIND

    with _BUCKETS_LOCK:
        _BUCKETS = {}

    with _SEQ_LOCK:
        _SEQ = 0

    with _CACHE_LOCK:
        _CACHE_ALL = {"hit": 0, "miss": 0}
        _CACHE_BY_KIND = {}


def record_cache_access(kind: str, hit: bool):
    if kind is None:
        kind = "unknown"
    kind = str(kind)

    dep_name, dep_type = get_current_dependency()
    dep_name = _normalize_dep_str(dep_name)
    dep_bucket = _get_download_bucket(dep_name)

    with dep_bucket.lock:
        dep_bucket.cached = hit

    with _CACHE_LOCK:
        if hit:
            _CACHE_ALL["hit"] += 1
        else:
            _CACHE_ALL["miss"] += 1
        bucket = _CACHE_BY_KIND.get(kind)
        if bucket is None:
            bucket = {"hit": 0, "miss": 0}
            _CACHE_BY_KIND[kind] = bucket
        if hit:
            bucket["hit"] += 1
        else:
            bucket["miss"] += 1


def _normalize_download_task(duration_ms: int, task):
    # a fixed schema
    base = {
        "durationMs": int(duration_ms) if duration_ms is not None else 0,
        "kind": "unknown",
        "url": "",
        "objectKey": "",
        "range": {"start": 0, "end": 0},
        "bytes": 0,
        "tool": "",
        "command": "",
        "dep_name": "unknown"
    }

    base["dep_name"], _ = get_current_dependency()

    kind = task.get("kind")
    if kind is not None and str(kind).strip():
        base["kind"] = str(kind)
    url = task.get("url")
    if url is not None:
        base["url"] = str(url)
    object_key = task.get("objectKey")
    if object_key is not None:
        base["objectKey"] = str(object_key)
    tool = task.get("tool")
    if tool is not None:
        base["tool"] = str(tool)
    command = task.get("command")
    if command is not None:
        base["command"] = str(command)
    try:
        b = task.get("bytes")
        if b is not None:
            base["bytes"] = int(b)
    except Exception:
        base["bytes"] = 0
    r = task.get("range")
    if isinstance(r, dict):
        try:
            start = r.get("start")
            end = r.get("end")
            base["range"] = {
                "start": 0 if start is None else int(start),
                "end": 0 if end is None else int(end),
            }
        except Exception:
            base["range"] = {"start": 0, "end": 0}
    else:
        base["range"] = {"start": 0, "end": 0}

    return base


def record_download_task(duration_ms: int, task: dict):
    global _SEQ
    duration_ms = int(duration_ms)

    normalized_task = _normalize_download_task(duration_ms, task)

    bucket = _get_download_bucket(normalized_task.get("dep_name"))

    with _SEQ_LOCK:
        _SEQ += 1
        seq = _SEQ

    with bucket.lock:
        bucket.tasks.append((duration_ms, seq, normalized_task))
        bucket.stats.add(duration_ms)
        try:
            bucket.bytes_sum += int(normalized_task.get("bytes") or 0)
        except Exception:
            pass


def get_all_download_tasks_sorted() -> list:
    with _BUCKETS_LOCK:
        buckets = list(_BUCKETS.values())

    items = []
    for bucket in buckets:
        with bucket.lock:
            items.extend(bucket.tasks)

    items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [t for _, __, t in items]


def get_top_slowest_download_tasks(limit: int = 10) -> list:
    tasks = get_all_download_tasks_sorted()
    return tasks[: int(limit)]


def record_dependency_span(duration_ms: int, dep_name=None):
    duration_ms = int(duration_ms)
    if dep_name is None:
        dep_name, _ = get_current_dependency()
    bucket = _get_download_bucket(dep_name)
    with bucket.lock:
        bucket.span_duration_ms += duration_ms


def get_download_time_by_dependency():
    with _BUCKETS_LOCK:
        buckets = list(_BUCKETS.values())

    out = []
    for bucket in buckets:
        with bucket.lock:
            count, sum_ms, _ = bucket.stats.snapshot()
            span_sum_ms = int(bucket.span_duration_ms)
            bytes_sum = int(bucket.bytes_sum)
        out.append(
            {
                "dep_name": bucket.dep_name,
                "dep_type": bucket.dep_type,
                "cached": bucket.cached,
                "count": int(count),
                "downloadDurationMs": int(sum_ms),
                "bytes": int(bytes_sum),
                "spanDurationMs": int(span_sum_ms),
            }
        )

    out.sort(
        key=lambda x: (x.get("spanDurationMs", 0), x.get("downloadDurationMs", 0)),
        reverse=True,
    )
    return out


def get_download_time_stats():
    with _BUCKETS_LOCK:
        buckets = list(_BUCKETS.values())

    total_count = 0
    total_sum_ms = 0
    durations = []

    for bucket in buckets:
        with bucket.lock:
            count, sum_ms, vals = bucket.stats.snapshot()
        total_count += count
        total_sum_ms += sum_ms
        durations.extend(vals)

    return _summarize_download_durations(total_count, total_sum_ms, durations)


def get_cache_stats():
    with _CACHE_LOCK:
        overall = dict(_CACHE_ALL)
        by_kind = {k: dict(v) for k, v in _CACHE_BY_KIND.items()}
    if by_kind:
        overall["byKind"] = by_kind
    return overall


__all__ = [
    "reset_download_profiling",
    "record_cache_access",
    "record_download_task",
    "record_dependency_span",
    "ensure_dependency_bucket",
    "get_all_download_tasks_sorted",
    "get_top_slowest_download_tasks",
    "get_download_time_by_dependency",
    "get_download_time_stats",
    "get_cache_stats",
    "dependency_context",
    "get_current_dependency",
]