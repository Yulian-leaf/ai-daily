import logging

from src.logging_setup import setup_logging


def test_setup_logging_returns_logger():
    """返回 logger，级别为 INFO。"""
    logger = setup_logging()
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.INFO


def test_setup_logging_is_idempotent():
    """多次初始化不重复添加 handler。"""
    a = setup_logging()
    b = setup_logging()
    # No double handlers added.
    assert len(a.handlers) == len(b.handlers)
