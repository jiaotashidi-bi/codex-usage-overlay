from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xiexie_usage_overlay.pet_identity import (
    PetIdentityResolver,
    compact_display_name,
    sanitize_display_name,
)


class PetIdentityResolverTests(unittest.TestCase):
    def test_custom_pet_uses_manifest_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text('selected-avatar-id = "custom:xiexie"\n', encoding="utf-8")
            pet_dir = home / "pets" / "xiexie"
            pet_dir.mkdir(parents=True)
            (pet_dir / "pet.json").write_text(
                json.dumps({"id": "xiexie", "displayName": "xiexie"}),
                encoding="utf-8",
            )

            identity = PetIdentityResolver(home).resolve()

        self.assertEqual(identity.avatar_id, "custom:xiexie")
        self.assertEqual(identity.display_name, "xiexie")
        self.assertEqual(identity.source, "custom")

    def test_missing_manifest_falls_back_to_custom_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text('selected-avatar-id = "custom:maomao"\n', encoding="utf-8")

            identity = PetIdentityResolver(home).resolve()

        self.assertEqual(identity.display_name, "maomao")

    def test_unknown_or_missing_selection_uses_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = PetIdentityResolver(Path(directory)).resolve()

        self.assertEqual(identity.display_name, "Codex")
        self.assertEqual(identity.source, "fallback")

    def test_builtin_id_is_humanized_without_manual_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text('selected-avatar-id = "builtin:space-cat"\n', encoding="utf-8")

            identity = PetIdentityResolver(home).resolve()

        self.assertEqual(identity.display_name, "space cat")
        self.assertEqual(identity.source, "builtin")

    def test_path_traversal_pet_id_cannot_escape_pets_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text('selected-avatar-id = "custom:../secret"\n', encoding="utf-8")

            identity = PetIdentityResolver(home).resolve()

        self.assertEqual(identity.display_name, "Codex")


class PetDisplayNameTests(unittest.TestCase):
    def test_control_characters_and_extra_spaces_are_removed(self) -> None:
        self.assertEqual(sanitize_display_name("  xie\n\txie\x00  "), "xie xie")

    def test_long_name_is_compacted_for_header(self) -> None:
        self.assertEqual(compact_display_name("Strawberry"), "Strawbe…")
        self.assertEqual(compact_display_name("谢谢谢谢谢谢"), "谢谢谢…")


if __name__ == "__main__":
    unittest.main()
