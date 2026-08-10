import asyncio
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.v1.routes_files import MAX_UPLOAD_BYTES, upload_file
from app.services import storage


class StoragePolicyTests(unittest.TestCase):
    def test_default_policy_is_local(self):
        self.assertEqual(storage.STORAGE_BACKEND, "local")

    def test_explicit_local_backend_ignores_present_spaces_credentials(self):
        with patch.multiple(
            storage,
            STORAGE_BACKEND="local",
            SPACES_KEY="production-key",
            SPACES_SECRET="production-secret",
            SPACES_BUCKET="production-bucket",
        ):
            self.assertFalse(storage.spaces_enabled())

    def test_explicit_spaces_requires_complete_configuration(self):
        with patch.multiple(
            storage, STORAGE_BACKEND="spaces", SPACES_KEY="", SPACES_SECRET="", SPACES_BUCKET=""
        ):
            with self.assertRaises(RuntimeError):
                storage.spaces_enabled()


class FileUploadTests(unittest.TestCase):
    def run_upload(self, file):
        return asyncio.get_event_loop().run_until_complete(
            upload_file(file=file, current_user=SimpleNamespace(id=42, role="agent"))
        )

    def test_upload_is_persisted_and_returns_reference(self):
        file = UploadFile(filename="safety report.pdf", file=io.BytesIO(b"%PDF-test"), headers=Headers({"content-type": "application/pdf"}))
        with patch("app.api.v1.routes_files.save_fileobj", return_value="/uploads/general/42/file.pdf") as save:
            result = self.run_upload(file)
        self.assertEqual(result["url"], "/uploads/general/42/file.pdf")
        self.assertEqual(result["size"], 9)
        self.assertIn("general/42/", save.call_args.args[1])

    def test_unsupported_content_type_is_rejected(self):
        file = UploadFile(filename="script.html", file=io.BytesIO(b"<script>"), headers=Headers({"content-type": "text/html"}))
        with self.assertRaises(HTTPException) as error:
            self.run_upload(file)
        self.assertEqual(error.exception.status_code, 415)

    def test_oversize_upload_is_rejected(self):
        file = UploadFile(filename="huge.pdf", file=io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1)), headers=Headers({"content-type": "application/pdf"}))
        with self.assertRaises(HTTPException) as error:
            self.run_upload(file)
        self.assertEqual(error.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
