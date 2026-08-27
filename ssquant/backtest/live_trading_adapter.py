#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实盘交易适配器
将CTP实盘交易接口适配为与回测一致的API调用方式
支持SIMNOW模拟和实盘交易
"""

import time
import numpy as np
import pandas as pd
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable, Union, TYPE_CHECKING
from collections import deque
import threading

from ..api.strategy_api import StrategyAPI

if TYPE_CHECKING:
    from ..pyctp.simnow_client import SIMNOWClient
    from ..pyctp.real_trading_client import RealTradingClient


import queue


def _live_ds_matches_instrument_id(ds: Any, instrument_id: str) -> bool:
    """
    报单/撤单回报中的 InstrumentID 与数据源匹配：
    当前主力 ds.symbol，或换月残留持仓对应的旧合约 _old_contract。
    """
    if not instrument_id:
        return False
    ins = instrument_id.upper()
    if ds.symbol.upper() == ins:
        return True
    old = getattr(ds, "_old_contract", None)
    return bool(old and str(old).upper() == ins)


class DataRecorder:
    """数据记录器 - 实盘行情落盘（支持CSV和DB双存储，异步队列写入）"""
    
    # 类级别的共享写入队列和后台线程（所有记录器共用）
    _write_queue = None
    _write_thread = None
    _running = False
    _init_lock = threading.Lock()  # 初始化锁，防止竞态条件
    
    @classmethod
    def _init_write_thread(cls):
        """初始化后台写入线程（只初始化一次，线程安全）"""
        if cls._write_thread is None:
            with cls._init_lock:  # 双重检查锁定
                if cls._write_thread is None:
                    cls._write_queue = queue.Queue()
                    cls._running = True
                    cls._write_thread = threading.Thread(target=cls._write_worker, daemon=True)
                    cls._write_thread.start()
                    print("[数据记录器] 后台写入线程已启动")
    
    @classmethod
    def _write_worker(cls):
        """后台写入工作线程"""
        while cls._running:
            try:
                # 等待队列中的任务，超时1秒
                task = cls._write_queue.get(timeout=1)
                if task is None:  # 退出信号
                    break
                
                task_type, data, params = task
                
                if task_type == 'tick_csv':
                    cls._do_write_csv(data, params['file_path'])
                elif task_type == 'tick_db':
                    cls._do_write_db(data, params['db_path'], params['table_name'])
                elif task_type == 'kline_csv':
                    cls._do_write_csv(data, params['file_path'])
                elif task_type == 'kline_db':
                    cls._do_write_db(data, params['db_path'], params['table_name'], log=True)
                
                cls._write_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[数据记录器] 后台写入错误: {e}")
    
    @classmethod
    def _do_write_csv(cls, data: Dict, file_path: str):
        """实际执行CSV写入"""
        try:
            df = pd.DataFrame([data])
            if os.path.exists(file_path):
                df.to_csv(file_path, mode='a', header=False, index=False)
            else:
                df.to_csv(file_path, index=False)
        except Exception as e:
            print(f"[数据记录器] CSV写入失败: {e}")
    
    @classmethod
    def _do_write_db(cls, data: Dict, db_path: str, table_name: str, log: bool = False):
        """实际执行DB写入（使用快速写入，不做去重检查）"""
        try:
            from ..data.api_data_fetcher import append_kline_fast
            new_count = append_kline_fast(data, db_path, table_name)
            if log and new_count > 0:
                # 提取K线详细信息
                dt = data.get('datetime', '')
                o = data.get('open', 0)
                h = data.get('high', 0)
                l = data.get('low', 0)
                c = data.get('close', 0)
                v = data.get('volume', 0)
                oi = data.get('cumulative_openint', 0) or 0
                oi_change = data.get('openint', 0) or 0
                oi_str = f"+{oi_change:.0f}" if oi_change >= 0 else f"{oi_change:.0f}"
                print(f"[K线写入] {table_name} | {dt} | O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f} V:{v:.0f} OI:{oi:.0f}({oi_str})")
        except Exception as e:
            print(f"[数据记录器] DB写入失败 {table_name}: {e}")
    
    @classmethod
    def stop_write_thread(cls):
        """停止后台写入线程"""
        if cls._write_thread and cls._running:
            cls._running = False
            cls._write_queue.put(None)  # 发送退出信号
            cls._write_thread.join(timeout=5)
            print("[数据记录器] 后台写入线程已停止")
    
    def __init__(self, symbol: str, kline_period: str = "1m",
                 save_path: str = "./live_data",
                 db_path: str = "data_cache/backtest_data.db",
                 save_kline_csv: bool = False,
                 save_kline_db: bool = False,
                 save_tick_csv: bool = False,
                 save_tick_db: bool = False,
                 adjust_type: str = "0"):
        """
        初始化数据记录器
        
        Args:
            symbol: 合约代码（具体合约，如 rb2601）
            kline_period: K线周期（用于DB表名，如 1m, 5m, 1d）
            save_path: CSV保存路径
            db_path: 数据库路径
            save_kline_csv: 是否保存K线到CSV
            save_kline_db: 是否保存K线到数据库
            save_tick_csv: 是否保存TICK到CSV
            save_tick_db: 是否保存TICK到数据库
            adjust_type: 复权类型 ('0'=不复权/raw, '1'=后复权/hfq, '2'=前复权/qfq)
        """
        self.symbol = symbol
        self.kline_period = kline_period
        self.save_path = save_path
        self.db_path = db_path
        self.adjust_type = adjust_type
        
        # 四个独立开关
        self.save_kline_csv = save_kline_csv
        self.save_kline_db = save_kline_db
        self.save_tick_csv = save_tick_csv
        self.save_tick_db = save_tick_db
        
        # 推导主连符号（用于DB存储）
        from ..data.contract_mapper import ContractMapper
        self.continuous_symbol = ContractMapper.get_continuous_symbol(symbol)
        
        # 创建CSV保存目录
        if save_kline_csv or save_tick_csv:
            os.makedirs(save_path, exist_ok=True)
        
        # CSV文件名（K线文件包含周期，如 au2602_1m_kline_20260119.csv）
        date_str = datetime.now().strftime("%Y%m%d")
        self.tick_file = os.path.join(save_path, f"{symbol}_tick_{date_str}.csv")
        self.kline_file = os.path.join(save_path, f"{symbol}_{kline_period}_kline_{date_str}.csv")
        
        # 根据复权类型确定K线表名后缀
        # TICK周期没有复权概念，不需要后缀
        try:
            from ..config.trading_config import ENABLE_REMOTE_ADJUST
        except ImportError:
            ENABLE_REMOTE_ADJUST = True
        
        if not ENABLE_REMOTE_ADJUST and adjust_type != '0':
            print(f"[数据记录器] 本地复权已禁用，adjust_type 已从 '{adjust_type}' 强制改为 '0'")
            adjust_type = '0'
            self.adjust_type = '0'
        
        if kline_period.lower() == 'tick':
            self.kline_suffix = None  # TICK模式不保存K线到DB
        else:
            from ..data.local_adjust import get_adjust_suffix
            self.kline_suffix = get_adjust_suffix(adjust_type)
        
        # 初始化后台写入线程（所有记录器共用）
        if save_kline_csv or save_kline_db or save_tick_csv or save_tick_db:
            DataRecorder._init_write_thread()
        
        # 打印配置信息
        print(f"[数据记录器] 初始化 - {symbol}")
        print(f"  K线保存: CSV={'开' if save_kline_csv else '关'}, DB={'开' if save_kline_db else '关'}")
        print(f"  TICK保存: CSV={'开' if save_tick_csv else '关'}, DB={'开' if save_tick_db else '关'}")
        if save_kline_csv or save_tick_csv:
            print(f"  CSV路径: {save_path}")
        if save_kline_db or save_tick_db:
            print(f"  DB路径: {db_path}")
            if save_kline_db and self.kline_suffix:
                print(f"  K线表名: {self.continuous_symbol}_{kline_period.upper()}_{self.kline_suffix}")
            if save_tick_db:
                print(f"  TICK表名: {self.continuous_symbol}_tick")
    
    def record_tick(self, tick_data: Dict):
        """记录TICK数据 - 放入队列异步保存"""
        if not self.save_tick_csv and not self.save_tick_db:
            return
        
        # 构建datetime字段
        trading_day = tick_data.get('TradingDay', '')
        update_time = tick_data.get('UpdateTime', '')
        millisec = tick_data.get('UpdateMillisec', 0)
        
        datetime_str = ''
        if trading_day and update_time:
            datetime_str = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:]} {update_time}.{millisec:03d}"
        
        # 统一字段顺序：datetime 放在第一位，保持与导入工具一致
        tick_record = {'datetime': datetime_str}
        tick_record.update(tick_data)
        
        # 放入队列异步保存（不阻塞）
        if self.save_tick_csv:
            DataRecorder._write_queue.put(('tick_csv', tick_record.copy(), {'file_path': self.tick_file}))
        
        if self.save_tick_db:
            table_name = f"{self.continuous_symbol}_tick"
            DataRecorder._write_queue.put(('tick_db', tick_record.copy(), {'db_path': self.db_path, 'table_name': table_name}))
    
    def record_kline(self, kline_data: Dict):
        """记录K线数据 - 放入队列异步保存"""
        if not self.save_kline_csv and not self.save_kline_db:
            return
        
        # K线数据字段已经与历史数据格式一致，直接复制
        # 字段: datetime, symbol, open, high, low, close, volume, amount, openint, cumulative_openint
        kline_record = kline_data.copy()
        
        # 放入队列异步保存（不阻塞）
        if self.save_kline_csv:
            DataRecorder._write_queue.put(('kline_csv', kline_record.copy(), {'file_path': self.kline_file}))
        
        if self.save_kline_db and self.kline_suffix:
            # TICK模式下 kline_suffix 为 None，跳过K线DB保存
            # 周期统一用大写（如 1M, 5M），与云端数据格式一致
            table_name = f"{self.continuous_symbol}_{self.kline_period.upper()}_{self.kline_suffix}"
            DataRecorder._write_queue.put(('kline_db', kline_record.copy(), {'db_path': self.db_path, 'table_name': table_name}))
    
    def flush_all(self):
        """等待队列中所有数据写入完成"""
        if DataRecorder._write_queue:
            DataRecorder._write_queue.join()  # 等待队列清空


class LiveDataSource:
    """实盘数据源 - 模拟回测时的DataSource接口"""
    
    def __init__(self, symbol: str, config: Dict):
        """
        初始化实盘数据源
        
        Args:
            symbol: 合约代码
            config: 配置参数
        """
        self.symbol = symbol
        self.config = config
        
        # ========== K线数据源模式 ==========
        # 'local' : 本地CTP Tick聚合K线（默认，原有行为）
        # 'data_server': 由 data_server 远程推送已完成K线（WebSocket）
        self.kline_source = config.get('kline_source', 'local')
        
        # 持仓信息
        self.current_pos = 0  # 当前持仓 (正数多头，负数空头)
        self.today_pos = 0  # 今仓
        self.yd_pos = 0  # 昨仓
        
        # 多空持仓分离（用于需要单独访问多头和空头持仓的场景）
        self.long_pos = 0  # 多头持仓
        self.short_pos = 0  # 空头持仓
        self.long_today = 0  # 多头今仓
        self.short_today = 0  # 空头今仓
        self.long_yd = 0  # 多头昨仓
        self.short_yd = 0  # 空头昨仓
        self.current_price = 0.0
        self.current_datetime = None
        self.current_idx = 0
        
        # K线数据缓存
        # lookback_bars 控制缓存大小，默认1000，设置0或不设置则使用默认值
        cache_maxlen = config.get('lookback_bars', 0) or 1000
        cache_maxlen = max(cache_maxlen, 100)  # 至少100条
        self.klines = deque(maxlen=cache_maxlen)  # 保存最近的K线
        self.kline_count = 0  # K线总数计数器（不受deque长度限制）
        
        # Tick数据缓存
        # 统一使用 lookback_bars 控制缓存大小
        self.ticks = deque(maxlen=cache_maxlen)  # 保存最近的TICK
        
        # K线聚合状态
        self.kline_period = config.get('kline_period', '1min')  # K线周期
        self.current_kline = None  # 当前正在聚合的K线
        self.last_kline_time = None  # 上一根K线的时间
        
        # 成交量计算（用于计算K线成交量增量）
        self.last_tick_volume = 0  # 上一个tick的累计成交量
        self.kline_start_volume = 0  # 当前K线开始时的累计成交量
        
        # 持仓量计算（用于记录K线持仓量变化）
        self.last_tick_open_interest = 0  # 上一个tick的持仓量
        self.kline_start_open_interest = 0  # 当前K线开始时的持仓量
        
        # 交易记录
        self.trades = []
        self.capital = config.get('initial_capital', 100000)
        self.available = self.capital
        
        # 交易参数
        self.commission = config.get('commission', 0.0001)
        self.margin_rate = config.get('margin_rate', 0.1)
        self.contract_multiplier = config.get('contract_multiplier', 10)
        
        # 委托价格偏移设置（跳数）
        self.price_tick = config.get('price_tick', 1.0)  # 最小变动价位
        self.order_offset_ticks = config.get('order_offset_ticks', 5)  # 委托偏移跳数，默认5跳
        
        # 智能算法交易配置
        self.algo_trading = config.get('algo_trading', False)
        self.order_timeout = config.get('order_timeout', 0)
        self.retry_limit = config.get('retry_limit', 0)
        self.retry_offset_ticks = config.get('retry_offset_ticks', 5)
        self.orders_to_resend = {}  # 待重发订单 {OrderSysID: retry_count}
        
        # CTP客户端引用
        self.ctp_client: Optional[Union['SIMNOWClient', 'RealTradingClient']] = None
        
        # 未成交订单跟踪
        self.pending_orders = {}  # {OrderSysID: order_data}
        
        # 历史数据预加载（默认延迟到 _init_data_source 中并行执行）
        # data_server 模式：历史数据通过 WebSocket preload 获取，不走本地预加载
        self._need_preload = config.get('preload_history', False) and self.kline_source != 'data_server'
        self._preload_config = config

        # ====== IndicatorCache v2（实盘 / SIMNOW 流式增量预计算） ======
        # 与 DataSource（回测）IndicatorCache 完全相同的 API 语义：
        #   register_indicator / unregister_indicator / get_indicator / get_indicator_array
        # 区别：
        #   - 回测：set_data() 一次性预计算全量
        #   - 实盘：每根 K 线写入后基于 deque 当前内容全量重算（O(maxlen)，maxlen<=1000，~ms 级）
        # _indicator_registry: name -> {'func': callable, 'window': Optional[int]}
        # _indicator_arrays:   name -> np.ndarray（长度 == len(self.klines)，主循环 O(1) 查表）
        self._indicator_registry: Dict[str, Dict[str, Any]] = {}
        self._indicator_arrays: Dict[str, np.ndarray] = {}
        # OHLCV ndarray 缓存（K 线写入时 invalidate，按需重建；register/重算前确保最新）
        self._ohlcv_cache_dirty: bool = True
        self._cache_close: Optional[np.ndarray] = None
        self._cache_open: Optional[np.ndarray] = None
        self._cache_high: Optional[np.ndarray] = None
        self._cache_low: Optional[np.ndarray] = None
        self._cache_volume: Optional[np.ndarray] = None
    
    def _preload_historical_data(self, config: Dict):
        """预加载历史数据（支持K线和TICK两种模式）"""
        from ..data.historical_preloader import HistoricalDataPreloader
        
        # 获取数据库路径配置
        db_path = config.get('db_path', 'data_cache/backtest_data.db')
        preloader = HistoricalDataPreloader(db_path=db_path)
        
        # TICK周期：预加载历史TICK数据
        if self.kline_period.lower() == 'tick':
            self._preload_historical_tick(config, preloader)
            return
        
        # K线周期：预加载历史K线数据
        lookback_bars = config.get('history_lookback_bars', 100)
        adjust_type = config.get('adjust_type', '0')
        
        try:
            from ..config.trading_config import ENABLE_REMOTE_ADJUST
        except ImportError:
            ENABLE_REMOTE_ADJUST = True
        
        if not ENABLE_REMOTE_ADJUST and adjust_type != '0':
            print(f"[预加载] 本地复权已禁用，adjust_type 已从 '{adjust_type}' 强制改为 '0'")
            adjust_type = '0'
        
        # 用户自定义历史数据符号（如 rb888 主力或 rb777 次主力）
        history_symbol = config.get('history_symbol', None)
        
        print(f"\n[LiveDataSource] 开始预加载历史K线数据...")
        
        historical_df = preloader.preload(
            self.symbol,
            self.kline_period,
            lookback_bars=lookback_bars,
            adjust_type=adjust_type,
            history_symbol=history_symbol,
            kline_source=self.kline_source
        )
        
        if not historical_df.empty:
            # 将历史数据加载到klines队列
            for idx, row in historical_df.iterrows():
                kline = {
                    'datetime': idx,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row.get('volume', 0)),
                }
                self.klines.append(kline)
            
            # 初始化K线计数器
            self.kline_count = len(self.klines)
            self.current_idx = self.kline_count - 1
            
            # 【关键修复】初始化 last_kline_time，使 K线 聚合从最后一根历史 K线 时间继续
            # 这样第一个 TICK 来时，系统会正确判断是否需要创建新 K线
            last_kline = self.klines[-1]
            self.last_kline_time = pd.to_datetime(last_kline['datetime'])
            
            print(f"[LiveDataSource] ✅ 已预加载 {len(self.klines)} 根历史K线")
            print(f"[LiveDataSource] 历史数据范围: {historical_df.index[0]} 至 {historical_df.index[-1]}\n")

            # IndicatorCache v2: 历史数据已就绪，触发已注册指标的初始全量预计算
            self._invalidate_ohlcv_cache()
            self._recompute_all_indicators()
        else:
            print(f"[LiveDataSource] ⚠️ 未加载到历史K线数据\n")
    
    def _preload_historical_tick(self, config: Dict, preloader):
        """预加载历史TICK数据"""
        # 获取TICK数量配置（默认1000条）
        lookback_count = config.get('history_lookback_bars', 1000)
        # 用户自定义历史数据符号（如 au2602，TICK通常使用具体合约）
        history_symbol = config.get('history_symbol', None)
        
        print(f"\n[LiveDataSource] 开始预加载历史TICK数据...")
        
        historical_df = preloader.preload_tick(
            self.symbol,
            lookback_count=lookback_count,
            history_symbol=history_symbol
        )
        
        if not historical_df.empty:
            # 将历史TICK数据加载到ticks队列
            for idx, row in historical_df.iterrows():
                tick_info = row.to_dict()
                tick_info['datetime'] = idx
                self.ticks.append(tick_info)
            
            # 更新当前价格为最后一个TICK的价格
            last_tick = self.ticks[-1]
            if 'LastPrice' in last_tick:
                self.current_price = float(last_tick['LastPrice'])
            self.current_datetime = pd.to_datetime(last_tick['datetime'])
            
            print(f"[LiveDataSource] ✅ 已预加载 {len(self.ticks)} 条历史TICK")
            print(f"[LiveDataSource] 历史TICK范围: {historical_df.index[0]} 至 {historical_df.index[-1]}")
            print(f"[LiveDataSource] 最新价格: {self.current_price}\n")
        else:
            print(f"[LiveDataSource] ⚠️ 未加载到历史TICK数据")
            print(f"[LiveDataSource] 提示: 请确保数据库中存在对应的TICK数据表")
            print(f"[LiveDataSource]       可通过 save_tick_db=True 采集TICK数据\n")
    
    def _check_order_timeout(self):
        """检查订单超时（智能算法交易），节流为每秒最多检查一次"""
        if not self.algo_trading or self.order_timeout <= 0:
            return
        
        current_time = time.time()
        
        # 节流：每秒最多检查一次，避免每个 tick 都遍历 pending_orders
        last_check = getattr(self, '_last_timeout_check', 0)
        if current_time - last_check < 1.0:
            return
        self._last_timeout_check = current_time
        
        # 遍历所有未成交订单
        # 注意：需要拷贝items()，因为循环中可能删除字典元素
        for order_sys_id, order in list(self.pending_orders.items()):
            # 获取订单插入时间
            # 我们需要确保在记录订单时添加了本地时间戳，因为CTP时间可能不同步
            insert_time = order.get('_local_insert_time')
            if not insert_time:
                # 如果没有本地时间戳，尝试解析CTP时间，或者跳过
                # 如果订单是CTP回报中带的，尝试解析InsertTime
                insert_time_str = order.get('InsertTime', '')
                if insert_time_str:
                    try:
                        # CTP返回的时间格式通常是 HH:MM:SS
                        # 我们需要加上当前日期
                        from datetime import datetime
                        now = datetime.now()
                        order_time = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {insert_time_str}", "%Y-%m-%d %H:%M:%S")
                        insert_time = order_time.timestamp()
                        # 更新本地时间戳，避免重复解析
                        order['_local_insert_time'] = insert_time
                    except:
                        pass
            
            if not insert_time:
                continue
                
            if current_time - insert_time > self.order_timeout:
                print(f"[智能追单] 订单超时撤单: {order_sys_id} 已等待{current_time - insert_time:.1f}秒 (阈值:{self.order_timeout}秒)")
                
                # 标记该订单需要重发（勿覆盖「继承」的重试计数，否则第 2 次及以后重发会始终被视为第 1 次）
                if order_sys_id not in self.orders_to_resend:
                    self.orders_to_resend[order_sys_id] = 0
                
                # 撤单回报中 OrderSysID 偶发为空，提前登记 FrontID:SessionID:OrderRef 备用键
                adapter = getattr(self, 'trading_adapter', None)
                if adapter:
                    adapter.register_algo_timeout_resend(self, order, order_sys_id)
                
                # 发送撤单请求
                exchange_id = order.get('ExchangeID', '')
                if not exchange_id:
                    # 撤单必须使用订单上的合约代码（换月平旧时为旧合约，不能用 ds.symbol）
                    from ..pyctp.trader_api import _get_exchange_id
                    inst = order.get("InstrumentID") or self.symbol
                    exchange_id = _get_exchange_id(inst) or "SHFE"
                if self.ctp_client:
                    inst = order.get("InstrumentID") or self.symbol
                    self.ctp_client.cancel_order(inst, order_sys_id, exchange_id)

    def update_tick(self, tick_data: Dict) -> Dict:  # type: ignore
        """更新tick数据并聚合K线
        
        Returns:
            Dict 或 None: 如果生成了新K线，返回刚完成的K线；否则返回None
        """
        # 检查订单超时
        self._check_order_timeout()
        
        self.current_price = tick_data['LastPrice']
        
        # 格式化时间（使用TradingDay业务日期 + UpdateTime最后修改时间）
        # 【关键修复】CTP 的 TradingDay 是交易日而非自然日
        # 夜盘 21:00-02:30 的 TradingDay 是下一个交易日
        # 需要正确处理跨自然日的情况，避免时间"倒退"
        trading_day = tick_data['TradingDay']
        update_time = tick_data['UpdateTime']
        millisec = tick_data['UpdateMillisec']
        
        # 解析 update_time 的小时
        hour = int(update_time.split(':')[0])
        
        # 修正日期：将 CTP 的交易日时间转换为自然日时间
        # CTP 的 TradingDay 是交易日（周五夜盘的 TradingDay 是下周一）
        # 我们需要转换为真实的自然日（周五夜盘应该是周五的日期）
        # 
        # 关键认识：
        #   - 09:00-17:00 日盘：TradingDay 等于自然日
        #   - 21:00-23:59 夜盘前半段：TradingDay 是下一个交易日，需要反查
        #   - 00:00-02:30 夜盘后半段（凌晨）：TradingDay 已经是当天，直接用系统日期
        # 
        from datetime import datetime as dt
        
        if 9 <= hour < 17:  # 09:00-17:00 日盘时间
            # 日盘时段，TradingDay 就是自然日
            date_str = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:]}"
        elif hour >= 21:  # 21:00-23:59 夜盘前半段
            # 使用交易日历反查上一个交易日（带缓存，避免每个 tick 重复查询）
            cache = getattr(self, '_prev_trading_day_cache', {})
            if trading_day in cache:
                date_str = cache[trading_day]
            else:
                try:
                    from ..data.api_data_fetcher import get_prev_trading_day
                    date_str = get_prev_trading_day(trading_day)
                except Exception:
                    date_str = dt.now().strftime('%Y-%m-%d')
                cache[trading_day] = date_str
                self._prev_trading_day_cache = cache
        else:  # 00:00-08:59 凌晨时段（夜盘后半段 + 早盘前）
            # 凌晨夜盘（00:00-02:30）应该使用当前系统日期
            # 因为这时候已经是新的一天了
            date_str = dt.now().strftime('%Y-%m-%d')
        
        datetime_str = f"{date_str} {update_time}.{millisec:03d}"
        
        # data_server 模式：K线由远程推送，不需要本地聚合
        # 跳过 pd.to_datetime 和 dict.copy（这两个是最耗时的操作）
        # datetime 以字符串形式直接写入原始 tick_data（避免全量拷贝）
        if self.kline_source == 'data_server':
            tick_data['datetime'] = datetime_str
            self.ticks.append(tick_data)
            return None  # type: ignore
        
        tick_datetime = pd.to_datetime(datetime_str)
        
        # data_server 模式已在上方提前返回，此处仅 local 模式
        self.current_datetime = tick_datetime
        
        # 保存完整的CTP原始数据，只添加datetime字段
        tick_info = tick_data.copy()
        tick_info['datetime'] = tick_datetime
        
        self.ticks.append(tick_info)
        
        # 本地模式：聚合K线并返回完成的K线
        return self._aggregate_kline(tick_data)
    
    def get_current_price(self) -> float:
        """获取当前原始价格（用于委托定价/最新行情）。"""
        return self.current_price

    def get_strategy_price(self) -> float:
        """获取策略视角价格，尽量与 get_klines()/get_close() 所见口径一致。"""
        adjust_type = str(self.config.get('adjust_type', '0') or '0')
        if self.kline_source == 'data_server' and adjust_type != '0':
            df = self.get_klines(window=1)
            if not df.empty and 'close' in df.columns:
                price = df.iloc[-1].get('close')
                if pd.notna(price):
                    return float(price)
        return self.current_price

    def get_raw_price(self) -> float:
        """显式返回原始价格，避免与复权后的策略价格混用。"""
        return self.current_price
    
    def get_current_datetime(self):
        """获取当前时间"""
        return self.current_datetime
    
    def get_current_pos(self) -> int:
        """获取当前持仓"""
        return self.current_pos
    
    def _get_kline_timestamp(self, dt: pd.Timestamp) -> pd.Timestamp:
        """根据K线周期获取K线时间戳"""
        import re
        # 解析周期
        period = self.kline_period.lower()
        
        # 匹配分钟周期：1m, 5m, 15m, 30m, 1min, 5min 等
        min_match = re.match(r'^(\d+)(m|min)$', period)
        if min_match:
            minutes = int(min_match.group(1))
            if minutes < 60:
                # 向下取整到对应的分钟
                new_minute = (dt.minute // minutes) * minutes
                return dt.replace(minute=new_minute, second=0, microsecond=0)
            else:
                # ≥60 分钟：用当天总分钟数做整除，支持 65m/80m/120m 等任意周期
                total_minutes = dt.hour * 60 + dt.minute
                period_start = (total_minutes // minutes) * minutes
                new_hour, new_minute = divmod(period_start, 60)
                return dt.replace(hour=new_hour, minute=new_minute, second=0, microsecond=0)
        
        # 匹配小时周期：1h, 2h, 1hour 等
        hour_match = re.match(r'^(\d+)(h|hour)$', period)
        if hour_match:
            hours = int(hour_match.group(1))
            new_hour = (dt.hour // hours) * hours
            return dt.replace(hour=new_hour, minute=0, second=0, microsecond=0)
        
        # 匹配日线：1d, d, day
        # 日线归属规则：夜盘(21:00-23:59)归属当天，凌晨(00:00-02:30)归属前一天
        # 即：一个交易日 = 当天09:00-15:15 + 当天21:00-23:59 + 次日00:00-02:30
        if period in ['1d', 'd', 'day']:
            hour = dt.hour
            if hour < 5:
                # 凌晨夜盘(00:00-02:30)：归属前一自然日（与前晚21:00同属一个交易日）
                prev_day = dt - pd.Timedelta(days=1)
                return prev_day.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                # 日盘(09:00-15:15) + 夜盘(21:00-23:59)：归属当天
                return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 默认1分钟
        return dt.replace(second=0, microsecond=0)
    
    def _aggregate_kline(self, tick_data: Dict) -> Dict:  # type: ignore
        """聚合tick数据为K线 - 计算成交量增量和持仓量变化
        
        Returns:
            Dict 或 None: 如果生成了新K线，返回刚完成的K线；否则返回None
        """
        # 确保时间不为None
        if self.current_datetime is None:
            return None  # type: ignore
        
        # 获取当前tick的累计成交量和瞬时持仓量
        current_volume = tick_data.get('Volume', 0)
        current_open_interest = tick_data.get('OpenInterest', 0)
        
        # 获取K线时间戳
        kline_time = self._get_kline_timestamp(self.current_datetime)
        
        # 【关键修复】处理历史数据预加载后的状态不一致问题
        # 预加载只设置了 last_kline_time，但没有设置 current_kline
        # 这会导致以下场景失败：
        #   1. 同一分钟恢复：kline_time == last_kline_time，进入else但current_kline是None
        #   2. 时间回退：kline_time < last_kline_time（异常数据），同上
        # 解决方案：当检测到状态不一致时（有last_kline_time但无current_kline），
        # 无条件重置 last_kline_time，让系统从第一个实盘tick开始创建新K线
        if self.last_kline_time is not None and self.current_kline is None:
            # 只在第一个实盘tick时触发（之后 current_kline 会被设置）
            # 这确保历史数据的 last_kline_time 不会阻止实盘K线的创建
            self.last_kline_time = None
        
        # 判断是否需要生成新K线
        if self.last_kline_time is None or kline_time > self.last_kline_time:
            # 保存上一根完成的K线
            completed_kline = None
            if self.current_kline is not None:
                completed_kline = self.current_kline.copy()
                self.klines.append(completed_kline)
                # 增加K线计数器（不受deque长度限制）
                self.kline_count += 1
                self.current_idx = self.kline_count - 1
                # IndicatorCache v2: 新 K 线已落定，标记缓存脏 + 重算所有指标
                self._invalidate_ohlcv_cache()
                self._recompute_all_indicators()

            # 创建新K线时，记录起始成交量和持仓量
            self.kline_start_volume = current_volume
            self.kline_start_open_interest = current_open_interest
            
            # 创建新K线（字段名与历史数据保持一致）
            self.current_kline = {
                'datetime': kline_time,
                'symbol': self.symbol,  # 具体合约代码
                'real_symbol': self.symbol,  # 保留实际合约，供本地复权识别换月点
                'open': self.current_price,
                'high': self.current_price,
                'low': self.current_price,
                'close': self.current_price,
                'volume': 0,  # 初始成交量为0，后续累加增量
                'amount': None,  # 成交额（实时数据暂无）
                'openint': 0,  # 持仓量变化（初始为0）
                'cumulative_openint': current_open_interest,  # 累计持仓量
            }
            self.last_kline_time = kline_time
            self.last_tick_volume = current_volume
            self.last_tick_open_interest = current_open_interest
            return completed_kline  # type: ignore
        else:
            # 更新当前K线
            if self.current_kline is not None:
                self.current_kline['high'] = max(self.current_kline['high'], self.current_price)
                self.current_kline['low'] = min(self.current_kline['low'], self.current_price)
                self.current_kline['close'] = self.current_price
                
                # 计算成交量增量（当前累计成交量 - K线开始时的累计成交量）
                volume_delta = current_volume - self.kline_start_volume
                self.current_kline['volume'] = max(0, volume_delta)  # 确保成交量非负
                
                # 更新持仓量（字段名与历史数据保持一致）
                self.current_kline['cumulative_openint'] = current_open_interest
                
                # 计算持仓量变化（当前持仓量 - K线开始时的持仓量）
                openint_change = current_open_interest - self.kline_start_open_interest
                self.current_kline['openint'] = openint_change
                
            self.last_tick_volume = current_volume
            self.last_tick_open_interest = current_open_interest
            return None  # type: ignore
    
    def get_klines(self, window: int = None) -> pd.DataFrame:
        """获取K线数据
        
        Args:
            window: 滑动窗口大小，None或0表示返回所有缓存数据（最多deque maxlen条）
            
        Returns:
            K线数据DataFrame，最多返回window条（从最近往前）
        """
        if not self.klines:
            return pd.DataFrame()
        
        klines_list = list(self.klines)
        df = pd.DataFrame(klines_list)
        
        # data_server 模式统一缓存 raw 数据，对外读取时按 adjust_type 本地复权
        adjust_type = str(self.config.get('adjust_type', '0') or '0')
        if self.kline_source == 'data_server' and adjust_type != '0':
            try:
                from ..config.trading_config import ENABLE_REMOTE_ADJUST
            except ImportError:
                ENABLE_REMOTE_ADJUST = True
            if ENABLE_REMOTE_ADJUST:
                from ..data.local_adjust import apply_local_adjust
                df = apply_local_adjust(df, self.symbol, self.kline_period, adjust_type)
        
        # 如果指定了窗口大小且大于0，只返回最近的window条
        if window is not None and window > 0:
            df = df.iloc[-window:]
        
        return df

    def get_latest_kline_record(self) -> Optional[Dict]:
        """返回最新一根K线，供数据记录器保存。"""
        df = self.get_klines(window=1)
        if df.empty:
            return None
        return df.iloc[-1].to_dict()
    
    def get_close(self) -> pd.Series:
        """获取收盘价序列"""
        df = self.get_klines()
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df['close'])
    
    def get_open(self) -> pd.Series:
        """获取开盘价序列"""
        df = self.get_klines()
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df['open'])
    
    def get_high(self) -> pd.Series:
        """获取最高价序列"""
        df = self.get_klines()
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df['high'])
    
    def get_low(self) -> pd.Series:
        """获取最低价序列"""
        df = self.get_klines()
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df['low'])
    
    def get_volume(self) -> pd.Series:
        """获取成交量序列"""
        df = self.get_klines()
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df['volume'])

    # ============================================================
    # ====== 方式二：NumPy 数组 API（中性能档位，零 Pandas 开销） ======
    # ============================================================
    # 与 DataSource（回测）的 get_xxx_array 行为对齐：
    #   - 直接基于 deque 拷贝出 ndarray（实盘 deque 长度 ≤ maxlen，开销可忽略）
    #   - window=None / 0 时返回全部缓存；window>0 时返回最近 window 根
    # 注意：deque 在另一线程被修改时存在轻微竞争，但实盘 K 线写入与策略主循环串行，
    # 这里走主线程查询路径，无需加锁。
    def _ensure_ohlcv_cache(self):
        """构建 OHLCV ndarray 缓存。每次 K 线写入后置 dirty，按需重建。"""
        if not self._ohlcv_cache_dirty and self._cache_close is not None:
            return
        n = len(self.klines)
        if n == 0:
            self._cache_close = np.empty(0, dtype=np.float64)
            self._cache_open = np.empty(0, dtype=np.float64)
            self._cache_high = np.empty(0, dtype=np.float64)
            self._cache_low = np.empty(0, dtype=np.float64)
            self._cache_volume = np.empty(0, dtype=np.float64)
            self._ohlcv_cache_dirty = False
            return
        # 一次遍历，5 个字段同时填充（避免 5 次 list comprehension）
        close_arr = np.empty(n, dtype=np.float64)
        open_arr = np.empty(n, dtype=np.float64)
        high_arr = np.empty(n, dtype=np.float64)
        low_arr = np.empty(n, dtype=np.float64)
        vol_arr = np.empty(n, dtype=np.float64)
        for i, k in enumerate(self.klines):
            close_arr[i] = k.get('close', np.nan)
            open_arr[i] = k.get('open', np.nan)
            high_arr[i] = k.get('high', np.nan)
            low_arr[i] = k.get('low', np.nan)
            vol_arr[i] = k.get('volume', 0.0)
        self._cache_close = close_arr
        self._cache_open = open_arr
        self._cache_high = high_arr
        self._cache_low = low_arr
        self._cache_volume = vol_arr
        self._ohlcv_cache_dirty = False

    def _invalidate_ohlcv_cache(self):
        """K 线写入入口调用：标记 OHLCV ndarray 缓存失效。"""
        self._ohlcv_cache_dirty = True

    def _slice_array(self, arr: Optional[np.ndarray], window: Optional[int]) -> np.ndarray:
        if arr is None or arr.size == 0:
            return np.empty(0, dtype=np.float64)
        if window is None or window <= 0:
            return arr
        if window >= arr.size:
            return arr
        return arr[-int(window):]

    def get_close_array(self, window: Optional[int] = None) -> np.ndarray:
        """获取收盘价 ndarray（实盘版）。window=None/0 返回全部缓存。"""
        self._ensure_ohlcv_cache()
        return self._slice_array(self._cache_close, window)

    def get_open_array(self, window: Optional[int] = None) -> np.ndarray:
        """获取开盘价 ndarray（实盘版）。"""
        self._ensure_ohlcv_cache()
        return self._slice_array(self._cache_open, window)

    def get_high_array(self, window: Optional[int] = None) -> np.ndarray:
        """获取最高价 ndarray（实盘版）。"""
        self._ensure_ohlcv_cache()
        return self._slice_array(self._cache_high, window)

    def get_low_array(self, window: Optional[int] = None) -> np.ndarray:
        """获取最低价 ndarray（实盘版）。"""
        self._ensure_ohlcv_cache()
        return self._slice_array(self._cache_low, window)

    def get_volume_array(self, window: Optional[int] = None) -> np.ndarray:
        """获取成交量 ndarray（实盘版）。"""
        self._ensure_ohlcv_cache()
        return self._slice_array(self._cache_volume, window)

    # ============================================================
    # ====== 方式一：IndicatorCache v2（实盘 / SIMNOW 增量预计算） ======
    # ============================================================
    # 与 DataSource（回测）IndicatorCache 完全相同的对外 API：
    #   register_indicator(name, func, window=None) -> np.ndarray
    #   unregister_indicator(name) -> bool
    #   get_indicator(name) -> float
    #   get_indicator_array(name, window=None) -> np.ndarray
    # 内部实现差异：
    #   - 回测：set_data() 一次性预计算全量（一次性 O(N)）
    #   - 实盘：每根新 K 线写入入口触发 _recompute_all_indicators()，全量重算 deque 当前内容
    #          （N=len(self.klines) ≤ maxlen ≤ 1000，pandas/numpy 矢量化耗时 < 1ms / 指标）
    # 选择"全量重算 over 增量"的原因：
    #   1. 数值与回测路径逐位等价（用户 func 一份代码，回测+实盘都能跑）
    #   2. 不用处理 EMA 等递归指标的窗口切片初始值问题
    #   3. 不用维护 deque 滚动 ↔ ndarray 滚动的同步逻辑（一次性算）
    #   4. 实盘 1m K 线频率下 CPU 占用 < 0.005%，远低于网络/CTP 报单链路开销
    def register_indicator(self, name: str, func: Callable, window: Optional[int] = None) -> np.ndarray:
        """注册一个自定义指标，引擎在每根新 K 线时自动重算（全量）。

        Args:
            name: 指标名（同一 LiveDataSource 内唯一，重名会覆盖）
            func: 计算函数 func(close, open, high, low, volume) -> np.ndarray
                  必须返回与输入等长的 ndarray，可包含 NaN（前 N 根没法算的位置）
            window: 该指标依赖的最大窗口（仅作元信息，实盘下未直接使用，保留 API 兼容）

        Returns:
            np.ndarray: 当前缓存下预计算好的指标值数组（长度 == len(self.klines)）
        """
        if not callable(func):
            raise TypeError(f"register_indicator: func 必须是 callable，得到 {type(func)}")
        self._indicator_registry[name] = {'func': func, 'window': window}
        return self._recompute_indicator(name)

    def unregister_indicator(self, name: str) -> bool:
        """移除一个已注册的指标，返回是否成功移除。"""
        ok = self._indicator_registry.pop(name, None) is not None
        self._indicator_arrays.pop(name, None)
        return ok

    def _recompute_indicator(self, name: str) -> Optional[np.ndarray]:
        """对单个已注册指标做一次全量预计算，结果写入 _indicator_arrays。"""
        spec = self._indicator_registry.get(name)
        if spec is None:
            return None
        # OHLCV 缓存若已脏，先重建
        self._ensure_ohlcv_cache()
        n = len(self.klines)
        if n == 0:
            self._indicator_arrays[name] = np.full(0, np.nan, dtype=np.float64)
            return self._indicator_arrays[name]

        close = self._cache_close
        open_ = self._cache_open
        high = self._cache_high
        low = self._cache_low
        volume = self._cache_volume

        try:
            arr = spec['func'](close, open_, high, low, volume)
        except Exception as exc:
            raise RuntimeError(
                f"register_indicator: 指标 '{name}' 的计算函数抛错: {exc}"
            ) from exc

        if not isinstance(arr, np.ndarray):
            arr = np.asarray(arr, dtype=np.float64)
        if arr.dtype != np.float64:
            arr = arr.astype(np.float64, copy=False)
        if arr.shape[0] != n:
            raise ValueError(
                f"register_indicator: 指标 '{name}' 返回长度 {arr.shape[0]} != "
                f"K 线缓存长度 {n}，必须返回与输入等长的数组"
            )
        self._indicator_arrays[name] = arr
        return arr

    def _recompute_all_indicators(self):
        """重算所有已注册指标。在每个 K 线写入入口结束时被调用。

        若没有注册任何指标，立即返回（零开销）。
        """
        if not self._indicator_registry:
            return
        # 先把 OHLCV 缓存重建一次，避免每个指标都 dirty-check
        self._invalidate_ohlcv_cache()
        self._ensure_ohlcv_cache()
        for name in list(self._indicator_registry.keys()):
            self._recompute_indicator(name)

    def get_indicator(self, name: str) -> float:
        """获取已注册指标在当前 Bar（最新一根 K 线）的值（标量），O(1)。

        若指标未注册或缓存为空，返回 NaN。
        """
        arr = self._indicator_arrays.get(name)
        if arr is None or arr.size == 0:
            return float('nan')
        return float(arr[-1])

    def get_indicator_array(self, name: str, window: Optional[int] = None) -> np.ndarray:
        """获取已注册指标的最近 window 个值（ndarray，零拷贝视图或子视图）。

        - window=None / 0 时返回全部缓存
        - window>0 时返回 arr[-window:]
        """
        arr = self._indicator_arrays.get(name)
        if arr is None or arr.size == 0:
            return np.empty(0, dtype=np.float64)
        return self._slice_array(arr, window)

    def get_tick(self) -> Optional[Dict]:
        """获取当前最新的tick数据"""
        if self.ticks:
            return dict(self.ticks[-1])
        return None
    
    def get_ticks(self, window: int = None) -> pd.DataFrame:
        """获取最近window条tick数据
        
        Args:
            window: 窗口大小，None表示返回所有缓存数据，0也表示不限制
            
        Returns:
            DataFrame: tick数据
        """
        if not self.ticks:
            return pd.DataFrame()
        
        tick_list = list(self.ticks)
        
        # 如果指定了窗口大小且大于0，只返回最近的window条
        if window is not None and window > 0:
            if len(tick_list) > window:
                tick_list = tick_list[-window:]
        
        return pd.DataFrame(tick_list)
    
    # ========== data_server K线接收方法 ==========
    
    def on_ws_kline(self, kline_data: Dict) -> Optional[Dict]:
        """
        接收 data_server 推送的已完成K线（data_server 模式专用）
        
        Args:
            kline_data: K线数据字典，包含 datetime, open, high, low, close, volume 等
            
        Returns:
            如果是新K线，返回K线数据（触发策略+记录）
            如果是更新已有K线（同一时间戳），返回 None（不触发策略）
        """
        # 转换datetime（如果是字符串）
        dt = kline_data.get('datetime')
        if isinstance(dt, str):
            kline_data['datetime'] = pd.to_datetime(dt)
        
        # 更新当前价格和时间（确保策略能获取到正确的价格）
        # 在 data_server 模式下，WS推送可能早于CTP Tick到达
        # 必须用K线的 close 价格兜底，否则 current_price=0 导致下单价格异常
        close_price = kline_data.get('close')
        if close_price is not None and close_price > 0:
            self.current_price = close_price
        self.current_datetime = kline_data.get('datetime', self.current_datetime)
        
        # 去重：如果最后一根K线时间戳相同，则更新（而非追加）
        # data_server 可能推送正在形成的K线更新，或重连后重叠推送
        if self.klines and kline_data['datetime'] == self.klines[-1].get('datetime'):
            self.klines[-1] = kline_data
            # 更新 last_kline_time
            self.last_kline_time = kline_data.get('datetime')
            return None  # 更新已有K线，不触发策略
        
        # 新K线：追加
        self.klines.append(kline_data)
        self.kline_count += 1
        self.current_idx = self.kline_count - 1
        
        # 更新 last_kline_time（用于状态一致性）
        self.last_kline_time = kline_data.get('datetime')

        # IndicatorCache v2: 新 K 线已追加，重算所有已注册指标
        self._invalidate_ohlcv_cache()
        self._recompute_all_indicators()

        return kline_data
    
    def on_ws_history(self, klines_list: list):
        """
        接收 data_server 预加载的历史K线（data_server 模式专用）
        
        首次连接：直接加载全部历史
        重连：只加载比已有数据更新的K线（避免重叠/倒序）
        
        Args:
            klines_list: K线数据列表（时间正序，从旧到新）
        """
        if not klines_list:
            return
        
        # 转换所有datetime
        for kline in klines_list:
            dt = kline.get('datetime')
            if isinstance(dt, str):
                kline['datetime'] = pd.to_datetime(dt)
        
        if not self.klines:
            # 首次加载：直接全部追加
            for kline in klines_list:
                self.klines.append(kline)
        else:
            # 已有数据：按 datetime 去重合并，历史 K 线（数据库 OHLC 通常更完整）覆盖现有缓存。
            # 同时正确处理三类混合段：
            #   later   (> 缓存末尾): 重连补新
            #   equal   (== 缓存末尾): 覆盖（数据库 close 更准确）
            #   earlier (< 缓存末尾): 实时 K 线先到时的前向补全（不再被丢弃）
            last_dt = self.klines[-1].get('datetime')
            cache_by_dt = {k.get('datetime'): k for k in self.klines}
            appended = 0
            prepend_or_filled = 0
            overwritten = 0
            for kline in klines_list:
                dt = kline['datetime']
                if dt in cache_by_dt:
                    cache_by_dt[dt] = kline
                    overwritten += 1
                else:
                    cache_by_dt[dt] = kline
                    if last_dt is not None and dt > last_dt:
                        appended += 1
                    else:
                        prepend_or_filled += 1
            # 重排：保证整体时间正序（O(n log n)，仅在 on_ws_history 被调用时触发，频率极低）
            self.klines = sorted(cache_by_dt.values(), key=lambda x: x.get('datetime'))
            if appended > 0:
                print(f"[LiveDataSource] 重连历史补充: +{appended} 条新K线 ({self.symbol})")
            if prepend_or_filled > 0:
                print(f"[LiveDataSource] 历史前向补全: +{prepend_or_filled} 条早于缓存的K线 ({self.symbol})")
            if overwritten > 0:
                print(f"[LiveDataSource] 历史覆盖刷新: {overwritten} 条同时间戳K线以历史 OHLC 为准 ({self.symbol})")
        
        # 更新计数器
        self.kline_count = len(self.klines)
        self.current_idx = max(0, self.kline_count - 1)
        
        # 更新 last_kline_time + 当前价格/时间
        if self.klines:
            last_kline = self.klines[-1]
            self.last_kline_time = last_kline.get('datetime')
            # 用最后一根历史K线的 close 初始化 current_price（避免策略读到 0）
            close_price = last_kline.get('close')
            if close_price is not None and close_price > 0:
                self.current_price = close_price
            self.current_datetime = last_kline.get('datetime', self.current_datetime)
        
        print(f"[LiveDataSource] ✅ 收到 data_server 历史K线 {len(klines_list)} 条 ({self.symbol})，缓存总计 {len(self.klines)} 条")
        if self.klines:
            last = self.klines[-1]
            print(f"[LiveDataSource] 缓存最新K线: {last.get('datetime')} | "
                  f"O:{last.get('open')} H:{last.get('high')} L:{last.get('low')} C:{last.get('close')} "
                  f"V:{last.get('volume')}")

        # IndicatorCache v2: data_server 历史灌入 / 重连合并完毕，重算所有已注册指标
        self._invalidate_ohlcv_cache()
        self._recompute_all_indicators()
    
    def buy(self, volume: int = 1, reason: str = "", log_callback=None, order_type: str = 'bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """买入开仓
        
        Args:
            volume: 交易量
            reason: 交易原因
            log_callback: 日志回调
            order_type: 订单类型
            offset_ticks: 价格偏移tick数，如果不提供则使用配置中的order_offset_ticks
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        if not self.ctp_client:
            if log_callback:
                log_callback("[错误] CTP客户端未初始化")
            return
        
        # 确定委托价格
        if price is not None:
            # 显式指定价格
            limit_price = price
            actual_offset = 0
        elif order_type == 'limit' and price is not None:
            # 指定了limit类型且提供了价格
            limit_price = price
            actual_offset = 0
        else:
            # 使用传入的offset_ticks，如果没有则使用配置中的值
            actual_offset = offset_ticks if offset_ticks is not None else self.order_offset_ticks
            
            # 买入使用卖一价+偏移，确保成交（使用CTP原始字段名）
            tick = self.ticks[-1] if self.ticks else None
            if tick and 'AskPrice1' in tick and tick['AskPrice1'] > 0:
                limit_price = tick['AskPrice1'] + self.price_tick * actual_offset
            else:
                limit_price = self.current_price + self.price_tick * actual_offset
        
        if log_callback:
            from datetime import datetime
            time_str = datetime.now().strftime("%H:%M:%S")
            offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
            log_callback(f"📤 [{time_str}] [买开] {self.symbol} 委托价={limit_price:.2f} {offset_msg} 数量={volume} 原因={reason}")
        
        # 调用CTP接口下单
        self.ctp_client.buy_open(self.symbol, limit_price, volume)
    
    def sell(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type: str = 'bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """卖出平仓（平多头）
        
        支持智能分单：当今仓+昨仓混合时，自动拆分为两个订单
        支持旧合约换月：如果持仓来自旧合约，自动使用旧合约代码平仓
        
        Args:
            volume: 交易量，如果不提供则平所有多头持仓
            reason: 交易原因
            log_callback: 日志回调
            order_type: 订单类型
            offset_ticks: 价格偏移tick数，如果不提供则使用配置中的order_offset_ticks
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        if not self.ctp_client:
            if log_callback:
                log_callback("[错误] CTP客户端未初始化")
            return
        
        # 【关键】检查是否有旧合约持仓需要平仓
        # _old_contract 由持仓同步时设置，表示该数据源的持仓实际来自旧合约
        trade_symbol = getattr(self, '_old_contract', None) or self.symbol
        is_old_contract = (trade_symbol != self.symbol)
        if is_old_contract and log_callback:
            log_callback(f"[换月平仓] 使用旧合约 {trade_symbol} 进行平仓（数据源: {self.symbol}）")
        
        # 获取多头今仓和昨仓（支持锁仓情况）
        long_today = getattr(self, 'long_today', 0)
        long_yd = getattr(self, 'long_yd', 0)
        
        # 如果没有指定数量，平所有多头持仓
        if volume is None:
            volume = long_today + long_yd  # 使用实际多头持仓，而非净持仓
        
        if volume <= 0:
            if log_callback:
                log_callback("[提示] 没有多头持仓，无需平仓")
            return
        
        # 检查总仓位是否足够，不足则自动调整
        total_available = long_today + long_yd
        if volume > total_available:
            if log_callback:
                log_callback(f"[持仓调整] 多头持仓不足: 需要{volume}手，实际{total_available}手 → 自动调整为{total_available}手")
            volume = total_available
            if volume <= 0:
                if log_callback:
                    log_callback("[提示] 没有多头持仓可平")
                return
        
        # 确定委托价格
        if price is not None:
            limit_price = price
            actual_offset = 0
        elif order_type == 'limit' and price is not None:
            limit_price = price
            actual_offset = 0
        else:
            # 使用传入的offset_ticks，如果没有则使用配置中的值
            actual_offset = offset_ticks if offset_ticks is not None else self.order_offset_ticks
            
            # 【关键修复】旧合约换月平仓时，使用更大的偏移量确保成交
            # 因为旧合约没有订阅行情，使用的是新合约价格，可能与旧合约价格有差异
            # 使用100跳偏移量，确保能够成交（换月的目标是尽快平掉旧合约）
            if is_old_contract:
                OLD_CONTRACT_OFFSET_TICKS = 100  # 旧合约平仓使用100跳偏移
                actual_offset = max(actual_offset, OLD_CONTRACT_OFFSET_TICKS)
                if log_callback:
                    log_callback(f"[换月平仓] 旧合约 {trade_symbol} 无行情数据，使用大偏移量 {actual_offset} 跳确保成交")
            
            # 计算委托价格（使用CTP原始字段名）
            tick = self.ticks[-1] if self.ticks else None
            if tick and 'BidPrice1' in tick and tick['BidPrice1'] > 0:
                limit_price = tick['BidPrice1'] - self.price_tick * actual_offset
            else:
                limit_price = self.current_price - self.price_tick * actual_offset
        
        # 智能分单：根据今仓和昨仓数量拆分订单
        if long_today >= volume:
            # 今仓足够，只平今仓
            if log_callback:
                log_callback(f"[平多判断] {trade_symbol} 多头今仓={long_today}, 多头昨仓={long_yd} → 平今仓{volume}手")
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                log_callback(f"📤 [{time_str}] [卖平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={volume} (今仓) 原因={reason}")
            self.ctp_client.sell_close(trade_symbol, limit_price, volume, close_today=True)
            
        elif long_today > 0:
            # 今仓不足，需要分单：先平今仓，再平昨仓
            close_today_volume = long_today
            close_yd_volume = volume - long_today
            
            if log_callback:
                log_callback(f"[平多判断] {trade_symbol} 多头今仓={long_today}, 多头昨仓={long_yd} → 需分单: 平今{close_today_volume}手 + 平昨{close_yd_volume}手")
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                log_callback(f"📤 [{time_str}] [卖平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={close_today_volume} (今仓) 原因={reason}")
            
            # 先平今仓
            self.ctp_client.sell_close(trade_symbol, limit_price, close_today_volume, close_today=True)
            
            # 再平昨仓（已在前面检查过总仓位，这里昨仓一定足够）
            if close_yd_volume > 0:
                if log_callback:
                    from datetime import datetime
                    time_str = datetime.now().strftime("%H:%M:%S")
                    offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                    log_callback(f"📤 [{time_str}] [卖平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={close_yd_volume} (昨仓) 原因={reason}")
                self.ctp_client.sell_close(trade_symbol, limit_price, close_yd_volume, close_today=False)
        else:
            # 没有今仓，只平昨仓
            if log_callback:
                log_callback(f"[平多判断] {trade_symbol} 多头今仓={long_today}, 多头昨仓={long_yd} → 平昨仓{volume}手")
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                log_callback(f"📤 [{time_str}] [卖平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={volume} (昨仓) 原因={reason}")
            self.ctp_client.sell_close(trade_symbol, limit_price, volume, close_today=False)
    
    def sellshort(self, volume: int = 1, reason: str = "", log_callback=None, order_type: str = 'bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """卖出开仓(做空)
        
        Args:
            volume: 交易量
            reason: 交易原因
            log_callback: 日志回调
            order_type: 订单类型
            offset_ticks: 价格偏移tick数，如果不提供则使用配置中的order_offset_ticks
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        if not self.ctp_client:
            if log_callback:
                log_callback("[错误] CTP客户端未初始化")
            return
        
        # 确定委托价格
        if price is not None:
            limit_price = price
            actual_offset = 0
        elif order_type == 'limit' and price is not None:
            limit_price = price
            actual_offset = 0
        else:
            # 使用传入的offset_ticks，如果没有则使用配置中的值
            actual_offset = offset_ticks if offset_ticks is not None else self.order_offset_ticks
            
            # 卖出使用买一价-偏移，确保成交（使用CTP原始字段名）
            tick = self.ticks[-1] if self.ticks else None
            if tick and 'BidPrice1' in tick and tick['BidPrice1'] > 0:
                limit_price = tick['BidPrice1'] - self.price_tick * actual_offset
            else:
                limit_price = self.current_price - self.price_tick * actual_offset
        
        if log_callback:
            from datetime import datetime
            time_str = datetime.now().strftime("%H:%M:%S")
            offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
            log_callback(f"📤 [{time_str}] [卖开] {self.symbol} 委托价={limit_price:.2f} {offset_msg} 数量={volume} 原因={reason}")
        
        # 调用CTP接口下单
        self.ctp_client.sell_open(self.symbol, limit_price, volume)
    
    def buycover(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type: str = 'bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """买入平仓（平空头）
        
        支持智能分单：当今仓+昨仓混合时，自动拆分为两个订单
        支持旧合约换月：如果持仓来自旧合约，自动使用旧合约代码平仓
        
        Args:
            volume: 交易量，如果不提供则平所有空头持仓
            reason: 交易原因
            log_callback: 日志回调
            order_type: 订单类型
            offset_ticks: 价格偏移tick数，如果不提供则使用配置中的order_offset_ticks
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        if not self.ctp_client:
            if log_callback:
                log_callback("[错误] CTP客户端未初始化")
            return
        
        # 【关键】检查是否有旧合约持仓需要平仓
        trade_symbol = getattr(self, '_old_contract', None) or self.symbol
        is_old_contract = (trade_symbol != self.symbol)
        if is_old_contract and log_callback:
            log_callback(f"[换月平仓] 使用旧合约 {trade_symbol} 进行平仓（数据源: {self.symbol}）")
        
        # 获取空头今仓和昨仓（支持锁仓情况）
        short_today = getattr(self, 'short_today', 0)
        short_yd = getattr(self, 'short_yd', 0)
        
        # 如果没有指定数量，平所有空头持仓
        if volume is None:
            volume = short_today + short_yd  # 使用实际空头持仓，而非净持仓
        
        if volume <= 0:
            if log_callback:
                log_callback("[提示] 没有空头持仓，无需平仓")
            return
        
        # 检查总仓位是否足够，不足则自动调整
        total_available = short_today + short_yd
        if volume > total_available:
            if log_callback:
                log_callback(f"[持仓调整] 空头持仓不足: 需要{volume}手，实际{total_available}手 → 自动调整为{total_available}手")
            volume = total_available
            if volume <= 0:
                if log_callback:
                    log_callback("[提示] 没有空头持仓可平")
                return
        
        # 确定委托价格
        if price is not None:
            limit_price = price
            actual_offset = 0
        elif order_type == 'limit' and price is not None:
            limit_price = price
            actual_offset = 0
        else:
            # 使用传入的offset_ticks，如果没有则使用配置中的值
            actual_offset = offset_ticks if offset_ticks is not None else self.order_offset_ticks
            
            # 【关键修复】旧合约换月平仓时，使用更大的偏移量确保成交
            # 因为旧合约没有订阅行情，使用的是新合约价格，可能与旧合约价格有差异
            # 使用100跳偏移量，确保能够成交（换月的目标是尽快平掉旧合约）
            if is_old_contract:
                OLD_CONTRACT_OFFSET_TICKS = 100  # 旧合约平仓使用100跳偏移
                actual_offset = max(actual_offset, OLD_CONTRACT_OFFSET_TICKS)
                if log_callback:
                    log_callback(f"[换月平仓] 旧合约 {trade_symbol} 无行情数据，使用大偏移量 {actual_offset} 跳确保成交")
            
            # 计算委托价格（使用CTP原始字段名）
            tick = self.ticks[-1] if self.ticks else None
            if tick and 'AskPrice1' in tick and tick['AskPrice1'] > 0:
                limit_price = tick['AskPrice1'] + self.price_tick * actual_offset
            else:
                limit_price = self.current_price + self.price_tick * actual_offset
        
        # 智能分单：根据今仓和昨仓数量拆分订单
        if short_today >= volume:
            # 今仓足够，只平今仓
            if log_callback:
                log_callback(f"[平空判断] {trade_symbol} 空头今仓={short_today}, 空头昨仓={short_yd} → 平今仓{volume}手")
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                log_callback(f"📤 [{time_str}] [买平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={volume} (今仓) 原因={reason}")
            self.ctp_client.buy_close(trade_symbol, limit_price, volume, close_today=True)
            
        elif short_today > 0:
            # 今仓不足，需要分单：先平今仓，再平昨仓
            close_today_volume = short_today
            close_yd_volume = volume - short_today
            
            if log_callback:
                log_callback(f"[平空判断] {trade_symbol} 空头今仓={short_today}, 空头昨仓={short_yd} → 需分单: 平今{close_today_volume}手 + 平昨{close_yd_volume}手")
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                log_callback(f"📤 [{time_str}] [买平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={close_today_volume} (今仓) 原因={reason}")
            
            # 先平今仓
            self.ctp_client.buy_close(trade_symbol, limit_price, close_today_volume, close_today=True)
            
            # 再平昨仓（已在前面检查过总仓位，这里昨仓一定足够）
            if close_yd_volume > 0:
                if log_callback:
                    from datetime import datetime
                    time_str = datetime.now().strftime("%H:%M:%S")
                    offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                    log_callback(f"📤 [{time_str}] [买平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={close_yd_volume} (昨仓) 原因={reason}")
                self.ctp_client.buy_close(trade_symbol, limit_price, close_yd_volume, close_today=False)
        else:
            # 没有今仓，只平昨仓
            if log_callback:
                log_callback(f"[平空判断] {trade_symbol} 空头今仓={short_today}, 空头昨仓={short_yd} → 平昨仓{volume}手")
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                offset_msg = f"(偏移{actual_offset}跳)" if actual_offset != 0 else "(限价)"
                log_callback(f"📤 [{time_str}] [买平] {trade_symbol} 委托价={limit_price:.2f} {offset_msg} 数量={volume} (昨仓) 原因={reason}")
            self.ctp_client.buy_close(trade_symbol, limit_price, volume, close_today=False)
    
    def buytocover(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type: str = 'bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """买入平仓(平空) - 别名
        
        Args:
            volume: 交易量，如果不提供则平所有空头持仓
            reason: 交易原因
            log_callback: 日志回调
            order_type: 订单类型
            offset_ticks: 价格偏移tick数，如果不提供则使用配置中的order_offset_ticks
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        return self.buycover(volume, reason, log_callback, order_type, offset_ticks, price)
    
    def close_all(self, reason: str = "", log_callback=None, order_type: str = 'bar_close'):
        """平掉所有持仓（包括锁仓情况）"""
        # 获取多头和空头的实际持仓（不是净持仓）
        long_pos = getattr(self, 'long_today', 0) + getattr(self, 'long_yd', 0)
        short_pos = getattr(self, 'short_today', 0) + getattr(self, 'short_yd', 0)
        
        # 平掉多头持仓
        if long_pos > 0:
            if log_callback:
                log_callback(f"[close_all] {self.symbol} 平多头持仓 {long_pos} 手")
            self.sell(volume=long_pos, reason=reason, log_callback=log_callback, order_type=order_type)
        
        # 平掉空头持仓
        if short_pos > 0:
            if log_callback:
                log_callback(f"[close_all] {self.symbol} 平空头持仓 {short_pos} 手")
            self.buycover(volume=short_pos, reason=reason, log_callback=log_callback, order_type=order_type)
    
    def reverse_pos(self, reason: str = "", log_callback=None, order_type: str = 'bar_close'):
        """反转持仓"""
        # 先记录原持仓方向（平仓后 current_pos 会变成 0）
        long_pos = getattr(self, 'long_today', 0) + getattr(self, 'long_yd', 0)
        short_pos = getattr(self, 'short_today', 0) + getattr(self, 'short_yd', 0)
        was_long = long_pos > 0
        was_short = short_pos > 0
        
        # 先平仓
        self.close_all(reason=reason, log_callback=log_callback, order_type=order_type)
        
        # 再反向开仓
        time.sleep(0.5)  # 等待平仓完成
        
        if was_long and not was_short:
            # 原来是多头，反转为空头
            self.sellshort(volume=1, reason=reason, log_callback=log_callback, order_type=order_type)
        elif was_short and not was_long:
            # 原来是空头，反转为多头
            self.buy(volume=1, reason=reason, log_callback=log_callback, order_type=order_type)
        elif was_long and was_short:
            # 锁仓情况，不做反转（避免复杂情况）
            if log_callback:
                log_callback(f"[reverse_pos] {self.symbol} 存在锁仓（多{long_pos}空{short_pos}），仅平仓不反转")
    
    def cancel_order(self, order_sys_id: str, log_callback=None) -> bool:
        """撤销指定的未成交订单。"""
        if not self.ctp_client:
            if log_callback:
                log_callback("[错误] CTP客户端未初始化")
            return False

        normalized_id = str(order_sys_id or '').strip()
        if not normalized_id:
            if log_callback:
                log_callback("[撤单] OrderSysID不能为空")
            return False

        matched_order = None
        matched_key = None
        for key, order in self.pending_orders.items():
            current_id = order.get('OrderSysID') or key
            if str(current_id).strip() == normalized_id:
                matched_order = order
                matched_key = key
                break

        if matched_order is None:
            if log_callback:
                log_callback(f"[撤单] {self.symbol} 未找到活动订单: {normalized_id}")
            return False

        order_status = matched_order.get('OrderStatus')
        if order_status not in ['1', '3', 'a']:
            if log_callback:
                log_callback(
                    f"[撤单] 订单 {normalized_id} 当前状态不可撤: {order_status}"
                )
            return False

        instrument_id = matched_order.get('InstrumentID') or self.symbol
        exchange_id = matched_order.get('ExchangeID', '')
        if not exchange_id:
            from ..pyctp.trader_api import _get_exchange_id
            exchange_id = _get_exchange_id(instrument_id) or 'SHFE'

        actual_order_sys_id = matched_order.get('OrderSysID') or matched_key
        if log_callback:
            log_callback(
                f"[撤单] {instrument_id} 订单号={actual_order_sys_id} 交易所={exchange_id}"
            )
        self.ctp_client.cancel_order(
            instrument_id, actual_order_sys_id, exchange_id
        )
        return True

    def cancel_all_orders(self, log_callback=None):
        """
        撤销所有未成交的订单
        
        注意：需要订单系统编号(OrderSysID)才能撤单
        """
        if not self.ctp_client:
            if log_callback:
                log_callback("[错误] CTP客户端未初始化")
            return
        
        if not hasattr(self, 'pending_orders') or not self.pending_orders:
            if log_callback:
                log_callback(f"[撤单] {self.symbol} 无未成交订单")
            return
        
        # 撤销所有未成交的订单
        cancel_count = 0
        for order in list(self.pending_orders.values()):
            if order.get('OrderSysID') and order.get('OrderStatus') in ['1', '3', 'a']:  # 部分成交/未成交/未知
                inst = order.get("InstrumentID") or self.symbol
                # 从订单数据中获取交易所代码
                exchange_id = order.get('ExchangeID', '')
                if not exchange_id:
                    from ..pyctp.trader_api import _get_exchange_id
                    exchange_id = _get_exchange_id(inst) or 'SHFE'
                
                if log_callback:
                    log_callback(f"[撤单] {inst} 订单号={order['OrderSysID']} 交易所={exchange_id}")
                
                self.ctp_client.cancel_order(inst, order['OrderSysID'], exchange_id)
                cancel_count += 1
        
        if cancel_count > 0 and log_callback:
            log_callback(f"[撤单] 共撤销 {cancel_count} 个订单")
        
        # 等待撤单完成
        if cancel_count > 0:
            time.sleep(0.3)


class MultiDataSource:
    """多数据源容器 - 兼容回测API"""
    
    def __init__(self, data_sources: List[LiveDataSource]):
        self.data_sources = data_sources
    
    def __getitem__(self, index: int) -> LiveDataSource:
        return self.data_sources[index]
    
    def __len__(self) -> int:
        return len(self.data_sources)


def _normalize_period(period: str) -> str:
    """
    将K线周期标准化为 data_server 格式（大写）
    
    '1m', '1min' -> '1M'
    '5m', '5min' -> '5M'
    '15m' -> '15M'
    '30m' -> '30M'
    '1h', '60m', '1hour' -> '1H'
    '1d', 'd', '1day' -> '1D'
    """
    import re
    p = period.strip().lower()
    p = re.sub(r'(\d+)min$', r'\1m', p)
    p = re.sub(r'(\d+)hour$', r'\1h', p)
    p = re.sub(r'(\d+)day$', r'\1d', p)
    if p == 'd':
        p = '1d'
    return p.upper()


class LiveTradingAdapter:
    """实盘交易适配器"""
    
    def __init__(self, mode: str, config: Dict, strategy_func: Callable, 
                 initialize_func: Optional[Callable] = None,
                 strategy_params: Optional[Dict] = None,
                 on_trade_callback: Optional[Callable] = None,
                 on_order_callback: Optional[Callable] = None,
                 on_cancel_callback: Optional[Callable] = None,
                 on_order_error_callback: Optional[Callable] = None,
                 on_cancel_error_callback: Optional[Callable] = None,
                 on_account_callback: Optional[Callable] = None,
                 on_position_callback: Optional[Callable] = None,
                 on_position_complete_callback: Optional[Callable] = None,
                 on_disconnect_callback: Optional[Callable] = None,
                 on_query_trade_callback: Optional[Callable] = None,
                 on_query_trade_complete_callback: Optional[Callable] = None,
                 on_query_order_callback: Optional[Callable] = None,
                 on_query_order_complete_callback: Optional[Callable] = None):
        """
        初始化实盘交易适配器
        
        Args:
            mode: 'simnow' 或 'real'
            config: 配置字典
            strategy_func: 策略函数
            initialize_func: 初始化函数
            strategy_params: 策略参数
            on_trade_callback: 用户自定义成交回调
            on_order_callback: 用户自定义报单回调
            on_cancel_callback: 用户自定义撤单回调
            on_order_error_callback: 用户自定义报单错误回调
            on_cancel_error_callback: 用户自定义撤单错误回调
            on_account_callback: 用户自定义账户资金回调
            on_position_callback: 用户自定义持仓回调
            on_position_complete_callback: 用户自定义持仓查询完成回调
            on_disconnect_callback: 用户自定义断开连接回调
            on_query_trade_callback: 用户自定义成交查询回调（单条）
            on_query_trade_complete_callback: 用户自定义成交查询完成回调
            on_query_order_callback: 用户自定义委托查询回调（单条）
            on_query_order_complete_callback: 用户自定义委托查询完成回调
        """
        self.mode = mode
        self.config = config
        self.strategy_func = strategy_func
        self.initialize_func = initialize_func
        self.strategy_params = strategy_params or {}
        self.on_trade_callback = on_trade_callback
        self.on_order_callback = on_order_callback
        self.on_cancel_callback = on_cancel_callback
        self.on_order_error_callback = on_order_error_callback
        self.on_cancel_error_callback = on_cancel_error_callback
        self.on_account_callback = on_account_callback
        self.on_position_callback = on_position_callback
        self.on_position_complete_callback = on_position_complete_callback
        self.on_disconnect_callback = on_disconnect_callback
        self.on_query_trade_callback = on_query_trade_callback
        self.on_query_trade_complete_callback = on_query_trade_complete_callback
        self.on_query_order_callback = on_query_order_callback
        self.on_query_order_complete_callback = on_query_order_complete_callback
        
        # CTP客户端
        self.ctp_client: Optional[Union['SIMNOWClient', 'RealTradingClient']] = None
        
        # 账户信息（实时更新）
        self.account_info = {
            'balance': 0,           # 账户权益
            'available': 0,         # 可用资金
            'position_profit': 0,   # 持仓盈亏
            'close_profit': 0,      # 平仓盈亏
            'commission': 0,        # 手续费
            'frozen_margin': 0,     # 冻结保证金
            'curr_margin': 0,       # 占用保证金
            'update_time': None,    # 更新时间
        }
        
        # 数据源
        self.data_source: Optional[LiveDataSource] = None
        self.multi_data_source: Optional[MultiDataSource] = None
        
        # 持仓查询完成事件
        import threading
        self._position_query_done = threading.Event()
        
        # 策略API
        self.api = None
        
        # 数据记录器 - 为每个数据源（品种+周期）创建独立的记录器
        # 键格式: {symbol}_{kline_period}，如 rb2601_1m, rb2601_5m
        self.data_recorders = {}
        save_kline_csv = config.get('save_kline_csv', False)
        save_kline_db = config.get('save_kline_db', False)
        save_tick_csv = config.get('save_tick_csv', False)
        save_tick_db = config.get('save_tick_db', False)
        
        if save_kline_csv or save_kline_db or save_tick_csv or save_tick_db:
            save_path = config.get('data_save_path', './live_data')
            db_path = config.get('db_path', 'data_cache/backtest_data.db')
            
            # 支持单数据源和多数据源
            if 'data_sources' in config:
                # 多数据源模式：为每个数据源创建记录器（支持同品种不同周期）
                for ds_config in config['data_sources']:
                    symbol = ds_config['symbol']
                    kline_period = ds_config.get('kline_period', '1m')
                    adjust_type = ds_config.get('adjust_type', '0')
                    recorder_adjust_type = '0'
                    
                    # 键: symbol_period，支持同品种多周期
                    recorder_key = f"{symbol}_{kline_period}"
                    self.data_recorders[recorder_key] = DataRecorder(
                        symbol=symbol,
                        kline_period=kline_period,
                        save_path=save_path,
                        db_path=db_path,
                        save_kline_csv=save_kline_csv,
                        save_kline_db=save_kline_db,
                        save_tick_csv=save_tick_csv,
                        save_tick_db=save_tick_db,
                        adjust_type=recorder_adjust_type,
                    )
            else:
                # 单数据源模式
                symbol = config['symbol']
                kline_period = config.get('kline_period', '1m')
                adjust_type = config.get('adjust_type', '0')
                recorder_adjust_type = '0'
                
                recorder_key = f"{symbol}_{kline_period}"
                self.data_recorders[recorder_key] = DataRecorder(
                    symbol=symbol,
                    kline_period=kline_period,
                    save_path=save_path,
                    db_path=db_path,
                    save_kline_csv=save_kline_csv,
                    save_kline_db=save_kline_db,
                    save_tick_csv=save_tick_csv,
                    save_tick_db=save_tick_db,
                    adjust_type=recorder_adjust_type,
                )
        
        # 运行标志
        self.running = False
        self.strategy_thread = None
        self._tick_thread_should_stop = False
        
        # TICK流支持（双驱动模式）
        self.enable_tick_callback = config.get('enable_tick_callback', False)
        
        # ========== Tick 处理队列（解耦 CTP 线程和策略执行） ==========
        self._tick_queue_maxsize = max(1000, int(config.get('tick_queue_maxsize', 20000)))
        self._tick_queue_soft_limit = max(100, int(self._tick_queue_maxsize * 0.7))
        self._tick_queue_recover_limit = max(50, int(self._tick_queue_maxsize * 0.3))
        self._tick_queue = queue.Queue(maxsize=self._tick_queue_maxsize)
        self._tick_thread: Optional[threading.Thread] = None
        self._tick_queue_high_water = 0
        self._tick_overflow_latest: Dict[str, Dict] = {}
        self._tick_overflow_count = 0
        self._tick_overflow_last_log = 0.0
        self._tick_overflow_lock = threading.Lock()
        self._runtime_state_lock = threading.Lock()
        self._runtime_state = {
            'pressure_level': 'normal',
            'tick_queue_size': 0,
            'tick_queue_maxsize': self._tick_queue_maxsize,
            'tick_queue_high_water': 0,
            'overflow_buffer_size': 0,
            'overflow_total': 0,
            'avg_process_ms': 0.0,
            'last_process_ms': 0.0,
            'compact_count': 0,
            'last_update_time': None,
        }
        
        # ========== data_server WebSocket K线客户端 ==========
        self.ws_kline_client = None
        self._ws_subscription_map = {}  # (ws_symbol, period) -> LiveDataSource
        self._strategy_lock = threading.Lock()  # 策略执行锁（防止tick线程和WS线程并发调用）
        self._kline_source = config.get('kline_source', 'data_server')
        self._ws_preload_done = threading.Event()
        self._ws_preload_expected = 0
        self._ws_preload_received = 0
        self._ws_preload_lock = threading.Lock()
        
        # data_server 模式 tick 回调节流（避免开盘 tick 洪峰导致假死）
        self._ws_kline_arrived = threading.Event()
        self._last_tick_strategy_ts = 0.0
        self._tick_callback_interval = float(config.get('tick_callback_interval', 0.5))
        
        # 自动换月引擎（run() 内 _init_data_source 之后创建）
        self._rollover_engine = None
        
        # 智能追单：超时撤单后「重发」匹配用（OrderSysID 为空时用 FrontID+SessionID+OrderRef）
        self._algo_timeout_resend: Dict[str, Any] = {}
        # 重发登记 TTL（秒）：超过该时长仍未被撤单回报命中的登记自动清理；0 或负数关闭清理
        # 默认 300 秒，远大于典型 ORDER_TIMEOUT × RETRY_LIMIT，避免清理掉正常等回报的登记
        self._algo_resend_plan_ttl: float = float(config.get('algo_resend_plan_ttl', 300.0))
        # 智能追单 · 重试次数继承队列（B4 修复）：按 (InstrumentID, Direction, OffsetFlag[0]) 三元组在 TTL 内 FIFO 匹配，
        # 取代原先的全局 ds._next_order_retry_count 标志位，避免重发瞬间的并发新订单错继承重试次数。
        self._pending_inherit: List[Dict[str, Any]] = []
        # 三元组队列 TTL（秒）：默认 10 秒，足以覆盖一次重发提交→新订单回报的链路；可通过 config 调整
        self._pending_inherit_ttl: float = float(config.get('algo_inherit_ttl', 10.0))
        
        print(f"[实盘适配器] 初始化 - 模式: {mode}")
        print(
            f"[实盘适配器] Tick队列: max={self._tick_queue_maxsize}, "
            f"soft={self._tick_queue_soft_limit}, recover={self._tick_queue_recover_limit}"
        )
        if self._kline_source == 'data_server':
            print(f"[实盘适配器] ✓ K线数据源: data_server（远程推送模式）")
        if self.enable_tick_callback:
            if self._kline_source == 'data_server':
                print(f"[实盘适配器] ✓ TICK流双驱动模式已启用（data_server节流: 新K线立即触发, 无K线时≤{self._tick_callback_interval}s触发一次）")
            else:
                print(f"[实盘适配器] ✓ TICK流双驱动模式已启用（每个tick和K线完成时都会触发策略）")

    def _update_runtime_state(self, **kwargs):
        """更新运行时状态快照，供策略层做自适应降级。"""
        with self._runtime_state_lock:
            self._runtime_state.update(kwargs)
            self._runtime_state['last_update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _refresh_runtime_pressure(self, queue_size: Optional[int] = None):
        """根据队列积压和处理耗时评估当前压力等级。"""
        if queue_size is None:
            queue_size = self._tick_queue.qsize()

        with self._runtime_state_lock:
            avg_process_ms = float(self._runtime_state.get('avg_process_ms', 0.0) or 0.0)
            overflow_buffer_size = int(self._runtime_state.get('overflow_buffer_size', 0) or 0)

        ratio = queue_size / self._tick_queue_maxsize if self._tick_queue_maxsize > 0 else 0
        if overflow_buffer_size > 0 or ratio >= 0.85 or avg_process_ms >= 500:
            pressure_level = 'critical'
        elif ratio >= 0.5 or avg_process_ms >= 150:
            pressure_level = 'busy'
        else:
            pressure_level = 'normal'

        self._update_runtime_state(
            pressure_level=pressure_level,
            tick_queue_size=queue_size,
            tick_queue_high_water=self._tick_queue_high_water,
        )

    def get_runtime_stats(self) -> Dict[str, Any]:
        """返回运行时统计快照。"""
        with self._runtime_state_lock:
            return dict(self._runtime_state)
    
    def run(self) -> Dict[str, Any]:
        """运行实盘交易"""
        # ========== 鉴权检查（仅使用 data_server 远程 K 线时需要） ==========
        from ..data.auth_manager import verify_auth, get_auth_message, set_effective_data_server
        set_effective_data_server(self.config.get('data_server'))
        if self._kline_source == 'data_server':
            if not verify_auth():
                auth_msg = get_auth_message()
                raise RuntimeError(
                    f"\n{'='*70}\n"
                    f"【当前 K 线源: data_server】需要松鼠俱乐部会员账号才能接收远程 K 线推送。\n"
                    f"鉴权失败原因: {auth_msg}\n"
                    f"{'='*70}\n"
                    f"\n解决方案（二选一）:\n"
                    f"\n1) 申请俱乐部会员并配置账号:\n"
                    f"   联系小松鼠 微信: viquant01\n"
                    f"   然后在 ssquant/config/trading_config.py 中填写俱乐部账号(API_USERNAME)和俱乐部密码(API_PASSWORD)\n"
                    f"\n2) 切换到 CTP 本地 K 线模式（无需会员）:\n"
                    f"   在 get_config() 中将参数改为: kline_source='local'\n"
                    f"   此模式下 CTP 自动从交易所 Tick 合成 K 线，完全免费\n"
                    f"{'='*70}"
                )
        
        # 初始化CTP客户端
        self._init_ctp_client()
        
        # 初始化数据源
        self._init_data_source()
        
        # 自动换月（移仓）引擎：依赖 multi_data_source 与合并后的 config
        from .rollover_engine import RolloverEngine
        self._rollover_engine = RolloverEngine(self)
        
        # 创建策略API
        self._create_strategy_api()
        
        # 初始化 data_server WebSocket K线客户端（如果启用）
        if self._kline_source == 'data_server':
            self._init_ws_kline_client()
        
        # 等待 data_server 预加载完成（在 CTP 连接前）
        if self._kline_source == 'data_server' and self._ws_preload_expected > 0:
            _preload_timeout = self._ws_preload_expected * 30
            print(f"[实盘适配器] 等待 data_server 预加载完成 ({self._ws_preload_expected} 个数据源)...")
            if self._ws_preload_done.wait(timeout=_preload_timeout):
                print(f"[实盘适配器] ✅ data_server 预加载完成 ({self._ws_preload_received}/{self._ws_preload_expected})\n")
            else:
                print(f"[实盘适配器] ⚠️ data_server 预加载超时，已收到 {self._ws_preload_received}/{self._ws_preload_expected}，继续启动...\n")
        
        # 运行策略初始化
        if self.initialize_func:
            print("[实盘适配器] 运行策略初始化...")
            self.initialize_func(self.api)
        
        # 启动 tick 处理线程（在 CTP 连接前，确保不遗漏早期 tick）
        self._tick_thread_should_stop = False
        self._tick_thread = threading.Thread(target=self._tick_processing_loop, daemon=True)
        self._tick_thread.start()
        print("[实盘适配器] ✓ Tick处理线程已启动（CTP线程解耦）")
        
        # 连接CTP
        print("[实盘适配器] 连接CTP服务器...")
        if self.ctp_client:
            self.ctp_client.connect()
            
            # 等待连接就绪
            self.ctp_client.wait_ready(timeout=30)
            
            # 查询持仓（同步到本地状态）
            # 重置持仓查询完成事件
            self._position_query_done.clear()
            
            # 清除旧的持仓缓存（使用覆盖模式，每次查询开始时清空）
            self._position_cache = {}
            
            # 【修复】使用空字符串查询所有持仓，避免大小写不匹配导致查不到
            # CTP 的 ReqQryInvestorPosition 传空字符串会返回账户所有持仓
            self._pending_position_queries = set([''])  # 只查询一次
            self.ctp_client.query_position('')  # 空字符串 = 查询所有持仓
            
            # 等待持仓查询完成（事件驱动，最多等待10秒）
            self._position_query_done.wait(timeout=10)
        else:
            raise RuntimeError("CTP客户端初始化失败")
        
        # 启动策略线程
        self.running = True
        
        # 品牌与免责声明（在CTP连接就绪后显示）
        self._print_disclaimer()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[实盘适配器] 用户中断")
        finally:
            self.stop()
        
        # 返回结果
        result = {
            'status': 'completed',
            'mode': self.mode,
        }
        
        # 添加symbol信息
        if 'data_sources' in self.config:
            result['symbols'] = [ds['symbol'] for ds in self.config['data_sources']]
        else:
            result['symbol'] = self.config['symbol']
        
        return result
    
    def _print_disclaimer(self):
        """打印品牌信息与免责声明"""
        border = "=" * 80
        print(f"\n{border}")
        print("  🐿️  松鼠Quant (SSQuant) - 专业量化交易框架")
        print(f"{border}")
        print("  🌐 官方网站: quant789.com")
        print("  📱 公众号  : 松鼠Quant")
        print(f"{border}")
        print("  ⚠️  风险提示 & 免责声明:")
        print("  1. 期货交易具有高风险，可能导致本金全部损失。")
        print("  2. 本软件仅供学习、研究与策略开发使用，不构成任何投资建议，且不能保证框架无BUG。")
        print("  3. 历史回测业绩不代表未来表现，模拟盘盈利不代表实盘盈利。")
        print("  4. 使用本软件产生的任何交易盈亏由用户自行承担，开发者不承担任何责任。")
        print("  5. 若不同意以上条款，请立即停止使用并退出！")
        print(f"{border}\n")

    def _init_ctp_client(self) -> None:
        """初始化CTP客户端"""
        # 获取订阅列表
        if 'data_sources' in self.config:
            # 多数据源模式：订阅所有品种（去重）
            subscribe_list = list(set([ds['symbol'] for ds in self.config['data_sources']]))
            print(f"[CTP客户端] 多数据源模式，准备订阅 {len(subscribe_list)} 个品种:")
            for symbol in subscribe_list:
                print(f"  - {symbol}")
        else:
            # 单数据源模式
            subscribe_list = [self.config['symbol']]
            print(f"[CTP客户端] 单数据源模式，订阅品种: {subscribe_list[0]}")
        
        if self.mode == 'simnow':
            from ..pyctp.simnow_client import SIMNOWClient
            
            self.ctp_client = SIMNOWClient(
                investor_id=self.config['investor_id'],
                password=self.config['password'],
                server_name=self.config.get('server_name', '24hour'),
                subscribe_list=subscribe_list
            )
        
        elif self.mode == 'real':
            from ..pyctp.real_trading_client import RealTradingClient
            
            self.ctp_client = RealTradingClient(
                broker_id=self.config['broker_id'],
                investor_id=self.config['investor_id'],
                password=self.config['password'],
                md_server=self.config['md_server'],
                td_server=self.config['td_server'],
                app_id=self.config['app_id'],
                auth_code=self.config['auth_code'],
                subscribe_list=subscribe_list
            )
        
        # 设置回调
        if self.ctp_client:
            self.ctp_client.on_market_data = self._on_market_data
            self.ctp_client.on_trade = self._on_trade
            self.ctp_client.on_order = self._on_order
            self.ctp_client.on_cancel = self._on_cancel
            self.ctp_client.on_position = self._on_position
            self.ctp_client.on_position_complete = self._on_position_complete
            self.ctp_client.on_order_error = self._on_order_error
            self.ctp_client.on_cancel_error = self._on_cancel_error
            self.ctp_client.on_account = self._on_account
            self.ctp_client.on_disconnected = self._on_disconnect
            self.ctp_client.on_query_trade = self._on_query_trade
            self.ctp_client.on_query_trade_complete = self._on_query_trade_complete
            self.ctp_client.on_query_order = self._on_query_order
            self.ctp_client.on_query_order_complete = self._on_query_order_complete
    
    def _init_data_source(self):
        """初始化数据源"""
        data_sources = []
        
        if 'data_sources' in self.config:
            # 多数据源模式
            for ds_config in self.config['data_sources']:
                # 合并配置：优先使用数据源独立配置，再用全局配置
                merged_config = {
                    **self.config,  # 全局配置
                    **ds_config,    # 数据源独立配置（会覆盖全局配置）
                }
                # 确保 kline_period 正确设置
                merged_config['kline_period'] = ds_config.get('kline_period', self.config.get('kline_period', '1min'))
                
                data_source = LiveDataSource(
                    symbol=ds_config['symbol'],
                    config=merged_config
                )
                data_source.ctp_client = self.ctp_client
                data_sources.append(data_source)
            
            # 第一个数据源作为主数据源
            self.data_source = data_sources[0]
        else:
            # 单数据源模式
            self.data_source = LiveDataSource(
                symbol=self.config['symbol'],
                config=self.config
            )
            self.data_source.ctp_client = self.ctp_client
            data_sources.append(self.data_source)
        
        # 并行预加载历史数据（local 模式）
        self._parallel_preload(data_sources)
        
        # 创建多数据源容器(兼容回测API)
        self.multi_data_source = MultiDataSource(data_sources)
        # 反向引用：让数据源在超时撤单时能登记重发计划到适配器
        for _ds in data_sources:
            _ds.trading_adapter = self
    
    def _parallel_preload(self, data_sources: list):
        """并行预加载所有数据源的历史数据"""
        need_preload = [ds for ds in data_sources if getattr(ds, '_need_preload', False)]
        if not need_preload:
            return
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        max_workers = min(8, len(need_preload))
        print(f"\n[预加载] 并行加载 {len(need_preload)} 个数据源的历史数据 (线程数: {max_workers})...")
        
        def _do_preload(ds):
            try:
                ds._preload_historical_data(ds._preload_config)
                return ds.symbol, True
            except Exception as e:
                print(f"[预加载] {ds.symbol} 失败: {e}")
                return ds.symbol, False
        
        t0 = time.time()
        success_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_do_preload, ds): ds for ds in need_preload}
            for future in as_completed(futures):
                symbol, ok = future.result()
                if ok:
                    success_count += 1
        
        elapsed = time.time() - t0
        print(f"[预加载] 完成: {success_count}/{len(need_preload)} 成功，耗时 {elapsed:.1f}s\n")
    
    def _init_ws_kline_client(self):
        """初始化 data_server WebSocket K线客户端"""
        from ..data.ws_kline_client import WSKlineClient, WEBSOCKET_AVAILABLE
        from ..data.contract_mapper import ContractMapper
        
        if not WEBSOCKET_AVAILABLE:
            print("[实盘适配器] ❌ websocket-client 未安装，无法使用 data_server K线模式")
            print("[实盘适配器]    请运行: pip install websocket-client")
            print("[实盘适配器]    回退到本地K线聚合模式")
            self._kline_source = 'local'
            # 回退: 设置所有数据源为local模式
            for ds in self.multi_data_source.data_sources:
                ds.kline_source = 'local'
            return
        
        # 获取 data_server 配置
        ds_config = self.config.get('data_server', {})
        ws_url = ds_config.get('ws_url', 'ws://localhost:8087')
        ws_urls = [ws_url]
        for fb in (ds_config.get('fallback_servers') or []):
            w = fb.get('ws_url')
            if w:
                ws_urls.append(w)
        default_preload = ds_config.get('preload_count', 100)
        auto_reconnect = ds_config.get('auto_reconnect', True)
        reconnect_interval = ds_config.get('reconnect_interval', 5.0)
        
        if len(ws_urls) > 1:
            print(f"\n[实盘适配器] 连接 data_server（多地址轮询）:")
            for i, u in enumerate(ws_urls):
                print(f"  [{i + 1}] {u}")
        else:
            print(f"\n[实盘适配器] 连接 data_server: {ws_urls[0]}")
        
        # 创建客户端
        self.ws_kline_client = WSKlineClient(
            ws_urls=ws_urls,
            auto_reconnect=auto_reconnect,
            reconnect_interval=reconnect_interval,
        )
        
        # 设置回调
        self.ws_kline_client.on_kline = self._on_ws_kline
        self.ws_kline_client.on_history = self._on_ws_history
        self.ws_kline_client.on_auth_required = self._reauth_for_ws
        
        # 连接
        connected = self.ws_kline_client.connect(timeout=10.0)
        
        if not connected:
            print("[实盘适配器] ⚠️ data_server 连接超时，将在后台继续重连")
        
        # 为每个数据源订阅K线
        self._ws_preload_expected = 0
        self._ws_preload_received = 0
        self._ws_preload_done.clear()
        
        for ds in self.multi_data_source.data_sources:
            if ds.kline_source != 'data_server':
                continue
            
            # 推导 WebSocket 订阅合约: 具体合约 → 主连(888)
            ws_symbol = ContractMapper.get_continuous_symbol(ds.symbol).lower()
            period = _normalize_period(ds.kline_period)
            
            # 建立映射: (ws_symbol, period) -> LiveDataSource
            map_key = (ws_symbol, period)
            self._ws_subscription_map[map_key] = ds
            
            # data_server 模式：优先使用策略配置的 history_lookback_bars 作为预加载数量
            ds_preload_cfg = getattr(ds, '_preload_config', {})
            preload_count = ds_preload_cfg.get('history_lookback_bars', default_preload) if ds_preload_cfg.get('preload_history', False) else default_preload
            
            if preload_count > 0:
                self._ws_preload_expected += 1
            
            # 订阅
            self.ws_kline_client.subscribe_kline(
                symbol=ws_symbol,
                period=period,
                preload=preload_count,
            )
            
            print(f"  订阅: {ws_symbol} {period} (preload={preload_count}) → 数据源 {ds.symbol}")
        
        if self._ws_preload_expected == 0:
            self._ws_preload_done.set()
        
        print(f"[实盘适配器] data_server K线订阅完成，等待预加载 {self._ws_preload_expected} 个数据源...\n")
    
    def _reauth_for_ws(self):
        """WebSocket 被服务端以 4001 拒绝后，重新进行 HTTP 鉴权"""
        from ..data.auth_manager import reset_auth, verify_auth, get_auth_message
        reset_auth()
        if verify_auth():
            print("[实盘适配器] WebSocket 重新鉴权成功")
        else:
            print(f"[实盘适配器] WebSocket 重新鉴权失败: {get_auth_message()}")
    
    def _on_ws_kline(self, symbol: str, period: str, kline_data: Dict):
        """
        data_server WebSocket K线推送回调
        
        当 data_server 推送一根已完成的K线时触发
        """
        # 查找对应的 LiveDataSource
        map_key = (symbol.lower(), period.upper())
        ds = self._ws_subscription_map.get(map_key)
        
        if not ds:
            return
        
        # 添加到数据源的K线缓存
        completed_kline = ds.on_ws_kline(kline_data)
        
        # 仅在新K线到达时才记录+触发策略（重复K线更新返回None，跳过）
        if completed_kline:
            # 通知 tick 处理线程有新 K 线到达（用于 data_server + tick 回调节流）
            self._ws_kline_arrived.set()
            
            # 记录K线数据（如果启用了数据保存）
            recorder_key = f"{ds.symbol}_{ds.kline_period}"
            if recorder_key in self.data_recorders:
                self.data_recorders[recorder_key].record_kline(completed_kline)
            
            # 触发策略执行（仅在非TICK回调模式下）
            # TICK回调模式下，策略已经由 _on_market_data 的每个tick触发
            if self.running and not self.enable_tick_callback:
                try:
                    with self._strategy_lock:
                        if getattr(self, '_rollover_engine', None):
                            self._rollover_engine.process_before_strategy()
                        self.strategy_func(self.api)
                except Exception as e:
                    print(f"[策略执行错误] (WS K线触发) {e}")
                    import traceback
                    traceback.print_exc()
    
    def _on_ws_history(self, symbol: str, period: str, klines_list: list):
        """
        data_server WebSocket 历史K线预加载回调
        """
        # 查找对应的 LiveDataSource
        map_key = (symbol.lower(), period.upper())
        ds = self._ws_subscription_map.get(map_key)
        
        if not ds:
            return
        
        # 加载历史K线到数据源
        ds.on_ws_history(klines_list)
        
        # 预加载计数，全部到达后通知主线程
        with self._ws_preload_lock:
            self._ws_preload_received += 1
            if self._ws_preload_received >= self._ws_preload_expected:
                self._ws_preload_done.set()
    
    def _create_strategy_api(self):
        """创建策略API"""
        context = {
            'data': self.multi_data_source,
            'log': self._log,
            'params': self.strategy_params,
            'account_info': self.account_info,  # 账户信息引用
            'ctp_client': self.ctp_client,      # CTP客户端引用
            'runtime_state_getter': self.get_runtime_stats,
            'rollover_status_getter': lambda: (
                self._rollover_engine.get_status_snapshot()
                if getattr(self, '_rollover_engine', None)
                else {}
            ),
        }
        
        from ..api.strategy_api import create_strategy_api
        self.api = create_strategy_api(context)
    
    _TICK_QUEUE_OVERFLOW_LIMIT = 10000

    def _stash_overflow_tick(self, data: Dict):
        """主队列满时，仅保留每个品种的最新 tick。"""
        symbol = data.get('InstrumentID', '') or '__UNKNOWN__'
        with self._tick_overflow_lock:
            self._tick_overflow_latest[symbol] = data
            self._tick_overflow_count += 1
            buffer_size = len(self._tick_overflow_latest)
            overflow_total = self._tick_overflow_count
        self._update_runtime_state(
            overflow_buffer_size=buffer_size,
            overflow_total=overflow_total,
        )
        self._refresh_runtime_pressure()

        now = time.time()
        if now - self._tick_overflow_last_log >= 5:
            self._tick_overflow_last_log = now
            print(
                f"[实盘适配器] ⚠ Tick队列已满，切换为最新值缓存模式: "
                f"累计暂存 {overflow_total} 条，当前保留 {buffer_size} 个品种最新Tick"
            )

    def _flush_overflow_ticks(self):
        """当主队列回落后，将暂存的最新 tick 回灌。"""
        with self._tick_overflow_lock:
            if not self._tick_overflow_latest or self._tick_queue.qsize() > self._tick_queue_recover_limit:
                return
            pending = list(self._tick_overflow_latest.values())
            self._tick_overflow_latest.clear()
        self._update_runtime_state(overflow_buffer_size=0)

        restored = 0
        for item in pending:
            try:
                self._tick_queue.put_nowait(item)
                restored += 1
            except queue.Full:
                self._stash_overflow_tick(item)
                break

        if restored:
            print(f"[实盘适配器] ✓ Tick队列恢复，已回灌 {restored} 个品种的最新Tick")
        self._refresh_runtime_pressure()

    def _compact_tick_backlog(self, current_data: Dict) -> Dict:
        """高水位时压缩积压，只保留每个品种最新 tick。"""
        latest_by_symbol = {}
        current_symbol = current_data.get('InstrumentID', '') or '__UNKNOWN__'
        latest_by_symbol[current_symbol] = current_data
        drained = 0

        while True:
            try:
                pending = self._tick_queue.get_nowait()
                self._tick_queue.task_done()
                drained += 1
                symbol = pending.get('InstrumentID', '') or '__UNKNOWN__'
                latest_by_symbol[symbol] = pending
            except queue.Empty:
                break

        current_data = latest_by_symbol.pop(current_symbol, current_data)

        requeued = 0
        for pending in latest_by_symbol.values():
            try:
                self._tick_queue.put_nowait(pending)
                requeued += 1
            except queue.Full:
                self._stash_overflow_tick(pending)

        print(
            f"[实盘适配器] ⚠ Tick积压压缩: 清理 {drained} 条，仅保留 "
            f"{requeued + 1} 个品种的最新Tick"
        )
        runtime_stats = self.get_runtime_stats()
        self._update_runtime_state(compact_count=int(runtime_stats.get('compact_count', 0) or 0) + 1)
        self._refresh_runtime_pressure()
        return current_data

    def _on_market_data(self, data: Dict):
        """CTP 行情回调 — 只入队，立即返回，不阻塞 CTP 线程"""
        try:
            self._tick_queue.put_nowait(data)
        except queue.Full:
            self._stash_overflow_tick(data)
            return

        # 队列积压监控（轻量检查，不阻塞）
        qsize = self._tick_queue.qsize()
        if qsize > self._tick_queue_high_water:
            self._tick_queue_high_water = qsize
            if qsize > 500 and (qsize // 1000) > ((qsize - 1) // 1000):
                print(f"[实盘适配器] ⚠ Tick队列积压: {qsize}")
        self._refresh_runtime_pressure(qsize)
    
    def _tick_processing_loop(self):
        """Tick 处理线程 — 从队列消费 tick 并执行策略"""
        print("[Tick处理线程] 启动")
        while True:
            self._flush_overflow_ticks()
            try:
                data = self._tick_queue.get(timeout=1.0)
            except queue.Empty:
                if self._tick_thread_should_stop and self._tick_queue.empty():
                    break
                continue

            qsize = self._tick_queue.qsize()
            if qsize >= self._tick_queue_soft_limit:
                data = self._compact_tick_backlog(data)

            try:
                start_ts = time.perf_counter()
                self._process_tick_data(data)
                elapsed_ms = (time.perf_counter() - start_ts) * 1000
                runtime_stats = self.get_runtime_stats()
                prev_avg = float(runtime_stats.get('avg_process_ms', 0.0) or 0.0)
                avg_process_ms = elapsed_ms if prev_avg <= 0 else prev_avg * 0.9 + elapsed_ms * 0.1
                self._update_runtime_state(
                    last_process_ms=round(elapsed_ms, 2),
                    avg_process_ms=round(avg_process_ms, 2),
                )
                self._refresh_runtime_pressure()
            except Exception as e:
                print(f"[Tick处理线程] 处理异常: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._tick_queue.task_done()
        
        print("[Tick处理线程] 停止")
    
    def _process_tick_data(self, data: Dict):
        """处理单个 tick 数据（原 _on_market_data 的完整逻辑）"""
        symbol = data.get('InstrumentID', '')
        
        completed_kline = None
        target_data_source = None
        completed_klines = []
        
        for ds in self.multi_data_source.data_sources:
            if ds.symbol.upper() == symbol.upper():
                kline = ds.update_tick(data)
                if kline is not None:
                    completed_klines.append((ds, kline))
                    if completed_kline is None:
                        completed_kline = kline
                        target_data_source = ds
                elif target_data_source is None:
                    target_data_source = ds
        
        if target_data_source:
            self.multi_data_source._current_tick = data
            self.multi_data_source._current_tick_symbol = symbol
        
        # 记录数据
        if target_data_source:
            if not hasattr(self, '_symbol_tick_recorder'):
                self._symbol_tick_recorder = {}
                for key, recorder in self.data_recorders.items():
                    sym = key.rsplit('_', 1)[0]
                    sym_upper = sym.upper()
                    if sym_upper not in self._symbol_tick_recorder:
                        self._symbol_tick_recorder[sym_upper] = recorder
            
            symbol_upper = symbol.upper()
            if symbol_upper in self._symbol_tick_recorder:
                self._symbol_tick_recorder[symbol_upper].record_tick(data)
            
            for ds, kline in completed_klines:
                recorder_key = f"{ds.symbol}_{ds.kline_period}"
                if recorder_key in self.data_recorders:
                    self.data_recorders[recorder_key].record_kline(kline)
        
        if not self.running:
            return
        
        # ========== data_server + tick回调 节流 ==========
        # 当 kline_source='data_server' 且 enable_tick_callback=True 时，
        # 策略仅需在新K线到达或定时间隔触发，无需每个tick都调用。
        # 避免开盘tick洪峰（34品种同时推送）导致队列积压/假死。
        if self.enable_tick_callback and self._kline_source == 'data_server':
            now_mono = time.monotonic()
            ws_arrived = self._ws_kline_arrived.is_set()
            if ws_arrived:
                self._ws_kline_arrived.clear()
            
            qsize = self._tick_queue.qsize()
            throttle = max(self._tick_callback_interval, 2.0) if qsize > 500 else self._tick_callback_interval
            elapsed = now_mono - self._last_tick_strategy_ts
            
            if not ws_arrived and elapsed < throttle:
                if hasattr(self.multi_data_source, '_current_tick'):
                    delattr(self.multi_data_source, '_current_tick')
                if hasattr(self.multi_data_source, '_current_tick_symbol'):
                    delattr(self.multi_data_source, '_current_tick_symbol')
                return
            
            self._last_tick_strategy_ts = now_mono
        
        try:
            with self._strategy_lock:
                if getattr(self, '_rollover_engine', None):
                    self._rollover_engine.process_before_strategy()
                if self.enable_tick_callback:
                    self.strategy_func(self.api)
                
                if completed_kline is not None:
                    if not self.enable_tick_callback:
                        self.strategy_func(self.api)
        except Exception as e:
            print(f"[策略执行错误] {e}")
            import traceback
            traceback.print_exc()
        finally:
            if hasattr(self.multi_data_source, '_current_tick'):
                delattr(self.multi_data_source, '_current_tick')
            if hasattr(self.multi_data_source, '_current_tick_symbol'):
                delattr(self.multi_data_source, '_current_tick_symbol')
    
    def _on_trade(self, data: Dict):
        """成交回调"""
        # 方向映射
        direction = '买' if data['Direction'] == '0' else '卖'
        
        # 开平映射
        offset_flag = data.get('OffsetFlag', '0')
        offset_map = {
            '0': '开仓',
            '1': '平仓',
            '2': '强平',
            '3': '平今',
            '4': '平昨',
        }
        offset = offset_map.get(offset_flag, '开仓')
        
        symbol = data['InstrumentID']
        
        # 时间（CTP返回的格式是 HH:MM:SS，已带冒号）
        trade_time = data.get('TradeTime', '')
        # 如果已经包含冒号，直接使用；否则按 HHMMSS 格式处理
        if ':' in trade_time:
            time_str = trade_time
        elif trade_time and len(trade_time) >= 6:
            time_str = f"{trade_time[:2]}:{trade_time[2:4]}:{trade_time[4:6]}"
        else:
            time_str = trade_time
        
        print(f"\n✅ [成交] {time_str} {symbol} {direction}{offset} "
              f"价格={data['Price']:.2f} 数量={data['Volume']}")
        
        # 更新持仓：找到对应的数据源
        # 支持旧合约成交：如果数据源的 _old_contract 与成交合约匹配，也进行更新
        for ds in self.multi_data_source.data_sources:
            # 精确匹配或旧合约匹配（大小写不敏感）
            old_contract = getattr(ds, '_old_contract', None)
            is_match = (ds.symbol.upper() == symbol.upper()) or (old_contract and old_contract.upper() == symbol.upper())
            if is_match:
                volume = data['Volume']
                direction_flag = data['Direction']
                
                # 【调试】记录成交前的持仓
                old_current_pos = ds.current_pos
                old_today_pos = ds.today_pos
                old_yd_pos = ds.yd_pos
                
                # 初始化多空持仓（如果不存在）
                if not hasattr(ds, 'long_pos'):
                    ds.long_pos = 0
                    ds.short_pos = 0
                    ds.long_today = 0
                    ds.short_today = 0
                    ds.long_yd = 0
                    ds.short_yd = 0
                
                # 根据开平方向更新持仓
                if offset_flag == '0':  # 开仓
                    if direction_flag == '0':  # 买开
                        ds.current_pos += volume
                        ds.today_pos += volume  # 增加今仓（多头）
                        # 同步更新多空持仓
                        ds.long_pos += volume
                        ds.long_today += volume
                    else:  # 卖开
                        ds.current_pos -= volume
                        ds.today_pos -= volume  # 增加今仓（空头，负数）
                        # 同步更新多空持仓
                        ds.short_pos += volume
                        ds.short_today += volume
                        
                elif offset_flag == '3':  # 平今
                    if direction_flag == '0':  # 买平（平空头今仓）
                        ds.current_pos += volume
                        ds.today_pos += volume  # 空头今仓是负数，加volume就是减少绝对值
                        # 同步更新多空持仓
                        ds.short_pos = max(0, ds.short_pos - volume)
                        ds.short_today = max(0, ds.short_today - volume)
                    else:  # 卖平（平多头今仓）
                        ds.current_pos -= volume
                        ds.today_pos -= volume  # 多头今仓是正数，减volume
                        # 同步更新多空持仓
                        ds.long_pos = max(0, ds.long_pos - volume)
                        ds.long_today = max(0, ds.long_today - volume)
                        
                elif offset_flag == '4':  # 平昨
                    if direction_flag == '0':  # 买平（平空头昨仓）
                        ds.current_pos += volume
                        ds.yd_pos += volume  # 空头昨仓是负数，加volume就是减少绝对值
                        # 同步更新多空持仓
                        ds.short_pos = max(0, ds.short_pos - volume)
                        ds.short_yd = max(0, ds.short_yd - volume)
                    else:  # 卖平（平多头昨仓）
                        ds.current_pos -= volume
                        ds.yd_pos -= volume  # 多头昨仓是正数，减volume
                        # 同步更新多空持仓
                        ds.long_pos = max(0, ds.long_pos - volume)
                        ds.long_yd = max(0, ds.long_yd - volume)
                        
                elif offset_flag in ('1', '2'):  # 平仓/强平（需要判断是今仓还是昨仓）
                    # 更新净持仓
                    if direction_flag == '0':  # 买平
                        ds.current_pos += volume
                    else:  # 卖平
                        ds.current_pos -= volume
                    
                    # 判断平的是今仓还是昨仓（使用 short_today/long_today 而不是 today_pos）
                    if direction_flag == '0':  # 买平（平空头）
                        # 使用空头今仓判断（不是净今仓）
                        if ds.short_today > 0:
                            # 优先平今仓
                            reduce_volume = min(volume, ds.short_today)
                            ds.today_pos += reduce_volume  # 净今仓：空头减少 = 加
                            ds.short_today = max(0, ds.short_today - reduce_volume)
                            if volume > reduce_volume:
                                # 今仓不足，平昨仓
                                ds.yd_pos += (volume - reduce_volume)
                                ds.short_yd = max(0, ds.short_yd - (volume - reduce_volume))
                        else:
                            # 没有空头今仓，平昨仓
                            ds.yd_pos += volume
                            ds.short_yd = max(0, ds.short_yd - volume)
                        ds.short_pos = max(0, ds.short_pos - volume)
                    else:  # 卖平（平多头）
                        # 使用多头今仓判断（不是净今仓）
                        if ds.long_today > 0:
                            # 优先平今仓
                            reduce_volume = min(volume, ds.long_today)
                            ds.today_pos -= reduce_volume  # 净今仓：多头减少 = 减
                            ds.long_today = max(0, ds.long_today - reduce_volume)
                            if volume > reduce_volume:
                                # 今仓不足，平昨仓
                                ds.yd_pos -= (volume - reduce_volume)
                                ds.long_yd = max(0, ds.long_yd - (volume - reduce_volume))
                        else:
                            # 没有多头今仓，平昨仓
                            ds.yd_pos -= volume
                            ds.long_yd = max(0, ds.long_yd - volume)
                        ds.long_pos = max(0, ds.long_pos - volume)
                
                # 【关键】平仓成交后，检查是否已平完旧合约持仓
                # 如果已经没有持仓了，清除 _old_contract 标记
                if offset_flag != '0':  # 平仓操作
                    total_pos = getattr(ds, 'long_pos', 0) + getattr(ds, 'short_pos', 0)
                    if total_pos == 0 and hasattr(ds, '_old_contract'):
                        old_contract = ds._old_contract
                        del ds._old_contract
                        print(f"[换月平仓完成] {old_contract} 持仓已清空，已清除旧合约标记")
                
                break
        
        # 调用用户自定义的成交回调
        if self.on_trade_callback:
            try:
                self.on_trade_callback(data)
            except Exception as e:
                print(f"[用户成交回调错误] {e}")
    
    def _on_query_trade(self, data: Dict):
        """成交查询回调（单条记录）"""
        # 调用用户自定义的成交查询回调
        if self.on_query_trade_callback:
            try:
                self.on_query_trade_callback(data)
            except Exception as e:
                print(f"[用户成交查询回调错误] {e}")
    
    def _on_query_trade_complete(self):
        """成交查询完成回调"""
        if self.on_query_trade_complete_callback:
            try:
                self.on_query_trade_complete_callback()
            except Exception as e:
                print(f"[用户成交查询完成回调错误] {e}")

    def _on_query_order(self, data: Dict):
        """委托查询回调（单条记录）。"""
        self._sync_pending_order(data, inherit_retry_state=False)
        if self.on_query_order_callback:
            try:
                self.on_query_order_callback(data)
            except Exception as e:
                print(f"[用户委托查询回调错误] {e}")

    def _on_query_order_complete(self):
        """委托查询完成回调。"""
        if self.on_query_order_complete_callback:
            try:
                self.on_query_order_complete_callback()
            except Exception as e:
                print(f"[用户委托查询完成回调错误] {e}")
    
    @staticmethod
    def _algo_order_lookup_keys(order_like: Dict) -> List[str]:
        """用于超时撤单后匹配「重发」计划：OrderSysID 与 FrontID+SessionID+OrderRef。"""
        keys: List[str] = []
        osid = order_like.get('OrderSysID')
        if osid is not None and str(osid).strip() != '':
            keys.append(str(osid).strip())
        try:
            fr = order_like.get('FrontID')
            se = order_like.get('SessionID')
            ref = order_like.get('OrderRef', '')
            if fr is not None and se is not None and ref != '':
                keys.append(f"{fr}:{se}:{ref}")
        except Exception:
            pass
        return keys
    
    def _gc_algo_timeout_resend(self, now: Optional[float] = None) -> int:
        """清理超过 TTL 的重发登记，返回清理条数。
        
        TTL 由 self._algo_resend_plan_ttl 控制；<=0 视为关闭清理。
        以 plan['ts'] 为基准（同一 plan 多键的时间戳一致），过期时一并清掉所有指向该 plan 的键。
        """
        ttl = getattr(self, '_algo_resend_plan_ttl', 300.0) or 0.0
        if ttl <= 0:
            return 0
        if now is None:
            now = time.time()
        cutoff = now - ttl
        # 收集过期 plan 标识（用 id() 而非对象本身，避免后续 pop 影响识别）
        expired_plan_ids = set()
        for plan in self._algo_timeout_resend.values():
            if isinstance(plan, dict):
                ts = plan.get('ts', 0) or 0
                if ts and ts < cutoff:
                    expired_plan_ids.add(id(plan))
        if not expired_plan_ids:
            return 0
        # 把所有指向过期 plan 的键一并删除
        dead_keys = [k for k, p in self._algo_timeout_resend.items() if id(p) in expired_plan_ids]
        for k in dead_keys:
            self._algo_timeout_resend.pop(k, None)
        if dead_keys:
            ttl_disp = f"{ttl:.1f}s" if ttl < 10 else f"{ttl:.0f}s"
            print(f"[智能追单] 清理过期重发登记 {len(dead_keys)} 项（TTL={ttl_disp}）")
        return len(dead_keys)
    
    def register_algo_timeout_resend(self, ds: 'LiveDataSource', order: Dict, order_sys_id: str) -> None:
        """超时撤单前登记：撤单回报到达时凭多键查找并触发重发。"""
        if not getattr(ds, 'algo_trading', False):
            return
        # 入口顺手做一次 TTL 清理，避免长期运行时残留
        self._gc_algo_timeout_resend()
        merged = {**order, 'OrderSysID': order_sys_id or order.get('OrderSysID', '')}
        rc = ds.orders_to_resend.get(order_sys_id, 0)
        plan = {'ds': ds, 'retry_count': rc, 'ts': time.time()}
        for k in self._algo_order_lookup_keys(merged):
            if k:
                self._algo_timeout_resend[k] = plan
    
    def pop_algo_timeout_resend_plan(self, cancel_data: Dict):
        """撤单回报中解析键并取出重发计划（同一 plan 的多键一并清理）。"""
        # 命中前先清一次过期登记，避免 OrderRef 后缀兜底误匹到上一会话残留键（B3）
        self._gc_algo_timeout_resend()
        for k in self._algo_order_lookup_keys(cancel_data):
            if not k:
                continue
            plan = self._algo_timeout_resend.pop(k, None)
            if plan is None:
                continue
            dead = [kk for kk, pp in list(self._algo_timeout_resend.items()) if pp is plan]
            for kk in dead:
                self._algo_timeout_resend.pop(kk, None)
            return plan
        # 撤单回报里 OrderSysID 偶发为空且未带全 FrontID/SessionID 时，用 OrderRef 后缀匹配已登记的「前置:会话:报单引用」键
        ref = str(cancel_data.get('OrderRef') or '').strip()
        if ref:
            suffix = ':' + ref
            for k, plan in list(self._algo_timeout_resend.items()):
                if k.endswith(suffix):
                    self._algo_timeout_resend.pop(k, None)
                    dead = [kk for kk, pp in list(self._algo_timeout_resend.items()) if pp is plan]
                    for kk in dead:
                        self._algo_timeout_resend.pop(kk, None)
                    return plan
        return None
    
    # =========================================================================
    # 智能追单 · 重试次数继承队列（B4 修复）
    # =========================================================================
    # 背景：旧实现把"待继承的 retry_count"写到 ds._next_order_retry_count（全局标志位）。
    #       从重发提交（CTP send_order 返回）到新订单 OnRtnOrder 回调期间，如果策略其它路径恰好
    #       提交了一笔无关订单，会把那笔订单错认为重发的"接班人"，继承到错误的重试次数。
    # 修法：以 (InstrumentID, Direction, OffsetFlag[0]) 三元组在 TTL 内 FIFO 匹配；
    #       多品种/多方向/不同开平时彻底隔离；同 instrument+direction+offset 的并发新单仍然有
    #       竞争窗口，但相比"全局标志位"已经把误匹概率从"任意订单"缩小到"完全同方向同开平的
    #       并发订单"。`_next_order_retry_count` 保留作为兜底分支以兼容自定义/外部调用。

    def _gc_pending_inherit(self, now: Optional[float] = None) -> int:
        """清理超过 TTL 的继承登记。"""
        ttl = getattr(self, '_pending_inherit_ttl', 10.0) or 0.0
        if ttl <= 0 or not self._pending_inherit:
            return 0
        if now is None:
            now = time.time()
        cutoff = now - ttl
        before = len(self._pending_inherit)
        self._pending_inherit = [p for p in self._pending_inherit if (p.get('ts', 0) or 0) >= cutoff]
        n = before - len(self._pending_inherit)
        if n:
            ttl_disp = f"{ttl:.1f}s" if ttl < 10 else f"{ttl:.0f}s"
            print(f"[智能追单] 清理过期继承登记 {n} 项（TTL={ttl_disp}）")
        return n

    def _register_pending_inherit(self, instrument: str, direction: str, offset: str, retry_count: int) -> None:
        """登记下一笔同 (instrument, direction, offset) 订单需要继承的重试次数。"""
        self._gc_pending_inherit()
        self._pending_inherit.append({
            'instrument': instrument or '',
            'direction': direction or '',
            'offset': (offset or '0')[:1] or '0',
            'retry_count': int(retry_count),
            'ts': time.time(),
        })

    def _consume_pending_inherit(self, ds: 'LiveDataSource', data: Dict, order_sys_id: str) -> bool:
        """新订单进入 pending 时，按三元组在 TTL 内 FIFO 消耗一份待继承重试次数。命中返回 True。"""
        if not self._pending_inherit:
            return False
        self._gc_pending_inherit()
        instrument = data.get('InstrumentID', '') or ''
        direction = data.get('Direction', '') or ''
        offset_flag = data.get('CombOffsetFlag', '0') or '0'
        of0 = offset_flag[0] if offset_flag else '0'
        for i, p in enumerate(self._pending_inherit):
            if (p.get('instrument') == instrument
                    and p.get('direction') == direction
                    and p.get('offset') == of0):
                ds.orders_to_resend[order_sys_id] = p['retry_count']
                print(f"[智能追单] 订单 {order_sys_id} 已继承重试次数: {p['retry_count']} (三元组队列匹配)")
                self._pending_inherit.pop(i)
                return True
        return False
    
    def _execute_algo_resend_after_cancel(self, ds: 'LiveDataSource', retry_count: int, data: Dict) -> None:
        """撤单成功后按原方向/开平重发一笔（更激进 retry_offset_ticks）。"""
        offset_flag = data.get('CombOffsetFlag', '0') or '0'
        of0 = offset_flag[0] if offset_flag else '0'
        order_sys_id = data.get('OrderSysID', '') or ''
        volume_original = int(data.get('VolumeTotalOriginal', 0) or 0)
        volume_traded = int(data.get('VolumeTraded', 0) or 0)
        volume_left = volume_original - volume_traded
        
        if order_sys_id:
            ds.orders_to_resend.pop(order_sys_id, None)
        
        if retry_count >= ds.retry_limit:
            print(f"[智能追单] 达到最大重试次数 ({ds.retry_limit})，停止追单")
            return
        if volume_left <= 0:
            return
        
        print(f"[智能追单] 触发重发: 剩余重试次数 {ds.retry_limit - retry_count - 1}")
        retry_offset = ds.retry_offset_ticks
        
        # 【B4 修复】先登记三元组继承计划：(instrument, direction, offset[0])
        # 这样 _on_order 收到新订单时会按 instrument/direction/offset 精确匹配，避免在重发提交→新订单回报
        # 之间到达的"无关订单"被错认为接班人。`_next_order_retry_count` 保留作为最终兜底。
        instrument = data.get('InstrumentID', '') or getattr(ds, 'symbol', '') or ''
        direction = data.get('Direction', '') or ''
        self._register_pending_inherit(instrument, direction, of0, retry_count + 1)
        
        if data.get('Direction') == '0':
            if of0 == '0':
                ds.buy(volume=volume_left, reason=f"超时重发(#{retry_count + 1})", offset_ticks=retry_offset)
            else:
                ds.buycover(volume=volume_left, reason=f"超时重发(#{retry_count + 1})", offset_ticks=retry_offset)
        else:
            if of0 == '0':
                ds.sellshort(volume=volume_left, reason=f"超时重发(#{retry_count + 1})", offset_ticks=retry_offset)
            else:
                ds.sell(volume=volume_left, reason=f"超时重发(#{retry_count + 1})", offset_ticks=retry_offset)
        
        # 兜底：保留旧字段以兼容自定义/外部路径；_on_order 命中三元组时会主动清掉它防止双重继承
        ds._next_order_retry_count = retry_count + 1
    
    def _sync_pending_order(
        self, data: Dict, inherit_retry_state: bool = False
    ) -> None:
        """将活动委托同步到对应数据源，终态委托从缓存移除。"""
        symbol = data.get('InstrumentID', '')
        order_sys_id = data.get('OrderSysID', '')
        order_status = data.get('OrderStatus', '')

        for ds in self.multi_data_source.data_sources:
            if not _live_ds_matches_instrument_id(ds, symbol):
                continue
            if not order_sys_id:
                break

            if order_status in ['0', '2', '4', '5']:
                ds.pending_orders.pop(order_sys_id, None)
            elif order_status in ['1', '3', 'a']:
                if order_sys_id not in ds.pending_orders:
                    data['_local_insert_time'] = time.time()

                    if inherit_retry_state:
                        consumed = self._consume_pending_inherit(
                            ds, data, order_sys_id
                        )
                        if consumed:
                            if hasattr(ds, '_next_order_retry_count'):
                                ds._next_order_retry_count = 0
                        elif (
                            hasattr(ds, '_next_order_retry_count')
                            and ds._next_order_retry_count > 0
                        ):
                            ds.orders_to_resend[order_sys_id] = (
                                ds._next_order_retry_count
                            )
                            ds._next_order_retry_count = 0
                            print(
                                f"[智能追单] 订单 {order_sys_id} 已继承重试次数: "
                                f"{ds.orders_to_resend[order_sys_id]} (兜底)"
                            )
                else:
                    data['_local_insert_time'] = ds.pending_orders[
                        order_sys_id
                    ].get('_local_insert_time', time.time())
                ds.pending_orders[order_sys_id] = data
            break

    def _on_order(self, data: Dict):
        """报单回调"""
        # 状态映射
        status_map = {
            '0': '全部成交',
            '1': '部分成交还在队列中',
            '3': '未成交还在队列中',
            '5': '撤单',
        }
        status = status_map.get(data['OrderStatus'], f"未知({data['OrderStatus']})")
        
        # 方向映射
        direction_map = {
            '0': '买',
            '1': '卖',
        }
        direction = direction_map.get(data.get('Direction', ''), '未知')
        
        # 开平映射
        offset_flag = data.get('CombOffsetFlag', '0')
        if offset_flag:
            offset_map = {
                '0': '开仓',
                '1': '平仓',
                '3': '平今',
                '4': '平昨',
            }
            offset = offset_map.get(offset_flag[0] if offset_flag else '0', '未知')
        else:
            offset = '开仓'
        
        # 时间（CTP返回的格式是 HH:MM:SS，已带冒号）
        insert_time = data.get('InsertTime', '')
        # 如果已经包含冒号，直接使用；否则按 HHMMSS 格式处理
        if ':' in insert_time:
            time_str = insert_time
        elif insert_time and len(insert_time) >= 6:
            time_str = f"{insert_time[:2]}:{insert_time[2:4]}:{insert_time[4:6]}"
        else:
            time_str = insert_time
        
        # 价格和数量
        price = data.get('LimitPrice', 0)
        volume_original = data.get('VolumeTotalOriginal', 0)
        volume_traded = data.get('VolumeTraded', 0)
        
        print(f"[报单] {time_str} {data['InstrumentID']} {direction}{offset} "
              f"价格={price:.2f} 数量={volume_original} 已成交={volume_traded} 状态={status}")
        
        self._sync_pending_order(data, inherit_retry_state=True)
        
        # 调用用户自定义的报单回调
        if self.on_order_callback:
            try:
                self.on_order_callback(data)
            except Exception as e:
                print(f"[用户报单回调错误] {e}")
    
    def _on_cancel(self, data: Dict):
        """撤单回调"""
        # 方向映射
        direction_map = {
            '0': '买',
            '1': '卖',
        }
        direction = direction_map.get(data.get('Direction', ''), '未知')
        
        # 开平映射
        offset_flag = data.get('CombOffsetFlag', '0')
        if offset_flag:
            offset_map = {
                '0': '开仓',
                '1': '平仓',
                '3': '平今',
                '4': '平昨',
            }
            offset = offset_map.get(offset_flag[0] if offset_flag else '0', '未知')
        else:
            offset = '开仓'
        
        symbol = data['InstrumentID']
        price = data.get('LimitPrice', 0)
        volume_original = data.get('VolumeTotalOriginal', 0)
        volume_traded = data.get('VolumeTraded', 0)
        order_sys_id = data.get('OrderSysID', '')
        
        # 时间（CTP返回的格式是 HH:MM:SS，已带冒号）
        cancel_time = data.get('CancelTime', '')
        # 如果已经包含冒号，直接使用；否则按 HHMMSS 格式处理
        if ':' in cancel_time:
            time_str = cancel_time
        elif cancel_time and len(cancel_time) >= 6:
            time_str = f"{cancel_time[:2]}:{cancel_time[2:4]}:{cancel_time[4:6]}"
        else:
            time_str = cancel_time
        
        print(f"\n🚫 [撤单成功] {time_str} {symbol} {direction}{offset} "
              f"价格={price:.2f} 数量={volume_original} 已成交={volume_traded} 订单号={order_sys_id}")
        
        # 智能追单：优先用超时前登记的 plan（支持 OrderSysID 为空时用 FrontID+SessionID+OrderRef 匹配）
        plan = self.pop_algo_timeout_resend_plan(data)
        if plan:
            self._execute_algo_resend_after_cancel(plan['ds'], plan['retry_count'], data)
        else:
            for ds in self.multi_data_source.data_sources:
                if _live_ds_matches_instrument_id(ds, symbol) and order_sys_id and order_sys_id in ds.orders_to_resend:
                    retry_count = ds.orders_to_resend.pop(order_sys_id)
                    self._execute_algo_resend_after_cancel(ds, retry_count, data)
                    break

        # 调用用户自定义的撤单回调
        if self.on_cancel_callback:
            try:
                self.on_cancel_callback(data)
            except Exception as e:
                print(f"[用户撤单回调错误] {e}")
    
    def _on_position(self, data: Dict):
        """持仓回调 - 处理CTP返回的持仓数据（累加模式）
        
        注意：CTP 返回的是持仓明细，同一合约可能有多条记录（不同开仓日期）
        需要累加所有 Position > 0 的记录，忽略 Position = 0 的记录
        
        修复：使用 _position_seen_keys 跟踪当前查询周期已见过的 key，
        每个 key 首次出现时先清理旧数据再写入，防止部分查询时重复累加。
        """
        symbol = data['InstrumentID']
        posi_direction = data['PosiDirection']
        position = data.get('Position', 0)
        today_pos = data.get('TodayPosition', 0)
        yd_pos = position - today_pos
        
        if not hasattr(self, '_position_cache'):
            self._position_cache = {}
        if not hasattr(self, '_position_seen_keys'):
            self._position_seen_keys = set()
        
        cache_key = (symbol, posi_direction)
        
        if position > 0:
            if cache_key not in self._position_seen_keys:
                # 当前查询周期首次见到此 key → 清理旧数据后写入（防止部分查询累加翻倍）
                self._position_cache[cache_key] = {
                    'position': position,
                    'today': today_pos,
                    'yd': yd_pos
                }
                self._position_seen_keys.add(cache_key)
            else:
                # 同一查询周期的后续记录 → 正常累加（CTP 同一合约可能分多条返回）
                self._position_cache[cache_key]['position'] += position
                self._position_cache[cache_key]['today'] += today_pos
                self._position_cache[cache_key]['yd'] += yd_pos
        
        # 调用用户自定义的持仓回调
        if self.on_position_callback:
            try:
                self.on_position_callback(data)
            except Exception as e:
                print(f"[用户持仓回调错误] {e}")
    
    def _on_position_complete(self):
        """
        持仓查询完成回调 - 合并多空持仓
        
        注意：CTP会在每个品种查询完成时调用此方法
        我们使用计数器来判断是否所有品种都查询完成
        """
        # 初始化完成计数器（如果不存在）
        if not hasattr(self, '_position_query_complete_count'):
            self._position_query_complete_count = 0
        
        self._position_query_complete_count += 1
        
        # 获取需要查询的品种数量
        if hasattr(self, '_pending_position_queries'):
            expected_count = len(self._pending_position_queries)
        else:
            expected_count = 1  # 单品种模式
        
        # 只有当所有品种都查询完成后才合并持仓
        if self._position_query_complete_count < expected_count:
            return
        
        # 重置计数器和查询周期跟踪
        self._position_query_complete_count = 0
        if hasattr(self, '_position_seen_keys'):
            self._position_seen_keys.clear()
        
        # 从适配器级别的缓存中提取持仓数据
        # _position_cache: {(symbol, direction): {position, today, yd}}
        position_cache = getattr(self, '_position_cache', {})
        
        # 按品种汇总多空持仓（使用大写键统一存储，解决大小写不敏感匹配）
        symbol_positions = {}  # {symbol_upper: {long, short, long_today, ...}}
        symbol_original = {}   # {symbol_upper: original_symbol} 保存原始大小写
        
        for (symbol, direction), pos_data in position_cache.items():
            symbol_upper = symbol.upper()
            if symbol_upper not in symbol_positions:
                symbol_positions[symbol_upper] = {
                    'long': 0, 'short': 0,
                    'long_today': 0, 'short_today': 0,
                    'long_yd': 0, 'short_yd': 0
                }
                symbol_original[symbol_upper] = symbol
            
            if direction == '2':  # 多头
                symbol_positions[symbol_upper]['long'] = pos_data['position']
                symbol_positions[symbol_upper]['long_today'] = pos_data['today']
                symbol_positions[symbol_upper]['long_yd'] = pos_data['yd']
            elif direction == '3':  # 空头
                symbol_positions[symbol_upper]['short'] = pos_data['position']
                symbol_positions[symbol_upper]['short_today'] = pos_data['today']
                symbol_positions[symbol_upper]['short_yd'] = pos_data['yd']
        
        # 【调试】打印查询到的持仓数据
        if symbol_positions:
            print(f"[持仓查询] CTP返回的持仓数据:")
            for sym_upper, pos_data in symbol_positions.items():
                orig_sym = symbol_original.get(sym_upper, sym_upper)
                long_pos = pos_data.get('long', 0)
                short_pos = pos_data.get('short', 0)
                if long_pos > 0 or short_pos > 0:
                    print(f"  - {orig_sym}: 多头={long_pos}手, 空头={short_pos}手")
        
        # 【辅助函数】提取品种代码（去除数字后缀）
        def extract_variety_code(symbol: str) -> str:
            """从合约代码提取品种代码，如 SC2603 -> SC"""
            import re
            match = re.match(r'^([a-zA-Z]+)', symbol)
            return match.group(1).upper() if match else symbol.upper()
        
        # 构建品种代码到持仓数据的映射（用于模糊匹配旧合约）
        variety_positions = {}  # {variety_upper: {symbol_upper: pos_data}}
        for sym_upper, pos_data in symbol_positions.items():
            variety = extract_variety_code(sym_upper)
            if variety not in variety_positions:
                variety_positions[variety] = {}
            variety_positions[variety][sym_upper] = pos_data
        
        # 将持仓数据同步到所有数据源
        # 优先精确匹配，如果没匹配到则按品种代码模糊匹配（支持旧合约换月）
        for ds in self.multi_data_source.data_sources:
            symbol_upper = ds.symbol.upper()
            pos_data = symbol_positions.get(symbol_upper, {})
            
            # 【关键修复】如果精确匹配没有持仓，尝试按品种代码模糊匹配
            # 这样旧合约（如SC2603）的持仓可以同步到新合约（如SC2604）的数据源
            if not pos_data or (pos_data.get('long', 0) == 0 and pos_data.get('short', 0) == 0):
                ds_variety = extract_variety_code(symbol_upper)
                if ds_variety in variety_positions:
                    # 找到该品种的所有持仓合约
                    variety_contracts = variety_positions[ds_variety]
                    for contract_upper, contract_pos in variety_contracts.items():
                        # 只同步有持仓的合约（避免覆盖已有持仓）
                        if contract_pos.get('long', 0) > 0 or contract_pos.get('short', 0) > 0:
                            if contract_upper != symbol_upper:
                                # 找到旧合约持仓，同步到当前数据源
                                pos_data = contract_pos
                                orig_sym = symbol_original.get(contract_upper, contract_upper)
                                print(f"[持仓同步] 旧合约 {orig_sym} 的持仓已同步到数据源 {ds.symbol}")
                                # 【重要】保存旧合约代码，平仓时需要使用
                                ds._old_contract = orig_sym
                            break
            
            long_pos = pos_data.get('long', 0)
            short_pos = pos_data.get('short', 0)
            long_today = pos_data.get('long_today', 0)
            short_today = pos_data.get('short_today', 0)
            long_yd = pos_data.get('long_yd', 0)
            short_yd = pos_data.get('short_yd', 0)
            
            # 计算净持仓
            net_pos = long_pos - short_pos
            net_today = long_today - short_today
            net_yd = long_yd - short_yd
            
            # 更新到数据源
            ds.current_pos = net_pos
            ds.today_pos = net_today
            ds.yd_pos = net_yd
            ds.long_pos = long_pos
            ds.short_pos = short_pos
            ds.long_today = long_today
            ds.short_today = short_today
            ds.long_yd = long_yd
            ds.short_yd = short_yd
        
        # 调用用户自定义的持仓查询完成回调
        if self.on_position_complete_callback:
            try:
                self.on_position_complete_callback()
            except Exception as e:
                print(f"[用户持仓查询完成回调错误] {e}")
        
        # 设置持仓查询完成事件
        self._position_query_done.set()
    
    def _on_order_error(self, error_id: int, error_msg: str, instrument_id: str = ""):
        """订单错误回调"""
        # 添加常见错误码说明（简洁版，只用中文描述）
        error_descriptions = {
            22: "合约不存在或未订阅",
            23: "报单价格不合法",
            30: "平仓数量超出持仓数量",
            31: "报单超过最大下单量",
            36: "资金不足",
            42: "成交价格不合法",
            44: "价格超出涨跌停板限制",
            50: "平今仓位不足，请改用平昨仓",
            51: "持仓不足或持仓方向错误",
            58: "报单已撤销",
            63: "重复报单",
            68: "每秒报单数超过限制",
            76: "撤单已提交到交易所，请稍后",
            81: "风控原因拒绝报单",
            85: "非法报单，CTP拒绝",
            90: "休眠时间不允许报单",
            91: "错误的开仓标志",
            95: "CTP不支持的价格类型（限价单/市价单）",
        }
        
        # 优先使用简洁的中文描述
        desc = error_descriptions.get(error_id, error_msg or "未知错误")
        symbol_str = f" {instrument_id}" if instrument_id else ""
        print(f"❌ [订单错误]{symbol_str} 错误码={error_id} - {desc}")
        
        # 调用用户自定义的报单错误回调
        if self.on_order_error_callback:
            try:
                self.on_order_error_callback({
                    'ErrorID': error_id,
                    'ErrorMsg': desc,
                    'InstrumentID': instrument_id
                })
            except Exception as e:
                print(f"[用户报单错误回调错误] {e}")
    
    def _on_cancel_error(self, error_id: int, error_msg: str):
        """撤单错误回调"""
        # 常见撤单错误码
        error_descriptions = {
            25: "撤单报单已全成交",
            26: "撤单被拒绝：订单已成交",
            76: "撤单已提交到交易所，请稍后",
            77: "撤单报单被拒绝：没有可撤的单",
        }
        
        desc = error_descriptions.get(error_id, "")
        if desc:
            print(f"❌ [撤单错误] 错误码={error_id} - {desc}")
        else:
            print(f"❌ [撤单错误] 错误码={error_id} - {error_msg}")
        
        # 调用用户自定义的撤单错误回调
        if self.on_cancel_error_callback:
            try:
                self.on_cancel_error_callback({
                    'ErrorID': error_id,
                    'ErrorMsg': desc or str(error_msg)
                })
            except Exception as e:
                print(f"[用户撤单错误回调错误] {e}")
    
    def _on_disconnect(self, source: str, reason: int):
        """
        连接断开回调
        
        Args:
            source: 断开的连接类型，'md'=行情服务器, 'trader'=交易服务器
            reason: 断开原因代码（CTP定义的错误码）
        """
        source_name = '行情服务器' if source == 'md' else '交易服务器'
        
        # 断开原因说明
        reason_map = {
            0x1001: '网络读取失败',
            0x1002: '网络写入失败', 
            0x2001: '接收心跳超时',
            0x2002: '发送心跳超时',
            0x2003: '收到错误报文',
        }
        reason_desc = reason_map.get(reason, '未知原因')
        
        print(f"\n{'!' * 60}")
        print(f"[CTP断开] {source_name} 连接断开!")
        print(f"[CTP断开] 原因码: {reason:#x} ({reason}) - {reason_desc}")
        print(f"{'!' * 60}\n")
        
        # 调用用户自定义的断开连接回调
        if self.on_disconnect_callback:
            try:
                self.on_disconnect_callback(source, reason)
            except Exception as e:
                print(f"[用户断开回调错误] {e}")
    
    def _on_account(self, data: Dict):
        """账户资金回调"""
        # 更新内部账户信息
        self.account_info = {
            'balance': data.get('Balance', 0),
            'available': data.get('Available', 0),
            'position_profit': data.get('PositionProfit', 0),
            'close_profit': data.get('CloseProfit', 0),
            'commission': data.get('Commission', 0),
            'frozen_margin': data.get('FrozenMargin', 0),
            'curr_margin': data.get('CurrMargin', 0),
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # 调用用户自定义的账户回调
        if self.on_account_callback:
            try:
                self.on_account_callback(data)
            except Exception as e:
                print(f"[用户账户回调错误] {e}")
    
    def _log(self, message: str):
        """日志输出"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    def stop(self):
        """停止运行"""
        print("\n[实盘适配器] 停止运行...")
        self.running = False
        self._tick_thread_should_stop = True
        
        # 等待 tick 处理线程消费完剩余 tick
        if self._tick_thread and self._tick_thread.is_alive():
            print("[实盘适配器] 等待Tick处理线程结束...")
            self._tick_thread.join(timeout=5)
        
        # 关闭 data_server WebSocket 客户端
        if self.ws_kline_client:
            print("[实盘适配器] 断开 data_server WebSocket...")
            self.ws_kline_client.close()
            self.ws_kline_client = None
        
        # 保存所有数据源的当前未完成K线（仅本地聚合模式有 current_kline）
        if self.multi_data_source:
            for ds in self.multi_data_source.data_sources:
                recorder_key = f"{ds.symbol}_{ds.kline_period}"
                if ds.current_kline is not None and recorder_key in self.data_recorders:
                    print(f"[数据记录器] 保存 {recorder_key} 当前未完成的K线")
                    self.data_recorders[recorder_key].record_kline(ds.current_kline)
        
        # 等待所有数据写入完成
        for symbol, recorder in self.data_recorders.items():
            recorder.flush_all()
        
        # 停止后台写入线程
        DataRecorder.stop_write_thread()
        
        if getattr(self, '_rollover_engine', None) and hasattr(self._rollover_engine, '_audit'):
            try:
                self._rollover_engine._audit.close()
            except Exception:
                pass
        
        # 释放CTP资源
        if self.ctp_client:
            self.ctp_client.release()
        
        print("[实盘适配器] 已停止")
