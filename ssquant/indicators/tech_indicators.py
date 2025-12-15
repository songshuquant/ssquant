"""
技术指标库 - 提供常用的技术分析指标

这个库包含了常用的技术分析指标，如移动平均线、MACD、RSI等。
用户可以直接导入这些函数使用，而不必依赖于API提供的指标计算功能。
"""

import pandas as pd
import numpy as np


# === 移动平均线指标 ===

def ma(price, period):
    """
    计算简单移动平均线
    
    Args:
        price: 价格序列
        period: 周期
        
    Returns:
        移动平均线序列
    """
    return price.rolling(period).mean()


def ema(price, period):
    """
    计算指数移动平均线
    
    Args:
        price: 价格序列
        period: 周期
        
    Returns:
        指数移动平均线序列
    """
    return price.ewm(span=period, min_periods=period).mean()


def wma(price, period):
    """
    计算加权移动平均线
    
    Args:
        price: 价格序列
        period: 周期
        
    Returns:
        加权移动平均线序列
    """
    weights = np.arange(1, period + 1)
    return price.rolling(period).apply(lambda x: np.sum(weights * x) / weights.sum(), raw=True)


# === MACD指标 ===

def macd(price, fast_period=12, slow_period=26, signal_period=9):
    """
    计算MACD指标
    
    Args:
        price: 价格序列
        fast_period: 快线周期
        slow_period: 慢线周期
        signal_period: 信号线周期
        
    Returns:
        (macd线, 信号线, 柱状图)
    """
    fast_ema = ema(price, fast_period)
    slow_ema = ema(price, slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# === RSI指标 ===

def rsi(price, period=14):
    """
    计算相对强弱指数(RSI)
    
    Args:
        price: 价格序列
        period: 周期
        
    Returns:
        RSI序列
    """
    delta = price.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    # 防止除零错误
    rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
    rsi = 100 - (100 / (1 + rs))
    return rsi


# === 布林带指标 ===

def bollinger_bands(price, period=20, stdev_factor=2):
    """
    计算布林带指标
    
    Args:
        price: 价格序列
        period: 移动平均周期
        stdev_factor: 标准差倍数
        
    Returns:
        (中轨, 上轨, 下轨)
    """
    # 计算中轨 (简单移动平均线)
    middle_band = ma(price, period)
    
    # 计算标准差
    std = price.rolling(period).std()
    
    # 计算上下轨
    upper_band = middle_band + stdev_factor * std
    lower_band = middle_band - stdev_factor * std
    
    return middle_band, upper_band, lower_band


# === KDJ指标 ===

def kdj(high, low, close, n=9, m1=3, m2=3):
    """
    计算KDJ指标
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        n: 周期
        m1: K值平滑因子
        m2: D值平滑因子
        
    Returns:
        (K值, D值, J值)
    """
    # 计算最低价和最高价的n日滚动最小值和最大值
    low_min = low.rolling(n).min()
    high_max = high.rolling(n).max()
    
    # 计算RSV
    rsv = 100 * ((close - low_min) / (high_max - low_min).replace(0, np.finfo(float).eps))
    
    # 计算K值
    k = pd.Series(np.nan, index=rsv.index)
    k[n-1] = 50.0  # 初始值设为50
    for i in range(n, len(rsv)):
        k[i] = (1-1/m1) * k[i-1] + 1/m1 * rsv[i]
    
    # 计算D值
    d = pd.Series(np.nan, index=k.index)
    d[n-1] = 50.0  # 初始值设为50
    for i in range(n, len(k)):
        d[i] = (1-1/m2) * d[i-1] + 1/m2 * k[i]
    
    # 计算J值
    j = 3*k - 2*d
    
    return k, d, j


# === ATR指标 ===

def atr(high, low, close, period=14):
    """
    计算平均真实波幅(ATR)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        ATR序列
    """
    # 计算真实波幅(TR)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # 计算ATR (使用简单移动平均)
    atr = tr.rolling(period).mean()
    return atr


# === CCI指标 ===

def cci(high, low, close, period=20):
    """
    计算顺势指标(CCI)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        CCI序列
    """
    # 计算典型价格
    tp = (high + low + close) / 3
    
    # 计算典型价格的简单移动平均
    tp_ma = tp.rolling(period).mean()
    
    # 计算平均偏差
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
    
    # 计算CCI
    cci = (tp - tp_ma) / (0.015 * mad)
    return cci


# === 交叉判断函数 ===

def is_crossover(fast_line, slow_line, idx):
    """
    判断快线是否上穿慢线
    
    Args:
        fast_line: 快线序列
        slow_line: 慢线序列
        idx: 当前索引
        
    Returns:
        是否上穿
    """
    if idx < 1 or idx >= len(fast_line):
        return False
    
    # 检查是否有NaN值
    if pd.isna(fast_line.iloc[idx]) or pd.isna(slow_line.iloc[idx]) or \
       pd.isna(fast_line.iloc[idx-1]) or pd.isna(slow_line.iloc[idx-1]):
        return False
    
    return (fast_line.iloc[idx-1] <= slow_line.iloc[idx-1] and 
            fast_line.iloc[idx] > slow_line.iloc[idx])


def is_crossunder(fast_line, slow_line, idx):
    """
    判断快线是否下穿慢线
    
    Args:
        fast_line: 快线序列
        slow_line: 慢线序列
        idx: 当前索引
        
    Returns:
        是否下穿
    """
    if idx < 1 or idx >= len(fast_line):
        return False
    
    # 检查是否有NaN值
    if pd.isna(fast_line.iloc[idx]) or pd.isna(slow_line.iloc[idx]) or \
       pd.isna(fast_line.iloc[idx-1]) or pd.isna(slow_line.iloc[idx-1]):
        return False
    
    return (fast_line.iloc[idx-1] >= slow_line.iloc[idx-1] and 
            fast_line.iloc[idx] < slow_line.iloc[idx])


# === 价格形态识别 ===

def find_swing_high(high, window=5):
    """
    识别价格波动高点
    
    Args:
        high: 最高价序列
        window: 窗口大小
        
    Returns:
        波动高点序列 (True/False)
    """
    result = pd.Series(False, index=high.index)
    half_window = window // 2
    
    for i in range(half_window, len(high) - half_window):
        if high.iloc[i] == high.iloc[i-half_window:i+half_window+1].max():
            result.iloc[i] = True
            
    return result


def find_swing_low(low, window=5):
    """
    识别价格波动低点
    
    Args:
        low: 最低价序列
        window: 窗口大小
        
    Returns:
        波动低点序列 (True/False)
    """
    result = pd.Series(False, index=low.index)
    half_window = window // 2
    
    for i in range(half_window, len(low) - half_window):
        if low.iloc[i] == low.iloc[i-half_window:i+half_window+1].min():
            result.iloc[i] = True
            
    return result 