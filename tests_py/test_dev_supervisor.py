from scripts.dev import acquire_lock, is_project_listener


def test_launcher_lock_allows_only_one_supervisor(tmp_path):
    path = tmp_path / "dev.lock"
    first = acquire_lock(path)
    second = acquire_lock(path)

    assert first is not None
    assert second is None
    first.close()


def test_listener_validation_is_scoped_to_this_project():
    root = "/Users/tongz/Code/SKHynix"

    assert is_project_listener(
        "backend", f"{root}/.venv/bin/uvicorn backend.main:app --port 8010"
    )
    assert is_project_listener("frontend", f"node {root}/node_modules/.bin/vinext dev")
    assert not is_project_listener("backend", "python -m uvicorn another.main:app --port 8010")
