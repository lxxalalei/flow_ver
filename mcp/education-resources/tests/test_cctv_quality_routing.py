from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from education_resource_mcp.adapters import cctv_download
from education_resource_mcp.adapters.cctv_download import CctvVideoDownloader
from education_resource_mcp.errors import DomainError

_GUID = "0123456789abcdef0123456789abcdef"
_CLEAR = "https://clear.example/master.m3u8"
_H5E = "https://h5e.example/master.m3u8"


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        download_timeout_seconds=10,
        jobs_dir=tmp_path / "jobs",
    )


def _resource() -> dict:
    return {
        "platform": "cctv",
        "title": "最高画质测试",
        "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
        "metadata": {"platform_signals": {"guid": _GUID}},
    }


def _downloader(tmp_path: Path) -> CctvVideoDownloader:
    return CctvVideoDownloader(
        None,
        _settings(tmp_path),
        video_info_func=lambda guid, *, timeout: {
            "hls_url": _CLEAR,
            "h5e_url": _H5E,
        },
        health_checker=lambda path: 0,
    )


def _write_mp4(title: str, job_dir: Path, payload: bytes) -> Path:
    target = job_dir / f"{title}.mp4"
    target.write_bytes(payload)
    return target


def test_clear_wins_when_clear_quality_is_higher(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path)

    def probe(url: str, **kwargs):
        return (1920 * 1080, 4_000_000) if url == _CLEAR else (1280 * 720, 2_000_000)

    with mock.patch.object(cctv_download, "_probe_stream_quality", probe), \
            mock.patch.object(
                cctv_download,
                "download_stream_native",
                side_effect=lambda url, title, job_dir, **kwargs: _write_mp4(
                    title, job_dir, b"clear"
                ),
            ) as clear_download, \
            mock.patch.object(cctv_download, "download_h5e_native") as h5e_download:
        result = downloader.download(_resource(), "clear-high", "direct", threading.Event())

    assert result.metadata["stream_type"] == "clear"
    clear_download.assert_called_once()
    h5e_download.assert_not_called()


def test_h5e_wins_when_h5e_quality_is_higher(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path)

    def probe(url: str, **kwargs):
        return (1280 * 720, 2_000_000) if url == _CLEAR else (1920 * 1080, 4_000_000)

    with mock.patch.object(cctv_download, "_probe_stream_quality", probe), \
            mock.patch.object(cctv_download, "download_stream_native") as clear_download, \
            mock.patch.object(
                cctv_download,
                "download_h5e_native",
                side_effect=lambda resource, guid, title, job_dir, **kwargs: _write_mp4(
                    title, job_dir, b"h5e"
                ),
            ) as h5e_download:
        result = downloader.download(_resource(), "h5e-high", "direct", threading.Event())

    assert result.metadata["stream_type"] == "h5e"
    h5e_download.assert_called_once()
    clear_download.assert_not_called()


def test_equal_quality_prefers_clear(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path)

    with mock.patch.object(
        cctv_download, "_probe_stream_quality", return_value=(1920 * 1080, 4_000_000)
    ), mock.patch.object(
        cctv_download,
        "download_stream_native",
        side_effect=lambda url, title, job_dir, **kwargs: _write_mp4(
            title, job_dir, b"clear"
        ),
    ) as clear_download, mock.patch.object(
        cctv_download, "download_h5e_native"
    ) as h5e_download:
        result = downloader.download(_resource(), "equal", "direct", threading.Event())

    assert result.metadata["stream_type"] == "clear"
    clear_download.assert_called_once()
    h5e_download.assert_not_called()


def test_highest_clear_failure_does_not_silently_downgrade(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path)

    def probe(url: str, **kwargs):
        return (1920 * 1080, 4_000_000) if url == _CLEAR else (1280 * 720, 2_000_000)

    with mock.patch.object(cctv_download, "_probe_stream_quality", probe), \
            mock.patch.object(
                cctv_download,
                "download_stream_native",
                side_effect=DomainError("DOWNLOAD_FAILED", "clear 下载失败"),
            ), \
            mock.patch.object(cctv_download, "download_wasm") as wasm_download:
        with pytest.raises(DomainError) as exc_info:
            downloader.download(_resource(), "no-downgrade", "direct", threading.Event())

    assert exc_info.value.code == "DOWNLOAD_FAILED"
    assert "不自动改下更低画质" in exc_info.value.message
    wasm_download.assert_not_called()
