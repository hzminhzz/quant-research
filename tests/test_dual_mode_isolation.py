"""Actual Linux namespace tests, not mocked sandbox capability claims."""
from pathlib import Path

import pytest

from src.engine.common import QuantError
from src.engine.feature_compiler import FeatureCompiler
from src.engine.isolation import isolated_features
from tests.dual_mode_fixtures import make_panel
from tests.dual_mode_fixtures import test_spec as spec_fixture


def test_isolated_native_polars_features_equal_parent():
    panel = make_panel(hours=30, dynamic=True)
    compiler = FeatureCompiler(spec_fixture())
    assert isolated_features(panel, compiler).equals(compiler(panel))


def test_isolated_callback_cannot_open_host_holdout(tmp_path):
    sentinel = tmp_path / 'protected-sentinel.txt'
    sentinel.write_text('protected synthetic value')
    forbidden = str(sentinel)
    def reader(frame):
        Path(forbidden).read_text()
        return frame
    with pytest.raises(QuantError, match='FileNotFoundError'):
        isolated_features(make_panel(hours=8), reader)


def test_isolated_callback_cannot_reach_host_network():
    def probe(frame):
        import socket
        connection = socket.socket()
        connection.settimeout(.2)
        try:
            connection.connect(('192.0.2.1', 443))
        finally:
            connection.close()
        return frame
    with pytest.raises(QuantError, match='OSError|TimeoutError'):
        isolated_features(make_panel(hours=8), probe)
