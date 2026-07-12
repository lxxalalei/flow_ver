from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import run_download_plan
from validate_output import validate


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/document.pdf", "/download"}:
            body = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/login":
            body = "<!doctype html><html><head><title>登录后访问</title></head><body><p>请登录后查看内容</p></body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = (
            "<!doctype html><html><head><title>测试文章</title></head><body>"
            "<nav>导航内容</nav><main><h1>测试文章</h1>"
            "<p>这是一段用于验证网页正文归档能力的公开测试内容。</p>"
            "<p>第二段包含<a href='/document.pdf'>资料链接</a>。</p>"
            "</main><script>ignored()</script></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class RunDownloadPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.previous_private_network = os.environ.get("LRS_ALLOW_PRIVATE_NETWORK")
        os.environ["LRS_ALLOW_PRIVATE_NETWORK"] = "1"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls.previous_private_network is None:
            os.environ.pop("LRS_ALLOW_PRIVATE_NETWORK", None)
        else:
            os.environ["LRS_ALLOW_PRIVATE_NETWORK"] = cls.previous_private_network

    def make_session(self, resource: dict[str, object]) -> tuple[Path, dict, dict, tempfile.TemporaryDirectory[str]]:
        temporary = tempfile.TemporaryDirectory()
        session_dir = Path(temporary.name)
        selection = {
            "_meta": {"session_id": "test-session"},
            "data": {"status": "selected", "selected": [{"resource_id": resource["resource_id"]}]},
        }
        stage3 = {
            "_meta": {"session_id": "test-session"},
            "data": {"resources": [resource]},
        }
        (session_dir / "stage4_selection.json").write_text(json.dumps(selection), encoding="utf-8")
        (session_dir / "stage3_search_results.json").write_text(json.dumps(stage3), encoding="utf-8")
        return session_dir, selection, stage3, temporary

    def test_platform_entrypoints_are_owned_by_downloader(self) -> None:
        for platform in ("bilibili", "cctv", "douyin", "nlc", "open163", "smartedu", "yixi", "zhihu"):
            script = run_download_plan.PLATFORM_SCRIPTS[platform]
            self.assertTrue(script.is_file(), platform)
            self.assertIn("resource-downloader", str(script))

    def test_yixi_platform_reports_degraded_level_to_runner(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="Level 2 (公开完整文稿): file.md", stderr="")
        with mock.patch.object(run_download_plan.subprocess, "run", return_value=completed):
            level = run_download_plan.run_platform_download(
                "yixi",
                "https://www.yixi.tv/speech/detail?id=768",
                Path(tempfile.gettempdir()),
                {},
            )
        self.assertEqual(level, "Level 2")

    def test_auto_downloads_confirmed_file_url(self) -> None:
        resource = {
            "resource_id": "generic:test-pdf",
            "platform": "generic",
            "title": "测试 PDF",
            "source_url": f"{self.base_url}/document.pdf",
        }
        session_dir, selection, stage3, temporary = self.make_session(resource)
        self.addCleanup(temporary.cleanup)
        plan = {
            "_meta": {"schema_version": "download-plan/v1", "session_id": "test-session"},
            "data": {"items": [{"resource_id": resource["resource_id"], "expected_formats": ["pdf"]}]},
        }
        output = run_download_plan.run(session_dir, plan)
        self.assertEqual(output["_summary"]["success_count"], 1)
        self.assertTrue(output["data"]["results"][0]["files"][0].endswith("document.pdf"))
        self.assertEqual(validate(session_dir, selection, stage3, output), [])

    def test_auto_archives_regular_webpage_as_level_two(self) -> None:
        resource = {
            "resource_id": "generic:test-article",
            "platform": "generic",
            "title": "测试文章",
            "source_url": f"{self.base_url}/article",
        }
        session_dir, selection, stage3, temporary = self.make_session(resource)
        self.addCleanup(temporary.cleanup)
        plan = {
            "_meta": {"schema_version": "download-plan/v1", "session_id": "test-session"},
            "data": {"items": [{"resource_id": resource["resource_id"]}]},
        }
        output = run_download_plan.run(session_dir, plan)
        result = output["data"]["results"][0]
        self.assertEqual(result["download_status"], "degraded")
        self.assertEqual(result["degraded_level"], "Level 2")
        self.assertEqual({Path(path).name for path in result["files"]}, {"content.md", "metadata.json", "source.html"})
        self.assertEqual(validate(session_dir, selection, stage3, output), [])

    def test_auto_detects_file_without_url_extension(self) -> None:
        resource = {
            "resource_id": "generic:test-no-extension",
            "platform": "generic",
            "title": "无扩展名 PDF",
            "source_url": f"{self.base_url}/download",
        }
        session_dir, selection, stage3, temporary = self.make_session(resource)
        self.addCleanup(temporary.cleanup)
        plan = {
            "_meta": {"schema_version": "download-plan/v1", "session_id": "test-session"},
            "data": {"items": [{"resource_id": resource["resource_id"]}]},
        }
        output = run_download_plan.run(session_dir, plan)
        result = output["data"]["results"][0]
        self.assertEqual(result["download_status"], "success")
        self.assertEqual(Path(result["files"][0]).name, "download.pdf")
        self.assertEqual(validate(session_dir, selection, stage3, output), [])

    def test_login_shell_falls_back_to_metadata(self) -> None:
        resource = {
            "resource_id": "generic:test-login",
            "platform": "generic",
            "title": "登录页面",
            "source_url": f"{self.base_url}/login",
        }
        session_dir, selection, stage3, temporary = self.make_session(resource)
        self.addCleanup(temporary.cleanup)
        plan = {
            "_meta": {"schema_version": "download-plan/v1", "session_id": "test-session"},
            "data": {"items": [{"resource_id": resource["resource_id"]}]},
        }
        output = run_download_plan.run(session_dir, plan)
        result = output["data"]["results"][0]
        self.assertEqual(result["download_status"], "degraded")
        self.assertEqual(result["degraded_level"], "Level 3")
        self.assertEqual({Path(path).name for path in result["files"]}, {"source.md"})
        self.assertEqual(validate(session_dir, selection, stage3, output), [])

    def test_stage_five_revalidation_detects_later_file_corruption(self) -> None:
        resource = {
            "resource_id": "generic:test-corruption",
            "platform": "generic",
            "title": "损坏检测",
            "source_url": f"{self.base_url}/document.pdf",
        }
        session_dir, selection, stage3, temporary = self.make_session(resource)
        self.addCleanup(temporary.cleanup)
        plan = {
            "_meta": {"schema_version": "download-plan/v1", "session_id": "test-session"},
            "data": {"items": [{"resource_id": resource["resource_id"]}]},
        }
        output = run_download_plan.run(session_dir, plan)
        Path(output["data"]["results"][0]["files"][0]).write_text(
            "<html><title>404 Not Found</title><body>Not Found</body></html>",
            encoding="utf-8",
        )
        errors = validate(session_dir, selection, stage3, output)
        self.assertTrue(any("内容校验失败" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
