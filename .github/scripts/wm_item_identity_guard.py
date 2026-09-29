"""Fail-closed stable-ID continuity checks for the Ws-Web item catalog."""


def _items_by_stable_id(document, label, minimum):
    if not isinstance(document, dict):
        raise ValueError(f"{label} WM item manifest is not an object")

    items = document.get("items")
    if (
        not isinstance(items, list)
        or document.get("count") != len(items)
        or len(items) < minimum
    ):
        raise ValueError(f"{label} WM item manifest is incomplete")

    by_id = {}
    slugs = set()
    for row in items:
        if not isinstance(row, dict):
            raise ValueError(f"{label} WM item manifest contains an invalid row")

        item_id = row.get("id")
        slug = row.get("slug")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"{label} WM item manifest has a missing stable ID")
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError(f"{label} WM item manifest has a missing slug")

        item_id = item_id.strip()
        slug = slug.strip()
        if item_id in by_id:
            raise ValueError(f"{label} WM item manifest has duplicate stable IDs")
        if slug in slugs:
            raise ValueError(f"{label} WM item manifest has duplicate slugs")
        by_id[item_id] = slug
        slugs.add(slug)

    return by_id


def validate_stable_id_continuity(previous_document, current_document, minimum=1500):
    """Require every previously published stable ID to remain in the new catalog.

    Slugs may change only while the same stable ID remains. Names and slug
    similarity are deliberately not used to infer identity.
    """
    previous = _items_by_stable_id(previous_document, "previous", minimum)
    current = _items_by_stable_id(current_document, "current", minimum)

    lost = set(previous) - set(current)
    if lost:
        lost_slugs = [previous[item_id] for item_id in sorted(lost)]
        sample = ", ".join(lost_slugs[:8])
        suffix = " ..." if len(lost_slugs) > 8 else ""
        raise ValueError(
            "WM item manifest lost %d previously published stable IDs: %s%s"
            % (len(lost), sample, suffix)
        )

    return sum(previous[item_id] != current[item_id] for item_id in previous)
