"""Current-user Windows DPAPI protection for local session records.

The module imports on every platform, but the Windows APIs are loaded lazily so
Linux/macOS packaging and tests do not require pywin32 or other dependencies.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


CRYPTPROTECT_UI_FORBIDDEN = 0x01
_DPAPI_ENTROPY_PREFIX = b"openclaw-session-manager\x00windows-dpapi-v1\x00"


class WindowsDpapiError(RuntimeError):
    """DPAPI is unavailable or rejected a protect/unprotect operation."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    if not data:
        raise WindowsDpapiError("DPAPI 不接受空数据")
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    return blob, buffer


class WindowsDpapiProtector:
    """Encrypt bytes for the current Windows user with DPAPI.

    ``CRYPTPROTECT_LOCAL_MACHINE`` is intentionally not used. A copied record
    therefore cannot be decrypted by another Windows user account or machine.
    """

    format_name = "windows-dpapi-v1"

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsDpapiError("Windows DPAPI 只能在原生 Windows 中使用")
        try:
            win_dll = getattr(ctypes, "WinDLL")
            self._crypt32 = win_dll("crypt32", use_last_error=True)
            self._kernel32 = win_dll("kernel32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise WindowsDpapiError("无法加载 Windows DPAPI") from exc

        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def _last_error(operation: str) -> WindowsDpapiError:
        error_code = ctypes.get_last_error()
        return WindowsDpapiError(f"Windows DPAPI {operation}失败（错误码 {error_code}）")

    def _finish(self, output: _DataBlob) -> bytes:
        try:
            if not output.pbData or output.cbData == 0:
                raise WindowsDpapiError("Windows DPAPI 返回空结果")
            result = ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                failed_handle = self._kernel32.LocalFree(
                    ctypes.cast(output.pbData, ctypes.c_void_p)
                )
                if failed_handle:
                    raise self._last_error("释放输出内存")
        return result

    @staticmethod
    def _entropy(purpose: str) -> bytes:
        if not purpose or len(purpose) > 256:
            raise WindowsDpapiError("DPAPI purpose 非法")
        try:
            return _DPAPI_ENTROPY_PREFIX + purpose.encode("ascii")
        except UnicodeEncodeError as exc:
            raise WindowsDpapiError("DPAPI purpose 必须是 ASCII") from exc

    def protect(self, plaintext: bytes, *, purpose: str) -> bytes:
        source, source_buffer = _input_blob(plaintext)
        entropy, entropy_buffer = _input_blob(self._entropy(purpose))
        output = _DataBlob()
        # Keep both input buffers alive through the native call.
        _ = (source_buffer, entropy_buffer)
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "OpenClaw Session Manager",
            ctypes.byref(entropy),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        ):
            raise self._last_error("加密")
        return self._finish(output)

    def unprotect(self, ciphertext: bytes, *, purpose: str) -> bytes:
        source, source_buffer = _input_blob(ciphertext)
        entropy, entropy_buffer = _input_blob(self._entropy(purpose))
        output = _DataBlob()
        _ = (source_buffer, entropy_buffer)
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        ):
            raise self._last_error("解密")
        return self._finish(output)
