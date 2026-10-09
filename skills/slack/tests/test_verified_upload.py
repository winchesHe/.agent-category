from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk.cmd_files_upload import (  # noqa: E402
    MAX_VERIFIED_FILE_BYTES,
    _prepare_verified_payloads,
    _read_verified_payload,
    _resolve_path,
)
from sk.errors import InvalidArgument  # noqa: E402
from sk.write_client import SlackWriteClient  # noqa: E402


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b""


class VerifiedUploadTest(unittest.TestCase):
    def test_hash_mismatch_fails_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.png"
            path.write_bytes(b"reviewed")
            with self.assertRaisesRegex(InvalidArgument, "SHA-256 mismatch"):
                _read_verified_payload(path, "0" * 64)

    def test_verified_buffer_is_the_exact_upload_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.png"
            reviewed = b"reviewed-bytes"
            path.write_bytes(reviewed)
            expected = hashlib.sha256(reviewed).hexdigest()
            payload = _read_verified_payload(path, expected)

            def fake_urlopen(request, **_kwargs):
                path.write_bytes(b"replaced-after-verification")
                self.assertEqual(request.data, reviewed)
                return _Response()

            client = SlackWriteClient("test-token", max_retries=1)
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                client.put_bytes(
                    "https://upload.example/presigned",
                    path,
                    verified_bytes=payload,
                )

    def test_verified_mode_rejects_files_over_25_mib(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.png"
            path.write_bytes(b"x")
            with path.open("r+b") as file_obj:
                file_obj.truncate(25 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(InvalidArgument, "limited to 25 MiB"):
                _read_verified_payload(path, "0" * 64)

    def test_verified_mode_bounds_file_count_and_total_buffer(self):
        paths = [Path(f"file-{index}.png") for index in range(21)]
        hashes = ["0" * 64] * len(paths)
        with self.assertRaisesRegex(InvalidArgument, "at most 20 files"):
            _prepare_verified_payloads(paths, hashes)

        payload = b"x" * MAX_VERIFIED_FILE_BYTES
        with patch(
            "sk.cmd_files_upload._read_verified_payload",
            return_value=payload,
        ):
            with self.assertRaisesRegex(InvalidArgument, "100 MiB total"):
                _prepare_verified_payloads(paths[:5], hashes[:5])

    def test_verified_mode_rejects_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.fifo"
            os.mkfifo(path)
            probe = """
import sys
sys.path.insert(0, sys.argv[2])
from pathlib import Path
from sk.cmd_files_upload import _read_verified_payload
from sk.errors import InvalidArgument
try:
    _read_verified_payload(Path(sys.argv[1]), "0" * 64)
except InvalidArgument as exc:
    if "not a single-link regular file" not in str(exc):
        raise
else:
    raise SystemExit("FIFO unexpectedly accepted")
"""
            completed = subprocess.run(
                [sys.executable, "-c", probe, str(path), str(SCRIPTS)],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_upload_path_resolution_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.png"
            target.write_bytes(b"png")
            link = Path(directory) / "link.png"
            link.symlink_to(target)
            with self.assertRaisesRegex(InvalidArgument, "symlink is not allowed"):
                _resolve_path(str(link))

    def test_verified_mode_rejects_next_file_before_exceeding_total_buffer(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            hashes = []
            for index, size in enumerate((25, 25, 25, 25, 1)):
                path = Path(directory) / f"file-{index}.bin"
                with path.open("wb") as file_obj:
                    file_obj.truncate(size * 1024 * 1024)
                paths.append(path)
                hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(InvalidArgument, "100 MiB total"):
                _prepare_verified_payloads(paths, hashes)

    def test_small_verified_file_does_not_allocate_25_mib_buffer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.bin"
            payload = b"reviewed"
            path.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            tracemalloc.start()
            try:
                self.assertEqual(_read_verified_payload(path, expected, 16), payload)
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertLess(peak, 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
