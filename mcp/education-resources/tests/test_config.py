from pathlib import Path

from education_resource_mcp.config import Settings


def test_default_library_dir_is_user_documents(monkeypatch) -> None:
    monkeypatch.delenv("EDUCATION_RESOURCE_MCP_LIBRARY_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.library_dir == (Path.home() / "Documents" / "学习资料库").resolve()


def test_library_dir_env_overrides_default(monkeypatch, tmp_path) -> None:
    custom_library = tmp_path / "custom-library"
    monkeypatch.setenv("EDUCATION_RESOURCE_MCP_LIBRARY_DIR", str(custom_library))

    settings = Settings.from_env()

    assert settings.library_dir == custom_library.resolve()
