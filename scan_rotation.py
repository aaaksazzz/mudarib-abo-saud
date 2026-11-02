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
