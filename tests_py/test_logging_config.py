import logging

from backend.logging_config import configure_application_logging


def test_application_error_logger_writes_rotating_file(tmp_path, monkeypatch):
    log_path = tmp_path / "error.log"
    logger_name = "hynix_basis.test_file_logging"
    monkeypatch.setenv("HYNIX_ERROR_LOG", str(log_path))
    monkeypatch.delenv("HYNIX_LOG_MODE", raising=False)

    logger = configure_application_logging(logger_name)
    logger.error("test gateway failure")
    for handler in logger.handlers:
        handler.flush()

    assert "test gateway failure" in log_path.read_text()

    for handler in logger.handlers:
        handler.close()
    logging.getLogger(logger_name).handlers.clear()
