"""Tests for live K-line subscription routing and history refresh."""

import json
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.live_trading_adapter import (
    LiveDataSource,
    LiveTradingAdapter,
    _resolve_ws_subscription_symbol,
)
from ssquant.data.ws_kline_client import WSKlineClient


class _FakeWebSocket:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(json.loads(message))


class WSKlineHistoryRefreshTests(unittest.TestCase):
    def setUp(self):
        self.client = WSKlineClient()
        self.client._connected = True
        self.client._ws = _FakeWebSocket()
        self.client.subscribe_kline('rb777', '1M', preload=100)
        self.client._ws.messages.clear()

    def test_refresh_reuses_active_subscription_without_duplicating_it(self):
        result = self.client.refresh_history('RB777', '1m', preload=500)

        self.assertTrue(result)
        self.assertEqual(len(self.client._active_subscriptions), 1)
        self.assertEqual(
            self.client._ws.messages,
            [
                {
                    'action': 'subscribe_kline',
                    'symbol': 'rb777',
                    'period': '1M',
                    'preload': 500,
                }
            ],
        )

    def test_refresh_fails_cleanly_while_disconnected(self):
        self.client._connected = False

        result = self.client.refresh_history('rb777', '1M')

        self.assertFalse(result)
        self.assertEqual(self.client._ws.messages, [])


class LiveDataRefreshRoutingTests(unittest.TestCase):
    def test_history_symbol_overrides_the_trading_contract(self):
        data_source = SimpleNamespace(
            symbol='rb2701',
            config={'history_symbol': ' RB777 '},
        )

        self.assertEqual(
            _resolve_ws_subscription_symbol(data_source),
            'rb777',
        )

    def test_trading_contract_defaults_to_main_continuous_history(self):
        data_source = SimpleNamespace(symbol='rb2701', config={})

        self.assertEqual(
            _resolve_ws_subscription_symbol(data_source),
            'rb888',
        )

    def test_adapter_refreshes_the_selected_subscription(self):
        calls = []
        client = SimpleNamespace(
            refresh_history=lambda **kwargs: calls.append(kwargs) or True
        )
        adapter = LiveTradingAdapter.__new__(LiveTradingAdapter)
        adapter._kline_source = 'data_server'
        adapter.ws_kline_client = client
        adapter.multi_data_source = SimpleNamespace(
            data_sources=[
                SimpleNamespace(
                    symbol='rb2701',
                    config={'history_symbol': 'rb777'},
                    kline_source='data_server',
                    kline_period='1min',
                )
            ]
        )

        result = adapter.refresh_kline_history(index=0, preload=500)

        self.assertTrue(result)
        self.assertEqual(
            calls,
            [{'symbol': 'rb777', 'period': '1M', 'preload': 500}],
        )


class LiveHistoryMergeTests(unittest.TestCase):
    def test_history_gap_fill_preserves_bounded_deque(self):
        source = LiveDataSource(
            'rb2701',
            {
                'kline_source': 'data_server',
                'kline_period': '1min',
                'lookback_bars': 100,
            },
        )
        with patch('builtins.print'):
            source.on_ws_history(
                [
                    {'datetime': '2026-08-27 14:00:00', 'close': 1},
                    {'datetime': '2026-08-27 14:02:00', 'close': 3},
                ]
            )

            source.on_ws_history(
                [
                    {'datetime': '2026-08-27 14:00:00', 'close': 1},
                    {'datetime': '2026-08-27 14:01:00', 'close': 2},
                    {'datetime': '2026-08-27 14:02:00', 'close': 3},
                ]
            )

        self.assertIsInstance(source.klines, deque)
        self.assertEqual(source.klines.maxlen, 100)
        self.assertEqual(
            [str(kline['datetime']) for kline in source.klines],
            [
                '2026-08-27 14:00:00',
                '2026-08-27 14:01:00',
                '2026-08-27 14:02:00',
            ],
        )

    def test_history_refresh_keeps_a_newer_realtime_bar(self):
        source = LiveDataSource(
            'rb2701',
            {
                'kline_source': 'data_server',
                'kline_period': '1min',
                'lookback_bars': 100,
            },
        )
        source.on_ws_kline(
            {'datetime': '2026-08-27 14:01:00', 'close': 2}
        )
        source.on_ws_kline(
            {'datetime': '2026-08-27 14:02:00', 'close': 3}
        )

        with patch('builtins.print'):
            source.on_ws_history(
                [
                    {'datetime': '2026-08-27 14:00:00', 'close': 1},
                    {'datetime': '2026-08-27 14:01:00', 'close': 2},
                ]
            )

        self.assertEqual(
            str(source.klines[-1]['datetime']),
            '2026-08-27 14:02:00',
        )


class StrategyAPIKlineRefreshTests(unittest.TestCase):
    def test_strategy_api_delegates_refresh_request(self):
        calls = []
        api = StrategyAPI(
            {
                'data': [SimpleNamespace()],
                'log': lambda _message: None,
                'kline_history_refresher': (
                    lambda **kwargs: calls.append(kwargs) or True
                ),
            }
        )

        result = api.refresh_klines(index=0, preload=500)

        self.assertTrue(result)
        self.assertEqual(calls, [{'index': 0, 'preload': 500}])

    def test_strategy_api_reports_unsupported_mode(self):
        logs = []
        api = StrategyAPI(
            {
                'data': [SimpleNamespace()],
                'log': logs.append,
            }
        )

        result = api.refresh_klines()

        self.assertFalse(result)
        self.assertEqual(
            logs,
            ['[K线刷新] 当前运行模式不支持主动刷新历史K线'],
        )


if __name__ == '__main__':
    unittest.main()
