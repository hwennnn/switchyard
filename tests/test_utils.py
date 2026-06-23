from __future__ import annotations

import socket
import unittest

from switchyard.utils import port_is_free


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


if __name__ == "__main__":
    unittest.main()
