import unittest
from types import SimpleNamespace

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.live_trading_adapter import (
    LiveDataSource,
    LiveTradingAdapter,
)


class _FakeCTPClient:
    def __init__(self):
        self.cancel_calls = []
        self.query_calls = []

    def cancel_order(self, instrument_id, order_sys_id, exchange_id):
        self.cancel_calls.append((instrument_id, order_sys_id, exchange_id))

    def query_orders(self, symbol):
        self.query_calls.append(symbol)


class _FakeLiveDataSource:
    def __init__(self):
        self.cancel_calls = []

    def cancel_order(self, order_sys_id, log_callback=None):
        self.cancel_calls.append(order_sys_id)
        return True


class StrategyAPIOrderManagementTests(unittest.TestCase):
    def _make_api(self, data_source, ctp_client=None):
        return StrategyAPI(
            {
                'data': [data_source],
                'log': lambda _message: None,
                'ctp_client': ctp_client,
            }
        )

    def test_query_orders_delegates_to_ctp_client(self):
        client = _FakeCTPClient()
        api = self._make_api(_FakeLiveDataSource(), client)

        api.query_orders('rb2601')

        self.assertEqual(client.query_calls, ['rb2601'])

    def test_cancel_order_delegates_to_selected_data_source(self):
        data_source = _FakeLiveDataSource()
        api = self._make_api(data_source)

        result = api.cancel_order('ORDER-1')

        self.assertTrue(result)
        self.assertEqual(data_source.cancel_calls, ['ORDER-1'])

    def test_cancel_order_respects_data_source_index(self):
        first = _FakeLiveDataSource()
        second = _FakeLiveDataSource()
        api = StrategyAPI(
            {
                'data': [first, second],
                'log': lambda _message: None,
                'ctp_client': None,
            }
        )

        result = api.cancel_order('ORDER-2', index=1)

        self.assertTrue(result)
        self.assertEqual(first.cancel_calls, [])
        self.assertEqual(second.cancel_calls, ['ORDER-2'])


class LiveDataSourceSingleCancelTests(unittest.TestCase):
    def test_cancel_order_only_submits_the_requested_active_order(self):
        client = _FakeCTPClient()
        data_source = LiveDataSource.__new__(LiveDataSource)
        data_source.ctp_client = client
        data_source.symbol = 'rb2601'
        data_source.pending_orders = {
            'ORDER-1': {
                'OrderSysID': 'ORDER-1',
                'InstrumentID': 'rb2601',
                'ExchangeID': 'SHFE',
                'OrderStatus': '3',
            },
            'ORDER-2': {
                'OrderSysID': 'ORDER-2',
                'InstrumentID': 'rb2601',
                'ExchangeID': 'SHFE',
                'OrderStatus': '3',
            },
        }

        result = data_source.cancel_order(' ORDER-1 ')

        self.assertTrue(result)
        self.assertEqual(
            client.cancel_calls,
            [('rb2601', 'ORDER-1', 'SHFE')],
        )

    def test_cancel_order_rejects_unknown_order(self):
        client = _FakeCTPClient()
        data_source = LiveDataSource.__new__(LiveDataSource)
        data_source.ctp_client = client
        data_source.symbol = 'rb2601'
        data_source.pending_orders = {}

        result = data_source.cancel_order('ORDER-404')

        self.assertFalse(result)
        self.assertEqual(client.cancel_calls, [])


class QueryOrderCallbackTests(unittest.TestCase):
    def setUp(self):
        self.data_source = SimpleNamespace(
            symbol='rb2601',
            pending_orders={},
        )
        self.received = []
        self.completed = []
        self.adapter = LiveTradingAdapter.__new__(LiveTradingAdapter)
        self.adapter.multi_data_source = SimpleNamespace(
            data_sources=[self.data_source]
        )
        self.adapter.on_query_order_callback = self.received.append
        self.adapter.on_query_order_complete_callback = (
            lambda: self.completed.append(True)
        )

    def test_query_order_callback_caches_active_order_and_forwards_it(self):
        order = {
            'InstrumentID': 'rb2601',
            'ExchangeID': 'SHFE',
            'OrderSysID': 'ORDER-1',
            'OrderStatus': '3',
        }

        self.adapter._on_query_order(order)

        self.assertIs(self.data_source.pending_orders['ORDER-1'], order)
        self.assertEqual(self.received, [order])

    def test_query_order_callback_removes_terminal_order(self):
        self.data_source.pending_orders['ORDER-1'] = {
            'OrderSysID': 'ORDER-1',
            'OrderStatus': '3',
        }
        order = {
            'InstrumentID': 'rb2601',
            'ExchangeID': 'SHFE',
            'OrderSysID': 'ORDER-1',
            'OrderStatus': '0',
        }

        self.adapter._on_query_order(order)
        self.adapter._on_query_order_complete()

        self.assertNotIn('ORDER-1', self.data_source.pending_orders)
        self.assertEqual(self.completed, [True])


if __name__ == '__main__':
    unittest.main()
