import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ssquant.backtest.backtest_visualization import BacktestVisualizer
from ssquant.backtest.html_report import HTMLReportGenerator
from ssquant.backtest.trade_position import (
    format_position,
    resolve_trade_positions,
)
from ssquant.data.data_source import DataSource


class TradePositionTests(unittest.TestCase):
    def test_add_trade_records_authoritative_position_snapshot(self):
        data_source = DataSource('rb888', '1m', slippage_ticks=0)
        trades = [
            ('开多', 2),
            ('开多', 1),
            ('平多', 2),
            ('平多', 1),
            ('开空', 4),
            ('平空', 3),
        ]

        for action, volume in trades:
            data_source.add_trade(action, 3500.0, volume, '')

        self.assertEqual(
            [trade['position_after'] for trade in data_source.trades],
            [2, 3, 1, 0, -4, -1],
        )

    def test_old_trade_records_fall_back_to_sequential_replay(self):
        trades = [
            {'action': '开多', 'volume': 2},
            {'action': '平多', 'volume': 2},
            {'action': '开空', 'volume': 2},
            {'action': '平空', 'volume': 2},
            {'action': '开多', 'volume': 3, 'position_after': 8},
            {'action': '平多', 'volume': 2},
        ]

        self.assertEqual(resolve_trade_positions(trades), [2, 0, -2, 0, 8, 6])

    def test_position_labels_distinguish_long_short_and_flat(self):
        self.assertEqual(format_position(5, compact=True), '多5')
        self.assertEqual(format_position(-3), '空3手')
        self.assertEqual(format_position(0), '空仓')


class PositionMarkerReportTests(unittest.TestCase):
    @staticmethod
    def _market_data():
        index = pd.date_range('2026-08-27 09:00:00', periods=4, freq='min')
        return pd.DataFrame(
            {
                'open': [3500.0, 3501.0, 3502.0, 3503.0],
                'high': [3502.0, 3503.0, 3504.0, 3505.0],
                'low': [3499.0, 3500.0, 3501.0, 3502.0],
                'close': [3501.0, 3502.0, 3503.0, 3504.0],
            },
            index=index,
        )

    def test_interactive_markers_show_final_position_and_merge_reverse_legs(self):
        data = self._market_data()
        trades = [
            {
                'datetime': data.index[0], 'action': '开多', 'price': 3501.0,
                'raw_price': 3501.0, 'volume': 2, 'position_after': 2,
            },
            {
                'datetime': data.index[1], 'action': '平多', 'price': 3502.0,
                'raw_price': 3502.0, 'volume': 2, 'position_after': 0,
            },
            {
                'datetime': data.index[1], 'action': '开空', 'price': 3502.0,
                'raw_price': 3502.0, 'volume': 2, 'position_after': -2,
            },
        ]
        results = {
            'rb888_1m': {
                'symbol': 'rb888', 'kline_period': '1m',
                'data': data, 'trades': trades,
            }
        }

        sources = HTMLReportGenerator()._get_kline_data_sources(results)
        markers = sources[0]['markers']

        self.assertEqual(len(markers), 2)
        self.assertEqual([marker['text'] for marker in markers], ['多2', '空2'])
        self.assertIn('成交后仓位：多2手', markers[0]['tooltip'])
        self.assertIn('平多开空 2手', markers[1]['tooltip'])
        self.assertIn('成交后仓位：空2手', markers[1]['tooltip'])

    def test_static_trade_chart_accepts_old_records_and_writes_image(self):
        data = self._market_data().copy()
        data['datetime'] = data.index
        result = {
            'symbol': 'rb888',
            'kline_period': '1m',
            'klines': data,
            'trades': [
                {
                    'datetime': data.index[0], 'action': '开多',
                    'price': 3501.0, 'volume': 2,
                },
                {
                    'datetime': data.index[2], 'action': '平多',
                    'price': 3503.0, 'volume': 2, 'net_profit': 20.0,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            chart_path = Path(tmp_dir) / 'position_markers.png'
            success = BacktestVisualizer()._generate_price_chart(result, str(chart_path))

            self.assertTrue(success)
            self.assertTrue(chart_path.exists())
            self.assertGreater(chart_path.stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()
