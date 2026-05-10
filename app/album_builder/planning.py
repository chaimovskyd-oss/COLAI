"""Page planner: distributes images across album pages with varied density.

Algorithm produces a *rhythm* of page sizes rather than uniform density:
  - Hero pages:    1–2 images  (strongest shots — breathing room)
  - Feature pages: 2–4 images  (important moments)
  - Story pages:   4–6 images  (narrative sequences)
  - Dense pages:   6–9 images  (background / filler)

If target_pages > 0 the mix is scaled to hit that page count.
If density != 'mixed' a uniform style is forced (for users who prefer that).
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from .models import AlbumPage, AlbumSettings, DENSITY_LIMITS, PhotoMeta


# Rhythm pattern: each entry is (page_type, size_range)
# The planner cycles through this pattern, adjusting for actual image count.
_RHYTHM = [
    ('hero',    (1, 2)),
    ('story',   (4, 6)),
    ('feature', (2, 4)),
    ('dense',   (6, 9)),
    ('story',   (3, 5)),
    ('feature', (2, 3)),
    ('dense',   (5, 8)),
    ('story',   (4, 6)),
]


def plan_pages(
    metas: List[PhotoMeta],
    settings: AlbumSettings,
) -> List[AlbumPage]:
    """Return AlbumPage list with image_indices assigned. Layouts set later."""
    n = len(metas)
    if n == 0:
        return []

    # Sort images by importance descending; heroes at the front
    sorted_idx = sorted(range(n), key=lambda i: -metas[i].importance)

    if settings.density == 'mixed':
        sizes = _mixed_sizes(n, settings)
    else:
        sizes = _uniform_sizes(n, settings)

    # Assign sorted images into pages
    page_batches: List[List[int]] = []
    pos = 0
    for size in sizes:
        batch = sorted_idx[pos: pos + size]
        if not batch:
            break
        page_batches.append(batch)
        pos += size

    # Overflow: add remaining to last page (or a new page)
    if pos < n:
        overflow = sorted_idx[pos:]
        if page_batches and len(page_batches[-1]) + len(overflow) <= 10:
            page_batches[-1].extend(overflow)
        else:
            page_batches.append(overflow)

    return [
        AlbumPage(page_index=i, image_indices=list(b))
        for i, b in enumerate(page_batches)
    ]


# ─── size-sequence generators ─────────────────────────────────────────────────

def _mixed_sizes(n: int, settings: AlbumSettings) -> List[int]:
    """Variable-density sequence with rhythmic small/large alternation."""
    target = settings.target_pages

    if target and target > 0:
        return _sizes_for_target(n, target, settings.hero_pages)

    # Auto: cycle through rhythm pattern scaled to image count
    sizes: List[int] = []
    remaining = n
    cycle = 0

    while remaining > 0:
        page_type, (lo, hi) = _RHYTHM[cycle % len(_RHYTHM)]

        # Hero pages only when hero_pages is enabled
        if page_type == 'hero' and not settings.hero_pages:
            cycle += 1
            continue

        # Don't create a hero page if already processed hero budget
        hero_done = sum(1 for s in sizes[:3] if s <= 2)
        if page_type == 'hero' and hero_done >= max(1, n // 20):
            cycle += 1
            continue

        size = min(remaining, _clamp(lo, hi, remaining))
        # Don't leave a tiny leftover
        if remaining - size < lo and remaining - size > 0:
            size = remaining          # absorb remainder
        sizes.append(size)
        remaining -= size
        cycle += 1

    return sizes


def _sizes_for_target(n: int, target: int, hero_pages: bool) -> List[int]:
    """Produce exactly `target` pages (or as close as possible) that sum to n.

    Creates a rhythmic mix: ~15% hero (1–3 imgs), ~30% feature (2–4),
    ~55% dense (proportional). Clamped so total == n.
    """
    if target >= n:
        # One image per page (up to n)
        return [1] * n

    avg = n / target

    # Decide how many pages of each tier to create
    if hero_pages:
        n_hero = max(1, round(target * 0.12))
    else:
        n_hero = 0
    n_feature = max(1, round(target * 0.28))
    n_dense = max(1, target - n_hero - n_feature)

    # Sizes for each tier
    hero_size = max(1, min(2, round(avg * 0.35)))
    feature_size = max(2, min(4, round(avg * 0.70)))
    dense_size = max(3, round(
        (n - n_hero * hero_size - n_feature * feature_size) / max(1, n_dense)
    ))
    dense_size = min(10, dense_size)

    # Build the raw sizes
    raw: List[Tuple[str, int]] = (
        [('hero', hero_size)] * n_hero
        + [('feature', feature_size)] * n_feature
        + [('dense', dense_size)] * n_dense
    )

    # Interleave for visual rhythm: h f d f d d f d d d ...
    ordered = _interleave(raw)
    sizes = [s for _, s in ordered]

    # Adjust total to match n exactly
    sizes = _adjust_sum(sizes, n)
    return sizes


def _uniform_sizes(n: int, settings: AlbumSettings) -> List[int]:
    """All pages same target size (for 'airy' / 'balanced' / 'dense' mode)."""
    lo, hi = DENSITY_LIMITS.get(settings.density, (4, 7))
    target_pp = (lo + hi) // 2
    sizes = []
    remaining = n
    while remaining > 0:
        size = min(remaining, target_pp)
        if remaining - size < lo and remaining - size > 0:
            size = remaining
        sizes.append(size)
        remaining -= size
    return sizes


# ─── helpers ─────────────────────────────────────────────────────────────────

def _clamp(lo: int, hi: int, cap: int) -> int:
    return max(lo, min(hi, cap))


def _interleave(items: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
    """Order items so hero → feature → dense → feature → dense → dense..."""
    heroes  = [x for x in items if x[0] == 'hero']
    features = [x for x in items if x[0] == 'feature']
    dense   = [x for x in items if x[0] == 'dense']
    result = []
    fi = di = 0
    for h in heroes:
        result.append(h)
        if fi < len(features):
            result.append(features[fi]); fi += 1
        if di < len(dense):
            result.append(dense[di]); di += 1
    # Remaining: alternate feature / dense
    while fi < len(features) or di < len(dense):
        if fi < len(features):
            result.append(features[fi]); fi += 1
        if di < len(dense):
            result.append(dense[di]); di += 1
    return result


def _adjust_sum(sizes: List[int], target_sum: int) -> List[int]:
    """Trim or grow sizes list so that sum(sizes) == target_sum."""
    if not sizes:
        return [target_sum]
    current = sum(sizes)
    diff = target_sum - current
    if diff == 0:
        return sizes
    result = list(sizes)
    i = len(result) - 1
    while diff != 0 and i >= 0:
        if diff > 0:
            result[i] += 1
            diff -= 1
        elif result[i] > 1:
            result[i] -= 1
            diff += 1
        i -= 1
        if i < 0:
            i = len(result) - 1
    # Remove zero-size pages
    return [s for s in result if s > 0]
