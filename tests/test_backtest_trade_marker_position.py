from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from ssquant.backtest.backtest_visualization import BacktestVisualizer


def _render_price_chart(monkeypatch, tmp_path, klines, trades):
    captured = {}

    def capture_savefig(self, *args, **kwargs):
        captured["figure"] = self

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture_savefig)
    charts = BacktestVisualizer().visualize_backtest(
        {
            "symbol": "TEST",
            "kline_period": "1d",
            "equity_curve": [],
            "klines": klines,
            "trades": trades,
        },
        output_dir=tmp_path,
    )
    return charts, captured["figure"].axes[0]


def _trade_marker_offsets(ax):
    offsets = []
    for collection in ax.collections:
        if collection.__class__.__name__ == "PathCollection":
            offsets.extend(collection.get_offsets())
    return np.asarray(offsets, dtype=float)


def test_static_chart_places_open_and_close_markers_outside_normal_candle(monkeypatch, tmp_path):
    klines = pd.DataFrame(
        {
            "datetime": ["2026-01-01", "2026-01-02"],
            "open": [100, 101],
            "high": [110, 111],
            "low": [90, 91],
            "close": [105, 102],
        }
    )
    charts, ax = _render_price_chart(
        monkeypatch,
        tmp_path,
        klines,
        [
            {"datetime": "2026-01-01", "price": 100, "action": "开多"},
            {"datetime": "2026-01-02", "price": 102, "action": "平多", "net_profit": 1},
        ],
    )

    assert "price_chart" in charts
    marker_offsets = _trade_marker_offsets(ax)
    assert marker_offsets[marker_offsets[:, 0] == 0, 1].item() < 90
    assert marker_offsets[marker_offsets[:, 0] == 1, 1].item() > 111
    profit_label = next(text for text in ax.texts if text.get_text() == "+1.00")
    assert profit_label.get_verticalalignment() == "bottom"


def test_static_chart_uses_small_local_fallback_for_zero_range_candle(monkeypatch, tmp_path):
    klines = pd.DataFrame(
        {
            "datetime": ["2026-01-01", "2026-01-02"],
            "open": [100, 1000],
            "high": [100, 1010],
            "low": [100, 990],
            "close": [100, 1005],
        }
    )
    _, ax = _render_price_chart(
        monkeypatch,
        tmp_path,
        klines,
        [{"datetime": "2026-01-01", "price": 100, "action": "平多", "net_profit": 1}],
    )

    marker_offsets = _trade_marker_offsets(ax)
    close_y = marker_offsets[marker_offsets[:, 0] == 0, 1].item()
    assert 100 < close_y < 101
