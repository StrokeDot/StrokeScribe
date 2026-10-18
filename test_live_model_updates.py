"""Offline safety and real-inventory regressions for the image model updater."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_engine
import ai_models
import model_updates_live as live


class LiveModelUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = ai_engine.Paths(Path(self.temp.name) / "AI")
        self.file = ai_models.ModelFile(
            "https://huggingface.co/example/model/resolve/main/weights.gguf",
            "diffusion_models", 3)
        self.shared = ai_models.ModelFile(
            "https://huggingface.co/example/model/resolve/main/encoder.bin",
            "text_encoders", 2)
        self.model = ai_models.ImageModel(
            id="test_image", name="Test Image Model", maker="Fixture",
            license="Apache 2.0", license_url="https://example.invalid",
            commercial="testing", needs_acceptance=False,
            tasks=("generate",),
            variants=(ai_models.Variant("small", "Small", 1, self.file),),
            shared=(self.shared,), min_ram_gb=1, good_ram_gb=2, steps=1,
            summary="offline fixture")
        self.hw = ai_models.Hardware("GPU", 16, 64, True)
        self.remote_bytes = b"official-changed-weights"
        self.remote = live.RemoteRevision(
            hashlib.sha256(self.remote_bytes).hexdigest(), len(self.remote_bytes))
        self.old = self.paths.model_path(self.file)
        self.old.parent.mkdir(parents=True, exist_ok=True)
        self.old.write_bytes(b"old")
        enc = self.paths.model_path(self.shared)
        enc.parent.mkdir(parents=True, exist_ok=True)
        enc.write_bytes(b"ok")
        self.registry = patch.object(ai_models, "MODELS", (self.model,))
        self.registry.start()
        self.addCleanup(self.registry.stop)

    def scan(self):
        return live.inspect_models(
            self.paths, self.hw, remote_lookup=lambda file: self.remote)

    def test_installed_model_has_one_card_and_detects_official_difference(self):
        states = self.scan()
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].model_id, "test_image")
        self.assertEqual(states[0].status, "update_available")

    def test_model_without_file_is_not_falsely_marked_installed(self):
        self.old.unlink()
        states = self.scan()
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].status, "not_installed")
        self.assertFalse(states[0].installed)

    def test_verified_update_keeps_previous_model_and_updates_registry_readiness(self):
        state = self.scan()[0]
        def fake_download(url, destination, size, progress=None, cancelled=None, sha256=None):
            self.assertEqual(sha256, self.remote.sha256)
            self.assertEqual(size, self.remote.size)
            Path(destination).write_bytes(self.remote_bytes)
            progress(size, size)
        with patch.object(ai_engine, "download", side_effect=fake_download):
            live.install_verified_revision(
                self.paths, state, fetch=lambda f: self.remote)
        self.assertEqual(self.old.read_bytes(), self.remote_bytes)
        self.assertEqual((self.old.parent / "weights.gguf.previous").read_bytes(), b"old")
        self.assertTrue(self.paths.has_files(self.model.files(self.model.variants[0], self.hw.ram_gb)))
        self.assertEqual(self.scan()[0].status, "up_to_date")

    def test_failed_download_never_touches_current_model(self):
        state = self.scan()[0]
        with patch.object(ai_engine, "download", side_effect=RuntimeError("broken checksum")):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                live.install_verified_revision(
                    self.paths, state, fetch=lambda f: self.remote)
        self.assertEqual(self.old.read_bytes(), b"old")
        self.assertFalse(self.old.with_name(self.old.name + ".previous").exists())

    def test_mismatched_publisher_revision_refuses_update_before_download(self):
        state = self.scan()[0]
        with patch.object(ai_engine, "download") as download:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                live.install_verified_revision(
                    self.paths, state, fetch=lambda f: live.RemoteRevision("a" * 64, 4))
        download.assert_not_called()
        self.assertEqual(self.old.read_bytes(), b"old")

    def test_power_cut_restore_variant_before_inventory_scan(self):
        backup = self.old.with_name(self.old.name + ".previous")
        os.replace(self.old, backup)
        self.assertEqual(self.scan()[0].status, "update_available")
        self.assertEqual(self.old.read_bytes(), b"old")
        self.assertFalse(backup.exists())

    def test_failed_second_rename_restores_previous_weights(self):
        state = self.scan()[0]
        actual_replace = live.os.replace
        def fail_once(src, dst):
            if Path(src).name.endswith(".verified-update") and Path(dst) == self.old:
                raise OSError("simulated cannot commit")
            return actual_replace(src, dst)
        def fake_download(url, destination, size, progress=None, cancelled=None, sha256=None):
            Path(destination).write_bytes(self.remote_bytes)
        with patch.object(ai_engine, "download", side_effect=fake_download), \
             patch.object(live.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "cannot commit"):
                live.install_verified_revision(
                    self.paths, state, fetch=lambda f: self.remote)
        self.assertEqual(self.old.read_bytes(), b"old")
        self.assertFalse(self.old.with_name(self.old.name + ".previous").exists())

    def test_network_unavailable_does_not_invent_an_update(self):
        def offline(f):
            raise OSError("offline")
        states = live.inspect_models(self.paths, self.hw, remote_lookup=offline)
        self.assertEqual(states[0].status, "unverified")
        self.assertIsNone(states[0].remote)

    def test_unverified_model_is_never_updateable(self):
        state = live.ModelState(self.model.id, self.model.name, self.model.maker,
                                "Image generation", "small", "Small", "unverified",
                                "offline", True, None, self.file)
        with self.assertRaisesRegex(RuntimeError, "No verified"):
            live.install_verified_revision(self.paths, state)

    def test_publisher_metadata_requires_sha256_and_expected_size(self):
        class Response:
            headers = {"X-Linked-Etag": '"' + self.remote.sha256 + '"',
                       "X-Linked-Size": str(self.remote.size)}
            def __enter__(self): return self
            def __exit__(self, *exc): return False
        with patch.object(live.urllib.request, "urlopen", return_value=Response()) as get:
            self.assertEqual(live.official_revision(self.file), self.remote)
            self.assertEqual(get.call_args.args[0].get_method(), "HEAD")
        with patch.object(live.urllib.request, "urlopen", return_value=type(
                "Bad", (), {"headers": {"ETag": '"not-a-sha"'}, "__enter__": lambda s: s,
                            "__exit__": lambda s,*a: False})()):
            with self.assertRaises(ValueError):
                live.official_revision(self.file)


if __name__ == "__main__":
    unittest.main(verbosity=2)
