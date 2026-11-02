"""Bounded round-robin market scan batches."""


def select_scan_batch(rows, offset=0, batch_size=40):
    """Return (batch, next_offset, actual_offset) without repeating rows in a cycle."""
    items = list(rows or [])
    if not items:
        return [], 0, 0
    try:
        size = max(1, int(batch_size))
        start = int(offset or 0) % len(items)
    except (TypeError, ValueError, OverflowError):
        size, start = 40, 0
    end = min(start + size, len(items))
    batch = items[start:end]
    next_offset = 0 if end >= len(items) else end
    return batch, next_offset, start


def select_priority_scan_batch(rows, offset=0, batch_size=40, priority_size=10):
    """Rescan the top fast movers every cycle while rotating through the rest."""
    items = list(rows or [])
    if not items:
        return [], 0, 0, 0
    try:
        size = max(1, int(batch_size))
        priority_count = min(max(0, int(priority_size)), size, len(items))
        start_offset = int(offset or 0)
    except (TypeError, ValueError, OverflowError):
        size, priority_count, start_offset = 40, 10, 0
    priority = items[:priority_count]
    rotating = items[priority_count:]
    if not rotating or size <= priority_count:
        return priority, 0, 0, priority_count
    batch, next_offset, actual_offset = select_scan_batch(
        rotating, start_offset, size - priority_count
    )
    return priority + batch, next_offset, actual_offset, priority_count
