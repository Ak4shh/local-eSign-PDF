from __future__ import annotations

import os
import shutil
import unittest
import uuid

from app.models import PdfRect, SignaturePresetType
from app.signature_presets import SignaturePresetService


class SignaturePresetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        root = os.path.join(os.getcwd(), "tests_tmp")
        os.makedirs(root, exist_ok=True)
        self._temp_dir = os.path.join(root, f"preset_test_{uuid.uuid4().hex}")
        os.makedirs(self._temp_dir, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self._temp_dir, ignore_errors=True))
        self.service = SignaturePresetService(storage_dir=self._temp_dir)

    def _write_image(self, path: str) -> None:
        bmp_bytes = (
            b"BM"
            b"\x3a\x00\x00\x00"
            b"\x00\x00"
            b"\x00\x00"
            b"\x36\x00\x00\x00"
            b"\x28\x00\x00\x00"
            b"\x02\x00\x00\x00"
            b"\x01\x00\x00\x00"
            b"\x01\x00"
            b"\x18\x00"
            b"\x00\x00\x00\x00"
            b"\x04\x00\x00\x00"
            b"\x13\x0b\x00\x00"
            b"\x13\x0b\x00\x00"
            b"\x00\x00\x00\x00"
            b"\x00\x00\x00\x00"
            b"\x00\x00\xff"
            b"\x00\xff\x00"
            b"\x00\x00"
        )
        with open(path, "wb") as handle:
            handle.write(bmp_bytes)

    def test_typed_preset_round_trips_and_builds_overlay(self) -> None:
        self.service.save_typed_preset(
            name="Primary Signature",
            text="Akash Patel",
            font_name="Allura",
            color="blue",
        )

        reloaded = SignaturePresetService(storage_dir=self._temp_dir)
        presets = reloaded.presets()
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0].name, "Primary Signature")
        self.assertEqual(presets[0].preset_type, SignaturePresetType.typed)

        overlay = reloaded.create_overlay(
            presets[0],
            page_index=2,
            rect_pdf=PdfRect(10, 20, 140, 48),
        )
        self.assertEqual(overlay.page_index, 2)
        self.assertEqual(overlay.type.value, "typed_signature")
        self.assertEqual(overlay.text, "Akash Patel")
        self.assertEqual(overlay.font_name, "Allura")
        self.assertEqual(overlay.color, "blue")

    def test_image_preset_round_trips_after_source_file_is_removed(self) -> None:
        source_path = os.path.join(self._temp_dir, "sig.bmp")
        self._write_image(source_path)

        preset = self.service.save_image_preset(
            name="Scanned Signature",
            source_image_path=source_path,
        )
        self.assertTrue(os.path.isfile(preset.resolved_image_path or ""))

        os.remove(source_path)

        reloaded = SignaturePresetService(storage_dir=self._temp_dir)
        presets = reloaded.presets()
        self.assertEqual(len(presets), 1)
        self.assertTrue(presets[0].is_available)
        self.assertTrue(os.path.isfile(presets[0].resolved_image_path or ""))

        overlay = reloaded.create_overlay(
            presets[0],
            page_index=0,
            rect_pdf=PdfRect(0, 0, 120, 40),
        )
        self.assertEqual(overlay.image_path, presets[0].resolved_image_path)

    def test_rename_and_delete_update_manifest(self) -> None:
        preset = self.service.save_typed_preset(
            name="Initial Name",
            text="Akash Patel",
            font_name="Allura",
            color="black",
        )

        self.service.rename_preset(preset.id, "Updated Name")
        self.assertEqual(self.service.get_preset(preset.id).name, "Updated Name")

        self.service.delete_preset(preset.id)
        self.assertEqual(self.service.presets(), [])

        reloaded = SignaturePresetService(storage_dir=self._temp_dir)
        self.assertEqual(reloaded.presets(), [])

    def test_missing_image_asset_marks_preset_unavailable_without_crashing(self) -> None:
        source_path = os.path.join(self._temp_dir, "sig.bmp")
        self._write_image(source_path)
        preset = self.service.save_image_preset(
            name="Image Preset",
            source_image_path=source_path,
        )

        os.remove(preset.resolved_image_path or "")

        reloaded = SignaturePresetService(storage_dir=self._temp_dir)
        self.assertEqual(len(reloaded.presets()), 1)
        loaded = reloaded.presets()[0]
        self.assertFalse(loaded.is_available)
        with self.assertRaises(ValueError):
            reloaded.create_overlay(loaded, page_index=0, rect_pdf=PdfRect(0, 0, 10, 10))

    def test_corrupt_manifest_is_ignored_gracefully(self) -> None:
        manifest_path = os.path.join(self._temp_dir, "manifest.json")
        os.makedirs(self._temp_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json")

        reloaded = SignaturePresetService(storage_dir=self._temp_dir)
        self.assertEqual(reloaded.presets(), [])
        self.assertTrue(reloaded.load_warnings)


if __name__ == "__main__":
    unittest.main()
