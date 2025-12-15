import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

class FunctionAPI:
    def __init__(self):
        self._klines = pd.DataFrame()
        self._target_pos = 0
        self._current_pos = 0
        self._signal_reason = ""  # 添加交易信号原因变量
        self._log_file = None
        
    def set_klines(self, klines):
        """设置K线数据"""
        self._klines = klines
        
    def get_klines(self):
        """获取K线数据"""
        return self._klines
        
    def get_close(self):
        """获取收盘价序列"""
        return self._klines['close'] if 'close' in self._klines else pd.Series()
        
    def get_high(self):
        """获取最高价序列"""
        return self._klines['high'] if 'high' in self._klines else pd.Series()
        
    def get_low(self):
        """获取最低价序列"""
        return self._klines['low'] if 'low' in self._klines else pd.Series()
        
    def get_volume(self):
        """获取成交量序列"""
        return self._klines['volume'] if 'volume' in self._klines else pd.Series()
        
    def get_current_pos(self):
        """获取当前持仓"""
        return self._current_pos
        
    def log_message(self, message):
        """记录日志消息"""
        print(message)  # 打印到控制台
        
        # 如果有日志文件，则写入
        if self._log_file:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(message + "\n")
        
    def _update_pos(self):
        """更新实际持仓"""
        if self._current_pos != self._target_pos:
            old_pos = self._current_pos
            self._current_pos = self._target_pos
            self.log_message(f"持仓变化: {old_pos} -> {self._current_pos}")
        
    def set_target_pos(self, target_pos):
        """设置目标持仓"""
        self._target_pos = target_pos
        self._update_pos()  # 立即更新实际持仓
        
    def set_signal_reason(self, reason):
        """设置交易信号原因"""
        self._signal_reason = reason
        
    # 期货交易API
    def open_long(self, volume=1, reason=""):
        """开多仓"""
        self._target_pos = self._current_pos + volume
        if reason:
            self.set_signal_reason(reason)
        self._update_pos()
        
    def close_long(self, volume=None, reason=""):
        """平多仓"""
        if volume is None:
            volume = max(0, self._current_pos)
        self._target_pos = self._current_pos - min(volume, max(0, self._current_pos))
        if reason:
            self.set_signal_reason(reason)
        self._update_pos()
        
    def open_short(self, volume=1, reason=""):
        """开空仓"""
        self._target_pos = self._current_pos - volume
        if reason:
            self.set_signal_reason(reason)
        self._update_pos()
        
    def close_short(self, volume=None, reason=""):
        """平空仓"""
        if volume is None:
            volume = max(0, -self._current_pos)
        self._target_pos = self._current_pos + min(volume, max(0, -self._current_pos))
        if reason:
            self.set_signal_reason(reason)
        self._update_pos()
        
    def close_all(self, reason=""):
        """平掉所有持仓"""
        self._target_pos = 0
        if reason:
            self.set_signal_reason(reason)
        self._update_pos()
        
    def reverse_pos(self, reason=""):
        """反手（多转空，空转多）"""
        self._target_pos = -self._current_pos
        if reason:
            self.set_signal_reason(reason)
        self._update_pos()

def init_api():
    """初始化API"""
    global api
    api = FunctionAPI()
    return api

def ma(series, timeperiod):
    """计算移动平均线"""
    if len(series) < timeperiod:
        return pd.Series(index=series.index)
    return series.rolling(window=timeperiod).mean()

def create_target_pos(symbol):
    """创建目标持仓对象"""
    return api

# 全局API对象
api = FunctionAPI()

def wait_update(self) -> bool:
    """等待数据更新"""
    return True
        
def is_changing(self, data: pd.Series, key: str) -> bool:
    """判断数据是否更新"""
    return True

def rsi(series: pd.Series, n: int) -> pd.Series:
    """计算RSI指标
    
    Args:
        series: 数据序列
        n: 周期
        
    Returns:
        RSI指标序列
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=n).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=n).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """计算MACD指标
    
    Args:
        series: 数据序列
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期
        
    Returns:
        包含DIF、DEA和MACD的字典
    """
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    
    return {
        'DIF': dif,
        'DEA': dea,
        'MACD': macd
    }

def boll(series: pd.Series, n: int = 20, k: float = 2.0) -> Dict[str, pd.Series]:
    """计算布林带指标
    
    Args:
        series: 数据序列
        n: 周期
        k: 标准差倍数
        
    Returns:
        包含上轨、中轨和下轨的字典
    """
    mid = ma(series, n)
    std = series.rolling(window=n).std()
    
    return {
        'upper': mid + k * std,
        'middle': mid,
        'lower': mid - k * std
    } 