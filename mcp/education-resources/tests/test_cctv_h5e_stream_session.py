from __future__ import annotations

from pathlib import Path
from unittest import mock

from education_resource_mcp.adapters import cctv_download, cctv_h5e


_GUID = "0123456789abcdef0123456789abcdef"


def test_native_h5e_decrypts_joined_stream_once(tmp_path: Path) -> None:
    """H5E mode state belongs to the ordered TS stream, not each HLS segment."""

    resource = {
        "platform": "cctv",
        "title": "old video",
        "source_url": "https://tv.cctv.com/example.shtml",
        "metadata": {"platform_signals": {"guid": _GUID}},
    }
    segment_data = {
        "https://cdn.example/a.ts": b"segment-A",
        "https://cdn.example/b.ts": b"segment-B",
        "https://cdn.example/c.ts": b"segment-C",
    }
    seen_decrypt_inputs: list[bytes] = []
    seen_remux_inputs: list[bytes] = []

    def fake_fetch(url: str, *, timeout: float, cancel_event=None) -> bytes | None:
        return segment_data.get(url)

    def fake_decrypt(data: bytes, vpid: int = 0x100) -> tuple[bytes, int]:
        seen_decrypt_inputs.append(data)
        return b"P" * len(data), 7

    def fake_remux(source_ts, destination_mp4, *, timeout, cancel_event=None):
        seen_remux_inputs.append(Path(source_ts).read_bytes())
        Path(destination_mp4).write_bytes(b"mp4")

    with mock.patch.object(
        cctv_download,
        "_fetch_media_m3u8",
        return_value=("https://cdn.example/2000.m3u8", ["a.ts", "b.ts", "c.ts"]),
    ), mock.patch.object(cctv_download, "_http_fetch_bytes", fake_fetch), mock.patch.object(
        cctv_h5e, "decrypt_ts", fake_decrypt
    ), mock.patch.object(cctv_download, "_remux_to_mp4", fake_remux):
        result = cctv_download.download_h5e_native(
            resource,
            _GUID,
            "old-video",
            tmp_path,
            timeout=5,
            h5e_url="https://cdn.example/master.m3u8",
        )

    joined = b"segment-Asegment-Bsegment-C"
    assert seen_decrypt_inputs == [joined]
    assert seen_remux_inputs == [b"P" * len(joined)]
    assert result.read_bytes() == b"mp4"


def test_native_h5e_rejects_zero_nal_decrypt(tmp_path: Path) -> None:
    resource = {
        "platform": "cctv",
        "title": "old video",
        "source_url": "https://tv.cctv.com/example.shtml",
        "metadata": {"platform_signals": {"guid": _GUID}},
    }

    with mock.patch.object(
        cctv_download,
        "_fetch_media_m3u8",
        return_value=("https://cdn.example/2000.m3u8", ["a.ts"]),
    ), mock.patch.object(
        cctv_download, "_http_fetch_bytes", return_value=b"encrypted"
    ), mock.patch.object(
        cctv_h5e, "decrypt_ts", return_value=(b"encrypted", 0)
    ):
        try:
            cctv_download.download_h5e_native(
                resource,
                _GUID,
                "old-video",
                tmp_path,
                timeout=5,
                h5e_url="https://cdn.example/master.m3u8",
            )
        except Exception as exc:
            assert getattr(exc, "code", None) == "DOWNLOAD_FAILED"
        else:
            raise AssertionError("zero-NAL H5E decrypt must fail")
