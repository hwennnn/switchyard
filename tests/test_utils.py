from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from switchyard.utils import lines_since, port_is_free


class UtilsTests(unittest.TestCase):
    def test_port_probe_sees_ipv6_wildcard_listener(self) -> None:
        if not socket.has_ipv6:
            self.skipTest("IPv6 is unavailable")
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("::", 0))
            listener.listen()
            port = int(listener.getsockname()[1])

            self.assertFalse(port_is_free(port, "127.0.0.1"))

    def test_lines_since_reads_only_appended_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "service.log"
            path.write_text("one\ntwo\n")
            offset = path.stat().st_size

            path.write_text("one\ntwo\nthree\n")
            next_offset, lines = lines_since(path, offset)

            self.assertEqual(lines, ["three"])
            self.assertEqual(next_offset, path.stat().st_size)

    def test_lines_since_handles_truncated_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "service.log"
            path.write_text("long before rotate\n")
            offset = path.stat().st_size

            path.write_text("new\n")
            next_offset, lines = lines_since(path, offset)

            self.assertEqual(lines, ["new"])
            self.assertEqual(next_offset, path.stat().st_size)


if __name__ == "__main__":
    unittest.main()
