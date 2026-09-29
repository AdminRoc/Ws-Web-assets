import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))

from wm_item_identity_guard import validate_stable_id_continuity  # noqa: E402


def manifest(items):
    return {"count": len(items), "items": items}


def item(item_id, slug, name=None):
    return {"id": item_id, "slug": slug, "en": name or slug}


class WmItemIdentityGuardTests(unittest.TestCase):
    def test_slug_change_is_allowed_only_with_the_same_stable_id(self):
        previous = manifest([item("stable-item-id", "old_slug", "Synthetic Item")])
        current = manifest([item("stable-item-id", "new_slug", "Synthetic Item")])

        self.assertEqual(validate_stable_id_continuity(previous, current, minimum=1), 1)

    def test_same_name_with_a_different_stable_id_is_not_a_rename(self):
        previous = manifest([item("old-id", "old_slug", "Synthetic Item")])
        current = manifest([item("new-id", "new_slug", "Synthetic Item")])

        with self.assertRaisesRegex(ValueError, "lost 1 previously published stable IDs"):
            validate_stable_id_continuity(previous, current, minimum=1)

    def test_all_65_slug_changes_are_allowed_when_stable_ids_survive(self):
        previous_rows = [item(f"id-{index}", f"old_slug_{index}") for index in range(65)]
        current_rows = [item(f"id-{index}", f"new_slug_{index}") for index in range(65)]

        self.assertEqual(
            validate_stable_id_continuity(
                manifest(previous_rows), manifest(current_rows), minimum=1
            ),
            65,
        )

    def test_equal_row_count_does_not_hide_lost_ids(self):
        previous = manifest([item("id-a", "slug-a"), item("id-b", "slug-b")])
        current = manifest([item("id-a", "slug-a"), item("id-c", "slug-c")])

        with self.assertRaisesRegex(ValueError, "lost 1 previously published stable IDs"):
            validate_stable_id_continuity(previous, current, minimum=1)

    def test_missing_id_in_published_baseline_fails_closed(self):
        previous = manifest([{"slug": "legacy_slug", "en": "Same Name"}])
        current = manifest([item("current-id", "new_slug", "Same Name")])

        with self.assertRaisesRegex(ValueError, "previous WM item manifest has a missing stable ID"):
            validate_stable_id_continuity(previous, current, minimum=1)

    def test_duplicate_ids_and_slugs_fail_closed(self):
        duplicate_id = manifest([item("same-id", "slug-a"), item("same-id", "slug-b")])
        duplicate_slug = manifest([item("id-a", "same-slug"), item("id-b", "same-slug")])
        valid = manifest([item("id-a", "slug-a"), item("id-b", "slug-b")])

        with self.assertRaisesRegex(ValueError, "duplicate stable IDs"):
            validate_stable_id_continuity(duplicate_id, valid, minimum=1)
        with self.assertRaisesRegex(ValueError, "duplicate slugs"):
            validate_stable_id_continuity(valid, duplicate_slug, minimum=1)

    def test_manifest_count_must_match_rows(self):
        malformed = {"count": 2, "items": [item("id", "slug")]}
        valid = manifest([item("id", "slug")])

        with self.assertRaisesRegex(ValueError, "current WM item manifest is incomplete"):
            validate_stable_id_continuity(valid, malformed, minimum=1)


if __name__ == "__main__":
    unittest.main()
