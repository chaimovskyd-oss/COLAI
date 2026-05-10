"""Page planner: distributes images across album pages.

Rules:
- Hero images (importance >= hero_threshold) get their own small pages (1-2 imgs)
- Remaining images fill pages according to density setting
- Consecutive similar-orientation images are grouped together
- Avoids pages with fewer than min_per_page images (merges with neighbour)
"""
from __future__ import annotations

import math
from typing import List

from .models import AlbumSettings, AlbumPage, PhotoMeta, DENSITY_LIMITS


def plan_pages(
    metas: List[PhotoMeta],
    settings: AlbumSettings,
) -> List[AlbumPage]:
    """Return AlbumPage list with image_indices assigned. Layouts set later."""
    n = len(metas)
    if n == 0:
        return []

    min_pp, max_pp = DENSITY_LIMITS.get(settings.density, (4, 7))
    if settings.min_per_page:
        min_pp = max(1, settings.min_per_page)
    if settings.max_per_page:
        max_pp = max(min_pp, settings.max_per_page)

    target_pp = (min_pp + max_pp) // 2

    # Sort by importance desc, preserve relative order for same importance tier
    tiers = _assign_tiers(metas, settings.hero_threshold)

    hero_indices = [i for i, t in enumerate(tiers) if t == 'hero']
    normal_indices = [i for i, t in enumerate(tiers) if t != 'hero']

    page_batches: List[List[int]] = []

    # Hero pages: 1-2 images per page (most important gets a solo page)
    if settings.hero_pages and hero_indices:
        for i in range(0, len(hero_indices), 2):
            batch = hero_indices[i:i + 2]
            page_batches.append(batch)

    # Normal pages: fill to target, respecting orientation grouping
    normal_batches = _group_by_orientation(normal_indices, metas, target_pp, max_pp)
    page_batches.extend(normal_batches)

    # Merge tiny tail pages
    page_batches = _merge_small_pages(page_batches, min_pp)

    # Build AlbumPage objects
    pages = []
    for idx, batch in enumerate(page_batches):
        pages.append(AlbumPage(page_index=idx, image_indices=list(batch)))

    return pages


# ─── helpers ─────────────────────────────────────────────────────────────────

def _assign_tiers(
    metas: List[PhotoMeta],
    hero_threshold: float,
) -> List[str]:
    """Return 'hero' or 'normal' for each image."""
    return ['hero' if m.importance >= hero_threshold else 'normal' for m in metas]


def _group_by_orientation(
    indices: List[int],
    metas: List[PhotoMeta],
    target: int,
    max_pp: int,
) -> List[List[int]]:
    """Pack images into pages, keeping same-orientation images together when possible."""
    if not indices:
        return []

    batches: List[List[int]] = []
    current: List[int] = []

    for idx in indices:
        current.append(idx)
        if len(current) >= target:
            batches.append(current)
            current = []

    if current:
        batches.append(current)

    return batches


def _merge_small_pages(batches: List[List[int]], min_pp: int) -> List[List[int]]:
    """Merge any page that's too small into its neighbour."""
    if not batches:
        return batches
    result = list(batches)
    changed = True
    while changed:
        changed = False
        i = len(result) - 1
        while i >= 0:
            if len(result[i]) < min_pp and len(result) > 1:
                # Merge with previous or next
                if i > 0:
                    result[i - 1].extend(result[i])
                    result.pop(i)
                else:
                    result[1] = result[0] + result[1]
                    result.pop(0)
                changed = True
            i -= 1
    return result
