import logging

import pytest

from infra import configure_logging, get_logger


class TestConfigureLogging:
    def test_sets_info_level_by_default(self):
        configure_logging()
        assert logging.getLogger().level == logging.INFO

    def test_sets_debug_level(self):
        configure_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_sets_warning_level(self):
        configure_logging("WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_sets_error_level(self):
        configure_logging("ERROR")
        assert logging.getLogger().level == logging.ERROR

    def test_invalid_level_falls_back_to_info(self):
        configure_logging("INVALID_LEVEL")
        # getattr returns INFO (20) as fallback
        assert logging.getLogger().level == logging.INFO


class TestGetLogger:
    def test_returns_logger_with_correct_name(self):
        logger = get_logger("my.test.module")
        assert logger.name == "my.test.module"

    def test_returns_logging_logger_instance(self):
        logger = get_logger("another.module")
        assert isinstance(logger, logging.Logger)

    def test_different_names_return_different_loggers(self):
        logger_a = get_logger("module.a")
        logger_b = get_logger("module.b")
        assert logger_a is not logger_b


