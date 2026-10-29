import logging

import pytest


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    """Keep tests that call setup_logger (e.g. via main()) out of the real logs/."""
    monkeypatch.setattr('trader.logger.log_dir', tmp_path / 'logs')
    names = ('trader', 'trader.decisions')
    before = {n: list(logging.getLogger(n).handlers) for n in names}
    yield
    for n in names:
        logger = logging.getLogger(n)
        for handler in list(logger.handlers):
            if handler not in before[n]:
                logger.removeHandler(handler)
                handler.close()
