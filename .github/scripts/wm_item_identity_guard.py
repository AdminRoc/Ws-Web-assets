"""Fail-closed stable-ID continuity checks for the Ws-Web item catalog."""
import json
from pathlib import Path


_RETIREMENT_REGISTRY = Path(__file__).with_name("wm-retired-items.json")


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


def _retirement_records(retired_items=None):
    if retired_items is None:
        try:
            document = json.loads(_RETIREMENT_REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("WM retired-item registry is missing or invalid") from error
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ValueError("WM retired-item registry has an unsupported schema")
        retired_items = document.get("items")

    if not isinstance(retired_items, list):
        raise ValueError("WM retired-item registry items must be a list")

    by_id = {}
    slugs = set()
    for record in retired_items:
        if not isinstance(record, dict):
            raise ValueError("WM retired-item registry contains an invalid record")
        item_id = record.get("id")
        slug = record.get("slug")
        evidence = record.get("evidence") or {}
        catalog = evidence.get("catalog") if isinstance(evidence, dict) else None
        orders = evidence.get("orders") if isinstance(evidence, dict) else None
        if not isinstance(item_id, str) or not item_id.strip() or not isinstance(slug, str) or not slug.strip():
            raise ValueError("WM retired-item registry has a missing stable ID or slug")
        item_id = item_id.strip()
        slug = slug.strip()
        if item_id in by_id:
            raise ValueError("WM retired-item registry has duplicate stable IDs")
        if slug in slugs:
            raise ValueError("WM retired-item registry has duplicate slugs")
        if (
            record.get("confirmed_not_tradable") is not True
            or not isinstance(record.get("checked_at"), str)
            or not record["checked_at"].strip()
            or not isinstance(catalog, dict)
            or catalog.get("http_status") != 200
            or catalog.get("id_present") is not False
            or catalog.get("slug_present") is not False
            or not isinstance(orders, dict)
            or orders.get("http_status") != 404
            or orders.get("error") != "app.item.notFound"
        ):
            raise ValueError("WM retired-item record lacks confirmed catalog and order-route evidence")
        by_id[item_id] = slug
        slugs.add(slug)
    return by_id


def validate_stable_id_continuity(previous_document, current_document, minimum=1500, retired_items=None):
    """Require every prior stable ID unless its exact retirement was reviewed.

    Slugs may change only while the same stable ID remains. Names and slug
    similarity are deliberately not used to infer identity. Retirements are
    explicit records backed by both current WFM item-catalog and order-route
    responses; unrelated missing IDs continue to fail closed.
    """
    previous = _items_by_stable_id(previous_document, "previous", minimum)
    current = _items_by_stable_id(current_document, "current", minimum)
    retired = _retirement_records(retired_items)

    reappeared = set(retired) & set(current)
    if reappeared:
        raise ValueError(
            "retired stable IDs reappeared; review the retirement registry before publishing: %s"
            % ", ".join(sorted(reappeared)[:8])
        )

    lost = set(previous) - set(current)
    mismatched = [
        item_id for item_id in lost
        if item_id in retired and retired[item_id] != previous[item_id]
    ]
    if mismatched:
        raise ValueError(
            "retired-item registry slug does not match the previous slug: %s"
            % ", ".join(sorted(mismatched)[:8])
        )

    unreviewed = lost - set(retired)
    if unreviewed:
        lost_slugs = [previous[item_id] for item_id in sorted(unreviewed)]
        sample = ", ".join(lost_slugs[:8])
        suffix = " ..." if len(unreviewed) > 8 else ""
        raise ValueError(
            "WM item manifest lost %d previously published stable IDs: %s%s"
            % (len(unreviewed), sample, suffix)
        )

    return sum(
        previous[item_id] != current[item_id]
        for item_id in previous.keys() & current.keys()
    )
