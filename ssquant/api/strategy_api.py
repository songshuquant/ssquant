import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union, Callable

class StrategyAPI:
    """
    策略API核心类，只提供数据访问和交易操作，不包含指标计算
    """
    
    def __init__(self, context: Dict):
        """
        初始化策略API
        
        Args:
            context: 策略上下文，包含数据源、日志函数和参数等
        """
        self._context = context
        self._data = context['data']
        self._log = context['log']
        self._params = context.get('params', {})
        self._account_info = context.get('account_info', None)  # 账户信息引用
        self._ctp_client = context.get('ctp_client', None)      # CTP客户端引用
        self._runtime_state_getter = context.get('runtime_state_getter', None)
        self._rollover_status_getter = context.get('rollover_status_getter', None)
        
    def log(self, message: str):
        """
        记录日志
        
        Args:
            message: 日志消息
        """
        self._log(message)
        
    def get_params(self) -> Dict:
        """
        获取策略参数
        
        Returns:
            策略参数字典
        """
        return self._params
    
    def get_param(self, key: str, default=None):
        """
        获取指定参数
        
        Args:
            key: 参数名
            default: 默认值
            
        Returns:
            参数值，如果不存在则返回默认值
        """
        return self._params.get(key, default)

    def get_runtime_stats(self) -> Dict[str, Any]:
        """
        获取运行时状态快照（队列积压、处理耗时、压力等级等）。
        """
        if callable(self._runtime_state_getter):
            try:
                return self._runtime_state_getter() or {}
            except Exception:
                return {}
        return {}

    def get_runtime_pressure(self) -> str:
        """
        获取运行时压力等级：normal / busy / critical
        """
        return str(self.get_runtime_stats().get('pressure_level', 'normal'))

    def get_rollover_status(self) -> Dict[str, Any]:
        """
        获取框架自动换月（移仓）状态快照（仅实盘/SIMNOW 且已启用引擎时有效）。

        返回结构示例：``{'per_source': {'0': { ... }}}``。每项可含：
        ``sent_for``、``expected_vol``、``expected_dir``、``wait_invocations``、
        ``seq_phase``（``''`` / ``wait_close`` / ``wait_open``，仅 sequential 模式有阶段）。
        """
        if callable(self._rollover_status_getter):
            try:
                return self._rollover_status_getter() or {}
            except Exception:
                return {}
        return {}

    def is_rollover_busy(self, index: int = 0) -> bool:
        """
        当前数据源是否处于移仓等待闭环（已发移仓单、尚未确认完成）。

        依据 ``sent_for`` 非空；含 sequential 下「仅平旧已发」或「已发开新待成交」等阶段。
        """
        per = self.get_rollover_status().get('per_source', {})
        st = per.get(str(index), {})
        return bool(st.get('sent_for'))

    def is_runtime_under_pressure(self, level: str = 'busy') -> bool:
        """
        判断当前是否达到指定压力等级及以上。
        """
        order = {'normal': 0, 'busy': 1, 'critical': 2}
        current = self.get_runtime_pressure()
        return order.get(current, 0) >= order.get(level, 1)
    
    def get_data_source(self, index: int = 0):
        """
        获取指定索引的数据源
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            数据源对象，如果索引无效则返回None
        """
        if index < len(self._data):
            return self._data[index]
        self.log(f"错误：数据源索引 {index} 超出范围，数据源数量: {len(self._data)}")
        return None
    
    def get_data_sources_count(self) -> int:
        """
        获取数据源数量
        
        Returns:
            数据源数量
        """
        return len(self._data)
    
    def require_data_sources(self, count: int) -> bool:
        """
        确保至少有指定数量的数据源
        
        Args:
            count: 最少需要的数据源数量
            
        Returns:
            是否满足要求
        """
        if len(self._data) < count:
            self.log(f"策略需要至少 {count} 个数据源，当前只有 {len(self._data)} 个")
            return False
        return True
    
    def get_klines(self, index: int = 0, window: int = None) -> pd.DataFrame:
        """
        获取指定数据源的K线数据
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            window: 滑动窗口大小，None表示使用配置的lookback_bars，0表示不限制
            
        Returns:
            K线数据DataFrame，最多返回window条（从最近往前）
            
        示例:
            # 使用配置的lookback_bars
            klines = api.get_klines(0)
            
            # 指定获取最近100条
            klines = api.get_klines(0, window=100)
            
            # 获取全部数据（忽略lookback_bars配置）
            klines = api.get_klines(0, window=0)
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_klines(window=window)
        return pd.DataFrame()
    
    def get_datetime(self, index: int = 0):
        """
        获取当前日期时间
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前日期时间
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_current_datetime()
        return None
    
    # 保留旧方法名，但标记为废弃
    def get_current_datetime(self, index: int = 0):
        """
        获取当前日期时间（已废弃，请使用get_datetime）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前日期时间
        """
        return self.get_datetime(index)
    
    def get_price(self, index: int = 0) -> Optional[float]:
        """
        获取当前策略价格。

        在 data_server + 本地复权场景下，该值会尽量与
        `get_klines()` / `get_close()` 返回的价格口径一致；
        如果需要原始未复权价格，请使用 `get_raw_price()`。
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前价格，如果数据源无效则返回None
        """
        ds = self.get_data_source(index)
        if ds:
            if hasattr(ds, 'get_strategy_price'):
                return ds.get_strategy_price()
            return ds.get_current_price()
        return None

    def get_raw_price(self, index: int = 0) -> Optional[float]:
        """
        获取原始未复权价格（更接近底层行情/委托定价口径）。
        """
        ds = self.get_data_source(index)
        if ds:
            if hasattr(ds, 'get_raw_price'):
                return ds.get_raw_price()
            return ds.get_current_price()
        return None
    
    # 保留旧方法名，但标记为废弃
    def get_current_price(self, index: int = 0) -> Optional[float]:
        """
        获取当前价格（已废弃，请使用get_price）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前价格，如果数据源无效则返回None
        """
        return self.get_price(index)
    
    def get_pos(self, index: int = 0) -> int:
        """
        获取当前持仓（净持仓：多头-空头）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前持仓，如果数据源无效则返回0
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_current_pos()
        return 0
    
    def get_long_pos(self, index: int = 0) -> int:
        """
        获取多头持仓
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            多头持仓数量
        """
        ds = self.get_data_source(index)
        if ds and hasattr(ds, 'long_pos'):
            return ds.long_pos
        return 0
    
    def get_short_pos(self, index: int = 0) -> int:
        """
        获取空头持仓
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            空头持仓数量
        """
        ds = self.get_data_source(index)
        if ds and hasattr(ds, 'short_pos'):
            return ds.short_pos
        return 0
    
    def get_position_detail(self, index: int = 0) -> dict:
        """
        获取详细持仓信息（包含多空分离数据）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            持仓详情字典，包含以下字段：
            - net_pos: 净持仓（多头-空头）
            - long_pos: 多头持仓
            - short_pos: 空头持仓
            - today_pos: 今仓（净）
            - yd_pos: 昨仓（净）
            - long_today: 多头今仓
            - short_today: 空头今仓
            - long_yd: 多头昨仓
            - short_yd: 空头昨仓
        """
        ds = self.get_data_source(index)
        if ds:
            return {
                'net_pos': ds.current_pos,
                'long_pos': getattr(ds, 'long_pos', 0),
                'short_pos': getattr(ds, 'short_pos', 0),
                'today_pos': ds.today_pos,
                'yd_pos': ds.yd_pos,
                'long_today': getattr(ds, 'long_today', 0),
                'short_today': getattr(ds, 'short_today', 0),
                'long_yd': getattr(ds, 'long_yd', 0),
                'short_yd': getattr(ds, 'short_yd', 0),
            }
        return {
            'net_pos': 0, 'long_pos': 0, 'short_pos': 0,
            'today_pos': 0, 'yd_pos': 0,
            'long_today': 0, 'short_today': 0,
            'long_yd': 0, 'short_yd': 0,
        }
    
    # 保留旧方法名，但标记为废弃
    def get_current_pos(self, index: int = 0) -> int:
        """
        获取当前持仓（已废弃，请使用get_pos）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前持仓，如果数据源无效则返回0
        """
        return self.get_pos(index)
    
    def get_idx(self, index: int = 0) -> int:
        """
        获取当前索引
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前索引，如果数据源无效则返回-1
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.current_idx
        return -1
    
    # 保留旧方法名，但标记为废弃
    def get_current_idx(self, index: int = 0) -> int:
        """
        获取当前索引（已废弃，请使用get_idx）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前索引，如果数据源无效则返回-1
        """
        return self.get_idx(index)
    
    def get_close(self, index: int = 0) -> pd.Series:
        """
        获取收盘价序列
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            收盘价序列
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_close()
        return pd.Series()
    
    def get_open(self, index: int = 0) -> pd.Series:
        """
        获取开盘价序列
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            开盘价序列
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_open()
        return pd.Series()
    
    def get_high(self, index: int = 0) -> pd.Series:
        """
        获取最高价序列
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            最高价序列
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_high()
        return pd.Series()
    
    def get_low(self, index: int = 0) -> pd.Series:
        """
        获取最低价序列
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            最低价序列
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_low()
        return pd.Series()
    
    def get_volume(self, index: int = 0) -> pd.Series:
        """
        获取成交量序列
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            成交量序列
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_volume()
        return pd.Series()

    # ====== 方式二：NumPy 数组直读接口（零拷贝、不构造 Series） ======
    # 与 get_close()/get_open()/... 语义完全一致，仅返回 ndarray 而非 pd.Series。
    # 推荐在策略热路径里使用：rolling/iloc 改成 arr[-N:].mean() 之类，主循环
    # strategy_func 段可加速 5-10×。回测和实盘共享同一接口，无未来数据泄漏。
    def get_close_array(self, window: int = None, index: int = 0) -> np.ndarray:
        """获取收盘价 ndarray 视图（零拷贝）。

        Args:
            window: 滑动窗口大小，None=使用 lookback_bars 配置，0=不限制
            index: 数据源索引，默认 0

        Returns:
            截至当前 Bar 的 close ndarray（不含未来数据）
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_close_array(window)
        return np.empty(0, dtype=np.float64)

    def get_open_array(self, window: int = None, index: int = 0) -> np.ndarray:
        """获取开盘价 ndarray 视图（零拷贝）。"""
        ds = self.get_data_source(index)
        if ds:
            return ds.get_open_array(window)
        return np.empty(0, dtype=np.float64)

    def get_high_array(self, window: int = None, index: int = 0) -> np.ndarray:
        """获取最高价 ndarray 视图（零拷贝）。"""
        ds = self.get_data_source(index)
        if ds:
            return ds.get_high_array(window)
        return np.empty(0, dtype=np.float64)

    def get_low_array(self, window: int = None, index: int = 0) -> np.ndarray:
        """获取最低价 ndarray 视图（零拷贝）。"""
        ds = self.get_data_source(index)
        if ds:
            return ds.get_low_array(window)
        return np.empty(0, dtype=np.float64)

    def get_volume_array(self, window: int = None, index: int = 0) -> np.ndarray:
        """获取成交量 ndarray 视图（零拷贝）。"""
        ds = self.get_data_source(index)
        if ds:
            return ds.get_volume_array(window)
        return np.empty(0, dtype=np.float64)

    # ====== 方式一：IndicatorCache 注册式 API（最高性能档位） ======
    # 推荐用法（在 strategy.initialize(api) 钩子里一次性注册）：
    #
    #     def initialize(api):
    #         api.register_indicator(
    #             'sma_20',
    #             lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
    #             window=20,
    #         )
    #
    # 主循环里 O(1) 查询：
    #
    #     def strategy(api):
    #         sma_now = api.get_indicator('sma_20')  # 标量 float
    #         sma_arr = api.get_indicator_array('sma_20', window=2)  # 最近 2 根
    @staticmethod
    def _ensure_ds_supports_indicator_cache(ds, method_name: str):
        """护栏：确保数据源实现了 IndicatorCache 接口。

        v2 起 DataSource（回测）+ LiveDataSource（SIMNOW/实盘）均已实现。
        若用户用了第三方/旧版数据源没有这些方法，抛清晰错误而不是裸 AttributeError。
        """
        if not hasattr(ds, method_name):
            raise RuntimeError(
                f"数据源 {type(ds).__name__} 未实现 IndicatorCache 接口 ({method_name})。"
                f"请确认你使用的是 SSQuant 内置 DataSource（回测）或 LiveDataSource（实盘/SIMNOW），"
                f"并升级到支持 IndicatorCache v2 的版本。"
            )

    def register_indicator(self, name: str, func: Callable,
                           window: Optional[int] = None,
                           index: int = 0) -> np.ndarray:
        """注册一个自定义指标，引擎自动预计算 + 保持最新。

        【三档统一可用】v2 起回测/SIMNOW/实盘均可使用：
          - 回测：set_data() 后立即一次性预计算全量
          - SIMNOW/实盘：每根新 K 线写入后基于 deque 全量重算（O(maxlen)，~ms 级）
          - 数值与回测路径逐位等价（用户一份代码两边都能跑）

        Args:
            name: 指标名（同一数据源内唯一，重名覆盖）
            func: 计算函数 func(close, open, high, low, volume) -> np.ndarray
                  必须返回与输入等长的数组，可包含 NaN（前 N 根没法算的位置）
            window: 该指标依赖的最大窗口（元信息，目前主要用于文档/调试）
            index: 数据源索引

        Returns:
            np.ndarray: 当前缓存下预计算好的指标数组
        """
        ds = self.get_data_source(index)
        if ds is None:
            return np.empty(0, dtype=np.float64)
        self._ensure_ds_supports_indicator_cache(ds, 'register_indicator')
        return ds.register_indicator(name, func, window=window)

    def unregister_indicator(self, name: str, index: int = 0) -> bool:
        """移除一个已注册指标。"""
        ds = self.get_data_source(index)
        if ds is None:
            return False
        self._ensure_ds_supports_indicator_cache(ds, 'unregister_indicator')
        return ds.unregister_indicator(name)

    def get_indicator(self, name: str, index: int = 0) -> float:
        """获取已注册指标在当前 Bar 的标量值，O(1)。"""
        ds = self.get_data_source(index)
        if ds is None:
            return float('nan')
        self._ensure_ds_supports_indicator_cache(ds, 'get_indicator')
        return ds.get_indicator(name)

    def get_indicator_array(self, name: str, window: int = None,
                            index: int = 0) -> np.ndarray:
        """获取已注册指标的最近 window 个值（ndarray 视图，零拷贝）。"""
        ds = self.get_data_source(index)
        if ds is None:
            return np.empty(0, dtype=np.float64)
        self._ensure_ds_supports_indicator_cache(ds, 'get_indicator_array')
        return ds.get_indicator_array(name, window=window)
    
    def buy(self, volume: int = 1, reason: str = "", order_type: str = 'bar_close', index: int = 0, offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        买入开仓
        
        Args:
            volume: 交易量，默认为1
            reason: 交易原因
            order_type: 订单类型，可选值：
                - 'limit': 限价单（需指定price）
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，tick策略中按ask1价格成交（买入用卖一价）
            index: 数据源索引，默认为0（第一个数据源）
            offset_ticks: 价格偏移tick数，如果不提供则使用配置中的order_offset_ticks
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        ds = self.get_data_source(index)
        if ds:
            ds.buy(volume=volume, reason=reason, log_callback=self._log, order_type=order_type, offset_ticks=offset_ticks, price=price)
    
    def sell(self, volume: Optional[int] = None, reason: str = "", order_type: str = 'bar_close', index: int = 0, offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        卖出平仓
        
        Args:
            volume: 交易量，默认为全部持仓
            reason: 交易原因
            order_type: 订单类型，可选值同buy
            index: 数据源索引，默认为0（第一个数据源）
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        ds = self.get_data_source(index)
        if ds:
            ds.sell(volume=volume, reason=reason, log_callback=self._log, order_type=order_type, offset_ticks=offset_ticks, price=price)
    
    def sellshort(self, volume: int = 1, reason: str = "", order_type: str = 'bar_close', index: int = 0, offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        卖出开仓（做空）
        
        Args:
            volume: 交易量，默认为1
            reason: 交易原因
            order_type: 订单类型，可选值同buy
            index: 数据源索引，默认为0（第一个数据源）
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        ds = self.get_data_source(index)
        if ds:
            ds.sellshort(volume=volume, reason=reason, log_callback=self._log, order_type=order_type, offset_ticks=offset_ticks, price=price)
    
    def buycover(self, volume: Optional[int] = None, reason: str = "", order_type: str = 'bar_close', index: int = 0, offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        买入平仓（平空）
        
        Args:
            volume: 交易量，默认为全部持仓
            reason: 交易原因
            order_type: 订单类型，可选值同buy
            index: 数据源索引，默认为0（第一个数据源）
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        """
        ds = self.get_data_source(index)
        if ds:
            ds.buycover(volume=volume, reason=reason, log_callback=self._log, order_type=order_type, offset_ticks=offset_ticks, price=price)
    
    def buytocover(self, volume: Optional[int] = None, reason: str = "", order_type: str = 'bar_close', index: int = 0, offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        买入平仓（平空）- 兼容buytocover别名
        """
        return self.buycover(volume=volume, reason=reason, order_type=order_type, index=index, offset_ticks=offset_ticks, price=price)
    
    def close_all(self, reason: str = "", order_type: str = 'bar_close', index: int = 0):
        """
        平仓所有持仓
        
        Args:
            reason: 交易原因
            order_type: 订单类型，可选值：
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，tick策略中按对手价成交（买入ask1，卖出bid1）
            index: 数据源索引，默认为0（第一个数据源）
        """
        ds = self.get_data_source(index)
        if ds:
            ds.close_all(reason=reason, log_callback=self._log, order_type=order_type)
    
    def reverse_pos(self, reason: str = "", order_type: str = 'bar_close', index: int = 0):
        """
        反转持仓
        
        Args:
            reason: 交易原因
            order_type: 订单类型，可选值：
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，tick策略中按对手价成交（买入ask1，卖出bid1）
            index: 数据源索引，默认为0（第一个数据源）
        """
        ds = self.get_data_source(index)
        if ds:
            ds.reverse_pos(reason=reason, log_callback=self._log, order_type=order_type)
    
    def cancel_all_orders(self, index: int = 0):
        """
        撤销所有未成交的订单（仅实盘模式有效）
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
        
        注意：
            - 此方法仅在实盘模式（SIMNOW/REAL_TRADING）下有效
            - 回测模式下调用此方法无效果
            - 撤单需要一定时间，建议撤单后等待0.3-0.5秒再下新单
        """
        ds = self.get_data_source(index)
        if ds and hasattr(ds, 'cancel_all_orders'):
            ds.cancel_all_orders(log_callback=self._log)

    def cancel_order(self, order_sys_id: str, index: int = 0) -> bool:
        """
        撤销指定的未成交订单（仅实盘/SIMNOW模式有效）。

        Args:
            order_sys_id: CTP交易所报单编号（OrderSysID）
            index: 数据源索引，默认为0（第一个数据源）

        Returns:
            bool: 撤单请求是否已成功提交

        注意：
            - OrderSysID 可从 on_order 或 on_query_order 回调中获取
            - 订单必须属于指定数据源，且仍处于未成交或部分成交状态
            - 回测模式下调用此方法返回 False
        """
        ds = self.get_data_source(index)
        if ds and hasattr(ds, 'cancel_order'):
            return bool(ds.cancel_order(order_sys_id, log_callback=self._log))
        self._log("[撤单] 当前运行模式不支持单笔撤单")
        return False

    def get_tick(self, index: int = 0):
        """
        获取当前tick的所有字段（Series）
        
        在TICK流模式下，如果是多数据源：
        - 返回"触发当前策略执行的那个TICK"
        - 这样可以准确获取到是哪个品种的TICK数据
        
        Args:
            index: 数据源索引，默认为0
        Returns:
            当前tick的所有字段（Series），若无数据则返回None
        """
        # 【多数据源TICK流模式优化】
        # 如果多数据源容器有 _current_tick 属性，优先返回（这是触发策略的TICK）
        if hasattr(self._data, '_current_tick'):
            return self._data._current_tick
        
        # 否则使用默认逻辑（返回指定数据源的TICK）
        ds = self.get_data_source(index)
        if ds:
            return ds.get_tick()
        return None

    def get_ticks(self, window: int = None, index: int = 0):
        """
        获取最近window条tick数据（DataFrame）
        
        说明:
            在实盘/SIMNOW模式下，如果开启了 preload_history=True 且 kline_period='tick'，
            历史TICK数据会被预加载到缓存中，可以通过增大window参数来获取更多历史数据。
            
        Args:
            window: 滑窗长度，None表示使用配置的lookback_bars（默认100）
                    如需获取所有预加载的历史TICK，可使用 get_ticks_count() 获取总数
            index: 数据源索引，默认为0
        Returns:
            最近window条tick数据（DataFrame），若无数据则返回空DataFrame
            
        示例:
            # 使用配置的lookback_bars
            ticks = api.get_ticks()
            
            # 指定获取最近50条
            ticks = api.get_ticks(window=50)
            
            # 获取全部缓存的TICK
            ticks = api.get_ticks(window=0)
        """
        ds = self.get_data_source(index)
        if ds:
            return ds.get_ticks(window=window)
        return pd.DataFrame()
    
    def get_ticks_count(self, index: int = 0) -> int:
        """
        获取当前缓存的TICK数据总数（包含预加载的历史TICK）
        
        使用场景:
            在实盘/SIMNOW模式下开启历史TICK预加载后，可用此方法获取已加载的TICK数量，
            然后通过 get_ticks(window=count) 获取全部历史TICK数据。
            
        Args:
            index: 数据源索引，默认为0
            
        Returns:
            缓存的TICK数据条数
            
        示例:
            tick_count = api.get_ticks_count()
            all_ticks = api.get_ticks(window=tick_count)
        """
        ds = self.get_data_source(index)
        if ds and hasattr(ds, 'ticks'):
            return len(ds.ticks)
        return 0
    
    # ==================== 账户资金查询 ====================
    
    def get_account(self) -> dict:
        """
        获取完整账户信息（回测/SIMNOW/实盘 均有效）
        
        Returns:
            账户信息字典，包含以下字段：
            - balance: 账户权益
            - available: 可用资金
            - position_profit: 持仓盈亏
            - close_profit: 平仓盈亏
            - commission: 手续费
            - frozen_margin: 冻结保证金
            - curr_margin: 占用保证金
            - update_time: 更新时间
            
        示例:
            account = api.get_account()
            print(f"权益: {account['balance']}, 可用: {account['available']}")
        """
        if self._account_info:
            return self._account_info.copy()
        return {
            'balance': 0,
            'available': 0,
            'position_profit': 0,
            'close_profit': 0,
            'commission': 0,
            'frozen_margin': 0,
            'curr_margin': 0,
            'update_time': None,
        }
    
    def get_balance(self) -> float:
        """
        获取账户权益（回测/SIMNOW/实盘 均有效）
        
        Returns:
            账户权益金额
        """
        if self._account_info:
            return self._account_info.get('balance', 0)
        return 0
    
    def get_available(self) -> float:
        """
        获取可用资金（回测/SIMNOW/实盘 均有效）
        
        Returns:
            可用资金金额
        """
        if self._account_info:
            return self._account_info.get('available', 0)
        return 0
    
    def get_position_profit(self) -> float:
        """
        获取持仓盈亏（回测/SIMNOW/实盘 均有效）
        
        Returns:
            持仓浮动盈亏
        """
        if self._account_info:
            return self._account_info.get('position_profit', 0)
        return 0
    
    def get_close_profit(self) -> float:
        """
        获取平仓盈亏（回测/SIMNOW/实盘 均有效）
        
        Returns:
            当日平仓盈亏
        """
        if self._account_info:
            return self._account_info.get('close_profit', 0)
        return 0
    
    def get_margin(self) -> float:
        """
        获取占用保证金（回测/SIMNOW/实盘 均有效）
        
        Returns:
            当前占用保证金
        """
        if self._account_info:
            return self._account_info.get('curr_margin', 0)
        return 0
    
    def get_commission(self) -> float:
        """
        获取手续费（回测/SIMNOW/实盘 均有效）
        
        Returns:
            当日手续费
        """
        if self._account_info:
            return self._account_info.get('commission', 0)
        return 0
    
    def query_account(self):
        """
        主动查询账户资金（仅实盘/SIMNOW模式有效）
        
        触发CTP账户查询，查询结果通过回调更新到 account_info。
        建议在查询后等待 0.3-0.5 秒再读取账户信息。
        
        注意：
            - 此方法仅在实盘模式（SIMNOW/REAL_TRADING）下有效
            - 回测模式下调用此方法无效果
            - CTP有查询频率限制，建议不要频繁调用
            
        示例:
            api.query_account()
            import time
            time.sleep(0.5)  # 等待回调
            account = api.get_account()
        """
        if self._ctp_client and hasattr(self._ctp_client, 'query_account'):
            self._ctp_client.query_account()
    
    def query_position(self, symbol: str = ""):
        """
        主动查询持仓（仅实盘/SIMNOW模式有效）
        
        Args:
            symbol: 合约代码，空字符串表示查询所有持仓
            
        注意：
            - 此方法仅在实盘模式（SIMNOW/REAL_TRADING）下有效
            - 回测模式下调用此方法无效果
        """
        if self._ctp_client and hasattr(self._ctp_client, 'query_position'):
            self._ctp_client.query_position(symbol)
    
    def query_trades(self, symbol: str = ""):
        """
        主动查询当日成交记录（仅实盘/SIMNOW模式有效）
        
        Args:
            symbol: 合约代码，空字符串表示查询所有成交
            
        注意：
            - 此方法仅在实盘模式（SIMNOW/REAL_TRADING）下有效
            - 回测模式下调用此方法无效果
            - 查询结果通过 on_query_trade 回调返回
        """
        if self._ctp_client and hasattr(self._ctp_client, 'query_trades'):
            self._ctp_client.query_trades(symbol)

    def query_orders(self, symbol: str = ""):
        """
        主动查询当日委托记录（仅实盘/SIMNOW模式有效）

        Args:
            symbol: 合约代码，空字符串表示查询所有委托

        注意：
            - 此方法仅在实盘模式（SIMNOW/REAL_TRADING）下有效
            - 回测模式下调用此方法无效果
            - 查询结果通过 on_query_order 回调逐条返回
            - 全部返回后触发 on_query_order_complete 回调
        """
        if self._ctp_client and hasattr(self._ctp_client, 'query_orders'):
            self._ctp_client.query_orders(symbol)

# 创建策略API工厂函数
def create_strategy_api(context: Dict) -> StrategyAPI:
    """
    从context创建策略API
    
    Args:
        context: 策略上下文
        
    Returns:
        策略API对象
    """
    return StrategyAPI(context)
