from education_resource_mcp.config import Settings


def test_data_dir_owns_job_workspace(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "education-resource-data"
    monkeypatch.setenv("EDUCATION_RESOURCE_MCP_DATA_DIR", str(data_dir))

    settings = Settings.from_env()

    assert settings.data_dir == data_dir.resolve()
    assert settings.jobs_dir == data_dir.resolve() / "jobs"
