"""Runtime dependency gates for lazy production download paths."""

from __future__ import annotations

import unittest


class RuntimeDependencyTests(unittest.TestCase):
    def test_ximalaya_aes_helpers_are_usable(self) -> None:
        """pycryptodome is lazily imported, so exercise it rather than only importing the adapter."""
        from education_resource_mcp.adapters.ximalaya_download import (
            _aes_decrypt,
            _aes_encrypt,
        )

        plaintext = b"runtime dependency gate"
        self.assertEqual(plaintext, _aes_decrypt(_aes_encrypt(plaintext)))


if __name__ == "__main__":
    unittest.main()
