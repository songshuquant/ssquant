import pandas as pd
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
        获取当前价格
        
        Args:
            index: 数据源索引，默认为0（第一个数据源）
            
        Returns:
            当前价格，如果数据源无效则返回None
        """
        ds = self.get_data_source(index)
        if ds:
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