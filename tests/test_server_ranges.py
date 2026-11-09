"""Range-serving regressions for normal browser connection cancellation."""
from __future__ import annotations

import io
import sys
import unittest
from email.message import Message
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import ClipScribeHandler


class ResettingOutput:
    def write(self, _chunk: bytes) -> None:
        raise ConnectionResetError(104, "Connection reset by peer")


class RangeCancellationTests(unittest.TestCase):
    def test_requested_range_bytes_are_actually_written(self) -> None:
        handler = object.__new__(ClipScribeHandler)
        handler._range_length = 8
        output = io.BytesIO()

        handler.copyfile(io.BytesIO(b"12345678EXTRA"), output)

        self.assertEqual(output.getvalue(), b"12345678")

    def test_browser_cancelling_range_does_not_escape_as_server_error(self) -> None:
        handler = object.__new__(ClipScribeHandler)
        handler._range_length = 8

        self.assertIsNone(handler.copyfile(io.BytesIO(b"12345678"), ResettingOutput()))

    def test_multipart_upload_is_spooled_to_disk(self) -> None:
        boundary = "clipscribe-test-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nMemory test\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sample.webm\"\r\n"
            "Content-Type: video/webm\r\n\r\n"
        ).encode() + b"video-bytes" + f"\r\n--{boundary}--\r\n".encode()
        handler = object.__new__(ClipScribeHandler)
        handler.rfile = io.BytesIO(body)
        handler.headers = Message()
        handler.headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        handler.headers["Content-Length"] = str(len(body))

        fields, upload = handler.read_request_data()
        self.assertEqual(fields["title"], "Memory test")
        self.assertIsNotNone(upload)
        assert upload is not None
        try:
            self.assertEqual(upload[0], "sample.webm")
            self.assertEqual(upload[1].read_bytes(), b"video-bytes")
        finally:
            upload[1].unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
