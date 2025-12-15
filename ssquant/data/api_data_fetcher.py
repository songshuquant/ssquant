import requests
import pandas as pd
from datetime import datetime, timedelta
from io import StringIO
import os
import time
import sqlite3
import functools

# 交易日历功能
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    # 静默失败，使用基本规则

class TradingCalendar:
    def __init__(self, cache_file="data_cache/trading_calendar_cache.pkl", update_freq_days=1):
        """
        初始化交易日历类
        
        Args:
            cache_file (str): 缓存文件路径
            update_freq_days (int): 更新频率(天)
        """
        self.cache_file = cache_file
        self.update_freq_days = update_freq_days
        self.trading_days = None
        self.last_update = None
        self.load_or_update_calendar()
    
    def load_or_update_calendar(self, force_update=False):
        """加载或更新交易日历"""
        need_update = True
        
        # 检查缓存文件是否存在
        if os.path.exists(self.cache_file) and not force_update:
            try:
                cache_data = pd.read_pickle(self.cache_file)
                self.trading_days = cache_data.get('calendar')
                self.last_update = cache_data.get('last_update')
                
                # 检查是否需要更新
                if self.last_update is not None:
                    days_since_update = (datetime.now() - self.last_update).days
                    need_update = days_since_update >= self.update_freq_days
                    
                    # 如果数据最后一天小于当前日期一年，强制更新
                    if self.trading_days is not None and len(self.trading_days) > 0:
                        last_date = pd.to_datetime(self.trading_days[-1])
                        days_to_last = (datetime.now() - last_date).days
                        if days_to_last > 365:
                            need_update = True
            except Exception as e:
                print(f"读取交易日历缓存出错: {e}")
                need_update = True
        
        # 需要更新交易日历
        if need_update or self.trading_days is None:
            if AKSHARE_AVAILABLE:
                try:
                    # 静默获取交易日历
                    tool_trade_date_hist_sina_df = ak.tool_trade_date_hist_sina()
                    self.trading_days = tool_trade_date_hist_sina_df['trade_date'].astype(str).tolist()
                    
                    # 更新缓存
                    self.last_update = datetime.now()
                    cache_data = {
                        'calendar': self.trading_days,
                        'last_update': self.last_update
                    }
                    os.makedirs(os.path.dirname(self.cache_file) if os.path.dirname(self.cache_file) else '.', exist_ok=True)
                    pd.to_pickle(cache_data, self.cache_file)
                    # 静默更新，不输出信息
                except Exception as e:
                    # 静默失败，使用基本规则
                    self.use_basic_rules()
            else:
                self.use_basic_rules()
    
    def use_basic_rules(self):
        """使用基本规则生成交易日历"""
        # 静默生成，不输出信息
        # 生成从2000年到当前年份后5年的所有工作日
        start_year = 2000
        end_year = datetime.now().year + 5
        all_days = []
        
        current_date = datetime(start_year, 1, 1)
        end_date = datetime(end_year, 12, 31)
        
        while current_date <= end_date:
            if current_date.weekday() < 5:  # 0-4表示周一至周五
                all_days.append(current_date.strftime('%Y-%m-%d'))
            current_date += timedelta(days=1)
        
        self.trading_days = all_days
        self.last_update = datetime.now()
    
    def is_trading_day(self, date):
        """
        检查日期是否为交易日
        
        Args:
            date: 日期，可以是字符串、datetime对象或pandas.Timestamp
        
        Returns:
            bool: 是否为交易日
        """
        if self.trading_days is None or len(self.trading_days) == 0:
            # 如果没有交易日历数据，使用基本规则
            if isinstance(date, str):
                date = pd.to_datetime(date)
            return date.weekday() < 5  # 周一至周五
        
        # 统一日期格式为字符串 YYYY-MM-DD
        if isinstance(date, (datetime, pd.Timestamp)):
            date_str = date.strftime('%Y-%m-%d')
        else:
            date_str = pd.to_datetime(date).strftime('%Y-%m-%d')
        
        return date_str in self.trading_days
    
    def get_trading_date_range(self, start_date, end_date):
        """
        获取起止日期间的实际交易日范围
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            tuple: (第一个交易日, 最后一个交易日)，如果范围内没有交易日返回(None, None)
        """
        # 确保日期格式统一
        if isinstance(start_date, str):
            start_dt = pd.to_datetime(start_date)
        else:
            start_dt = start_date
        
        if isinstance(end_date, str):
            end_dt = pd.to_datetime(end_date)
        else:
            end_dt = end_date
        
        # 生成日期范围
        date_range = pd.date_range(start=start_dt, end=end_dt)
        
        # 筛选交易日
        trading_days = [d for d in date_range if self.is_trading_day(d)]
        
        if not trading_days:
            return None, None
        
        # 返回第一个和最后一个交易日
        return trading_days[0].strftime('%Y-%m-%d'), trading_days[-1].strftime('%Y-%m-%d')

# 创建全局交易日历对象
trading_calendar = TradingCalendar()

# 添加实用函数
def is_trading_day(date):
    """检查日期是否为交易日"""
    return trading_calendar.is_trading_day(date)

def get_trading_date_range(start_date, end_date):
    """获取实际的交易日期范围"""
    return trading_calendar.get_trading_date_range(start_date, end_date)

def get_futures_data(
    symbol, 
    start_date, 
    end_date, 
    username=None, 
    password=None,
    kline_period='D', 
    adjust_type='0', 
    depth='no',
    use_cache=True,
    cache_dir='data_cache',
    save_data=False
):
    """
    从API获取期货数据
    
    Args:
        symbol (str): 期货代码，如"AP888"
        start_date (str): 开始日期，格式为"YYYY-MM-DD"
        end_date (str): 结束日期，格式为"YYYY-MM-DD"
        username (str): API用户名/手机号
        password (str): API密码
        kline_period (str): K线周期，支持分钟(1M,5M等)、天(1D)、周(1W)、月(1Y)
        adjust_type (str): 复权类型，0(不复权)或1(后复权)
        depth (str): 是否获取交易数据统计，"yes"或"no"
        use_cache (bool): 是否使用缓存数据
        cache_dir (str): 缓存目录
        save_data (bool): 是否保存数据，即使use_cache=False
        
    Returns:
        pd.DataFrame: 包含OHLCV数据的DataFrame
    """
    # ========== TICK数据特殊处理 ==========
    # TICK数据只能从本地数据库获取（远程服务器不提供TICK数据）
    # TICK数据没有复权概念，表名格式: {symbol}_tick
    if kline_period.lower() == 'tick':
        print("="*80)
        print(f"【TICK数据请求】{symbol}")
        print("="*80)
        print("注意: TICK数据只能从本地数据库获取，请先通过SIMNOW模式采集")
        
        db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
        
        if not os.path.exists(db_path):
            print(f"❌ 数据库不存在: {db_path}")
            print("请先运行SIMNOW模式采集TICK数据（开启save_tick_db=True）")
            return pd.DataFrame()
        
        try:
            data = read_from_sqlite(db_path, table_name)
            
            if data is None or data.empty:
                print(f"❌ TICK表为空或不存在: {table_name}")
                # 列出可用的tick表（sqlite3已在顶层导入）
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_tick'")
                available = [row[0] for row in cursor.fetchall()]
                conn.close()
                if available:
                    print(f"可用的TICK表: {available}")
                else:
                    print("数据库中没有TICK表，请先采集TICK数据")
                return pd.DataFrame()
            
            # 转换datetime
            data['datetime'] = pd.to_datetime(data['datetime'])
            
            # 按日期筛选
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            data = data[(data['datetime'] >= start_dt) & (data['datetime'] <= end_dt)]
            
            if data.empty:
                print(f"❌ 指定日期范围内没有TICK数据: {start_date} 至 {end_date}")
                return pd.DataFrame()
            
            # 设置索引
            data = data.set_index('datetime')
            data['datetime'] = data.index
            
            # TICK数据保留CTP原始字段，回测引擎已支持直接识别
            # 字段包括: InstrumentID, LastPrice, Volume, BidPrice1, AskPrice1 等
            
            print(f"✅ 成功加载 {len(data)} 条TICK数据")
            print(f"数据范围: {data.index[0]} 至 {data.index[-1]}")
            print("="*80)
            
            return data
            
        except Exception as e:
            print(f"❌ 读取TICK数据失败: {e}")
            return pd.DataFrame()
    
    # ========== K线数据处理 ==========
    # 检查是否提供了用户名和密码
    if not username or not password:
        raise ValueError("必须提供API用户名和密码")
    
    print("="*80)
    print(f"【数据请求开始】{symbol} {kline_period} {'后复权' if adjust_type == '1' else '不复权'}")
    print("="*80)
    
    # 获取当前系统时间并显示
    current_date = pd.to_datetime(datetime.now().date())
    print(f"当前系统日期: {current_date.strftime('%Y-%m-%d')}")
    print(f"原始请求日期范围: {start_date} 到 {end_date}")
    
    # 转换日期字符串为datetime对象，用于比较
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    
    # 检查结束日期是否超过当前日期
    if end_dt > current_date:
        print(f"警告: 请求的结束日期 {end_date} 超过当前日期 {current_date.strftime('%Y-%m-%d')}，将使用当前日期作为结束日期")
        end_dt = current_date
        end_date = current_date.strftime('%Y-%m-%d')
        print(f"调整后日期范围: {start_date} 到 {end_date}")
    
    # 新增: 调整为实际交易日范围
    trading_start, trading_end = get_trading_date_range(start_dt, end_dt)
    
    if trading_start is None:
        print(f"警告: 请求的日期范围内没有交易日")
        return pd.DataFrame()  # 返回空数据框
    
    # 更新请求日期范围为交易日
    if trading_start != start_date or trading_end != end_date:
        print(f"调整为实际交易日期范围: {trading_start} 到 {trading_end}")
        start_date = trading_start
        end_date = trading_end
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
    
    # 检查缓存
    if use_cache:
        db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
        if os.path.exists(db_path):
            print(f"使用缓存数据: {db_path}")
            try:
                data = read_from_sqlite(db_path, table_name)
                
                # 检查数据是否为空
                if data is None or data.empty:
                    print("缓存数据为空，将从API重新获取数据")
                    raise ValueError("缓存数据为空")
                
                data['datetime'] = pd.to_datetime(data['datetime'])
                
                # 确保时区一致性 - 将所有时间戳转换为无时区
                if isinstance(data['datetime'].dtype, pd.DatetimeTZDtype):
                    date_col_no_tz = data['datetime'].dt.tz_localize(None)
                else:
                    date_col_no_tz = data['datetime']
                
                # 移除NaT值后再计算min/max
                date_col_no_tz_valid = date_col_no_tz.dropna()
                
                if date_col_no_tz_valid.empty:
                    print("缓存数据全部为无效日期，将从API重新获取数据")
                    raise ValueError("缓存数据无效")
                
                cache_start = date_col_no_tz_valid.min()
                cache_end = date_col_no_tz_valid.max()
                
                # 检查缓存是否完全覆盖了请求的日期范围
                cache_covers_request = (cache_start <= start_dt) and (cache_end >= end_dt)
                
                # 检查数据是否包含请求的日期范围内的数据
                data_in_range = data[(date_col_no_tz >= start_dt) & (date_col_no_tz <= end_dt)]
                has_data_in_range = not data_in_range.empty
                
                print(f"缓存数据范围: {cache_start.strftime('%Y-%m-%d')} 到 {cache_end.strftime('%Y-%m-%d')}")
                print(f"请求数据范围: {start_dt.strftime('%Y-%m-%d')} 到 {end_dt.strftime('%Y-%m-%d')}")
                
                # 直接比较日期字符串，避免可能的时间比较问题
                cache_start_date = cache_start.strftime('%Y-%m-%d')
                cache_end_date = cache_end.strftime('%Y-%m-%d')
                request_start_date = start_dt.strftime('%Y-%m-%d')
                request_end_date = end_dt.strftime('%Y-%m-%d')
                
                # 检查缓存是否包含所有交易日
                trading_days_in_range = []
                date_range = pd.date_range(start=start_dt, end=end_dt)
                for date in date_range:
                    if is_trading_day(date):
                        trading_days_in_range.append(date.strftime('%Y-%m-%d'))
                
                # 检查缓存中是否包含所有交易日的数据
                missing_trading_days = []
                # 移除NaT值后再转换为字符串
                cache_dates = set(date_col_no_tz.dropna().dt.strftime('%Y-%m-%d'))
                for trading_day in trading_days_in_range:
                    if trading_day not in cache_dates:
                        missing_trading_days.append(trading_day)
                
                # 更精确的覆盖判断：如果缓存的开始和结束日期包含请求的日期范围，且没有缺失交易日
                cache_fully_covers = (cache_start_date <= request_start_date and 
                                    cache_end_date >= request_end_date and 
                                    not missing_trading_days)
                
                # 日志输出当前判断结果
                print(f"缓存完全覆盖请求范围: {cache_fully_covers}")
                if missing_trading_days:
                    print(f"缺失交易日: {', '.join(missing_trading_days[:5])}{' 等' if len(missing_trading_days) > 5 else ''}")
                
                if cache_fully_covers:
                    print("缓存完全覆盖请求范围，直接使用缓存数据")
                    # 缓存完全覆盖了请求的日期范围，直接筛选
                    filtered_data = data[(date_col_no_tz >= start_dt) & (date_col_no_tz <= end_dt)]
                    filtered_data.set_index('datetime', inplace=True)
                    print(f"返回数据条数: {len(filtered_data)}")
                    print("="*80)
                    return filtered_data
                else:
                    # 缓存不完全覆盖请求的日期范围
                    print(f"缓存数据不完全覆盖请求的日期范围，需要获取缺失部分")
                    
                    # 标记缺失部分
                    merged_data = data.copy()
                    need_fetch_missing_data = False
                    
                    # 处理开始日期缺失的情况 - 仅在缓存起始日期晚于请求起始日期时处理
                    if cache_start_date > request_start_date:
                        print("-"*50)
                        print("【处理缺失的开始部分数据】")
                        
                        # 计算缺失的交易日
                        missing_start_trading_days = []
                        for day in trading_days_in_range:
                            day_dt = pd.to_datetime(day)
                            if day_dt < cache_start and day not in cache_dates:
                                missing_start_trading_days.append(day)
                        
                        if not missing_start_trading_days:
                            print(f"缺失部分没有交易日，跳过获取")
                        else:
                            # 对缺失交易日进行排序
                            missing_start_trading_days.sort()
                            missing_start_date = missing_start_trading_days[0]
                            missing_start_end_date = missing_start_trading_days[-1]
                            
                            print(f"缺失开始部分: {missing_start_date} 到 {missing_start_end_date}")
                            
                            # 获取缺失的开始部分数据
                            try:
                                print(f"尝试获取缺失数据: {missing_start_date} 到 {missing_start_end_date}")
                                missing_data = fetch_data_from_api(symbol, missing_start_date, missing_start_end_date, 
                                                            username, password, kline_period, adjust_type, depth)
                                
                                if missing_data is not None and not missing_data.empty:
                                    # 合并数据
                                    missing_reset = missing_data.reset_index()
                                    # 确保时区一致性
                                    if isinstance(missing_reset['datetime'].dtype, pd.DatetimeTZDtype):
                                        missing_reset['datetime'] = missing_reset['datetime'].dt.tz_localize(None)
                                    
                                    # 计算实际新增数据量
                                    new_records = len(missing_reset)
                                    merged_data = pd.concat([missing_reset, merged_data])
                                    need_fetch_missing_data = True
                                    print(f"成功获取缺失开始部分，新增 {new_records} 条记录")
                                else:
                                    print(f"未能获取缺失的开始部分数据")
                            except Exception as e:
                                print(f"获取缺失开始部分时出错: {str(e)}")
                        print("-"*50)
                    
                    # 处理结束日期缺失的情况 - 仅在缓存结束日期早于请求结束日期时处理
                    if cache_end_date < request_end_date:
                        print("-"*50)
                        print("【处理缺失的结束部分数据】")
                        
                        # 计算缺失的交易日
                        missing_end_trading_days = []
                        for day in trading_days_in_range:
                            day_dt = pd.to_datetime(day)
                            if day_dt > cache_end and day not in cache_dates:
                                missing_end_trading_days.append(day)
                        
                        if not missing_end_trading_days:
                            print(f"缺失部分没有交易日，跳过获取")
                        else:
                            # 对缺失交易日进行排序
                            missing_end_trading_days.sort()
                            missing_end_start_date = missing_end_trading_days[0]
                            missing_end_date = missing_end_trading_days[-1]
                            
                            print(f"缺失结束部分: {missing_end_start_date} 到 {missing_end_date}")
                            
                            # 获取缺失的结束部分数据
                            try:
                                print(f"尝试获取缺失数据: {missing_end_start_date} 到 {missing_end_date}")
                                missing_data = fetch_data_from_api(symbol, missing_end_start_date, missing_end_date, 
                                                            username, password, kline_period, adjust_type, depth)
                                
                                if missing_data is not None and not missing_data.empty:
                                    # 合并数据
                                    missing_reset = missing_data.reset_index()
                                    # 确保时区一致性
                                    if isinstance(missing_reset['datetime'].dtype, pd.DatetimeTZDtype):
                                        missing_reset['datetime'] = missing_reset['datetime'].dt.tz_localize(None)
                                    
                                    # 计算实际新增数据量
                                    cache_dates = set(date_col_no_tz)
                                    new_data_count = sum(1 for date in missing_reset['datetime'] if date not in cache_dates)
                                    
                                    # 合并数据
                                    merged_data = pd.concat([merged_data, missing_reset])
                                    need_fetch_missing_data = True
                                    print(f"成功获取缺失结束部分，新增 {new_data_count} 条记录")
                                else:
                                    print(f"未能获取缺失的结束部分数据")
                            except Exception as e:
                                print(f"获取缺失结束部分时出错: {str(e)}")
                        print("-"*50)
                    
                    # 处理缺失的中间交易日（如果有）
                    middle_missing_days = [day for day in missing_trading_days 
                                           if pd.to_datetime(day) >= cache_start and pd.to_datetime(day) <= cache_end]
                    
                    if middle_missing_days:
                        print("-"*50)
                        print("【处理缺失的中间交易日数据】")
                        print(f"缺失的交易日: {', '.join(middle_missing_days[:5])}{' 等' if len(middle_missing_days) > 5 else ''}")
                        
                        # 按连续区间合并缺失的交易日，减少API请求次数
                        missing_ranges = []
                        middle_missing_days.sort()
                        
                        if middle_missing_days:
                            range_start = middle_missing_days[0]
                            range_end = middle_missing_days[0]
                            
                            for i in range(1, len(middle_missing_days)):
                                current = pd.to_datetime(middle_missing_days[i])
                                previous = pd.to_datetime(range_end)
                                
                                # 如果日期连续（考虑周末和节假日）
                                if (current - previous).days <= 5:
                                    range_end = middle_missing_days[i]
                                else:
                                    missing_ranges.append((range_start, range_end))
                                    range_start = middle_missing_days[i]
                                    range_end = middle_missing_days[i]
                            
                            # 添加最后一个区间
                            missing_ranges.append((range_start, range_end))
                        
                        # 获取每个缺失区间的数据
                        for range_start, range_end in missing_ranges:
                            print(f"尝试获取缺失区间: {range_start} 到 {range_end}")
                            try:
                                missing_data = fetch_data_from_api(symbol, range_start, range_end, 
                                                            username, password, kline_period, adjust_type, depth)
                                
                                if missing_data is not None and not missing_data.empty:
                                    # 合并数据
                                    missing_reset = missing_data.reset_index()
                                    # 确保时区一致性
                                    if isinstance(missing_reset['datetime'].dtype, pd.DatetimeTZDtype):
                                        missing_reset['datetime'] = missing_reset['datetime'].dt.tz_localize(None)
                                    
                                    # 计算实际新增数据量
                                    new_records = len(missing_reset)
                                    merged_data = pd.concat([merged_data, missing_reset])
                                    need_fetch_missing_data = True
                                    print(f"成功获取缺失区间数据，新增 {new_records} 条记录")
                                else:
                                    print(f"未能获取缺失区间数据")
                            except Exception as e:
                                print(f"获取缺失区间数据时出错: {str(e)}")
                        print("-"*50)
                    
                    # 处理合并后的数据
                    if need_fetch_missing_data:
                        print("合并和处理所有数据...")
                        # 删除重复项并按日期排序
                        before_dedup = len(merged_data)
                        merged_data = merged_data.drop_duplicates(subset=['datetime']).sort_values('datetime')
                        after_dedup = len(merged_data)
                        print(f"删除了 {before_dedup - after_dedup} 条重复记录")
                        
                        # 更新缓存
                        if save_data:
                            print("更新缓存数据...")
                            try:
                                save_to_sqlite(merged_data.reset_index(drop=True), db_path, table_name)
                            except Exception as e:
                                print(f"缓存更新失败，但继续使用合并后的数据: {e}")
                        
                        # 确保时区一致性 - 重新计算无时区列
                        if isinstance(merged_data['datetime'].dtype, pd.DatetimeTZDtype):
                            date_col_no_tz = merged_data['datetime'].dt.tz_localize(None)
                        else:
                            date_col_no_tz = merged_data['datetime']
                        
                        # 筛选出请求的日期范围
                        filtered_data = merged_data[(date_col_no_tz >= start_dt) & (date_col_no_tz <= end_dt)]
                        filtered_data.set_index('datetime', inplace=True)
                        print(f"返回数据条数: {len(filtered_data)}")
                        print("="*80)
                        return filtered_data
                    else:
                        # 没有成功获取到任何新数据，使用已有的部分缓存数据
                        if has_data_in_range:
                            print(f"使用缓存中的有效数据 ({len(data_in_range)} 条记录)")
                            filtered_data = data_in_range
                            filtered_data.set_index('datetime', inplace=True)
                            print("="*80)
                            return filtered_data
                        else:
                            # 尝试一次完整获取
                            print(f"缓存中没有请求范围内的数据，尝试获取完整数据")
                            print(f"请求范围: {start_date} 到 {end_date}")
                            new_data = fetch_data_from_api(symbol, start_date, end_date, username, password, 
                                                       kline_period, adjust_type, depth)
                            if new_data is not None and not new_data.empty:
                                # 更新缓存
                                if save_data:
                                    save_to_sqlite(new_data.reset_index(), db_path, table_name)
                                print(f"返回数据条数: {len(new_data)}")
                                print("="*80)
                                return new_data
                            else:
                                print("未能获取任何数据")
                                print("="*80)
                                return pd.DataFrame()  # 返回空DataFrame而不是None
            except sqlite3.Error as e:
                print(f"读取SQLite缓存出错: {e}")
                print("将从API重新获取数据")
            except Exception as e:
                print(f"处理缓存数据时出错: {e}")
                print("将从API重新获取数据")
        else:
            print(f"缓存数据库不存在，将从API获取数据")
    
    # 从API获取数据
    print(f"直接从API获取完整数据: {start_date} 到 {end_date}")
    data = fetch_data_from_api(symbol, start_date, end_date, username, password, kline_period, adjust_type, depth)
    
    # 缓存数据
    if data is not None and not data.empty and (use_cache or save_data):
        db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
        try:
            save_to_sqlite(data.reset_index(), db_path, table_name)
        except Exception as e:
            print(f"缓存更新失败: {e}")
        print(f"返回数据条数: {len(data)}")
        print("="*80)
        return data
    else:
        print("未能获取任何数据或数据为空")
        print("="*80)
        return pd.DataFrame()  # 返回空DataFrame而不是None

def fetch_data_from_api(symbol, start_date, end_date, username, password, kline_period, adjust_type, depth, max_retries=3):
    """从API获取数据的辅助函数"""
    # 检查日期是否为交易日
    trading_start, trading_end = get_trading_date_range(start_date, end_date)
    
    if trading_start is None:
        print(f"请求的日期范围 {start_date} 到 {end_date} 内没有交易日")
        return pd.DataFrame()  # 返回空DataFrame而不是None
    
    # 使用调整后的交易日期范围
    if trading_start != start_date or trading_end != end_date:
        print(f"调整API请求为实际交易日: {trading_start} 到 {trading_end}")
        start_date = trading_start
        end_date = trading_end
    
    # 检查开始日期和结束日期是否相同（单日请求），如果是，尝试扩展结束日期
    if start_date == end_date:
        print(f"检测到单日请求：{start_date}，尝试扩展请求范围以适配API")
        # 将结束日期后推一天
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        # 找到下一个交易日
        next_trading_day = None
        for i in range(1, 10):  # 最多尝试往后找10天
            check_date = pd.to_datetime(end_date) + pd.Timedelta(days=i)
            if is_trading_day(check_date):
                next_trading_day = check_date.strftime('%Y-%m-%d')
                break
        
        if next_trading_day:
            print(f"扩展请求范围至下一个交易日: {start_date} 到 {next_trading_day}")
            end_date = next_trading_day
    
    # 检查结束日期是否超过当前日期
    current_date = pd.to_datetime(datetime.now().date())
    end_dt = pd.to_datetime(end_date)
    if end_dt > current_date:
        print(f"警告: API请求的结束日期 {end_date} 超过当前日期 {current_date.strftime('%Y-%m-%d')}，将使用当前日期作为结束日期")
        end_date = current_date.strftime('%Y-%m-%d')
    
    # API配置
    base_url = 'http://kanpan789.com:8086/ftdata'
    
    # 构建请求参数
    params = {
        'username': username,
        'password': password,
        'symbol': symbol,
        'start_date': start_date,
        'end_date': end_date,
        'kline_period': kline_period,
        'adjust_type': adjust_type
    }
    
    if depth:
        params['Depth'] = depth
    
    print(f"API请求: {symbol} 从 {start_date} 到 {end_date}")
    
    # 添加重试逻辑
    retries = 0
    while retries < max_retries:
        try:
            # 发送请求，设置超时时间为300秒
            response = requests.get(base_url, params=params, timeout=300)
            
            # 检查响应状态
            if response.status_code == 200:
                # 检查响应是否为JSON格式
                if 'application/json' in response.headers.get('Content-Type', ''):
                    data = pd.read_json(StringIO(response.text), orient='records')
                    data = data.reset_index()
                    
                    # 列名排序
                    if depth == 'yes':
                        columns = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'amount', 'openint', 'cumulative_openint', 'open_askp', 'open_bidp', 'close_askp', 'close_bidp', '开仓', '平仓', '多开', '空开', '多平', '空平', '双开', '双平', '双换', 'B', 'S', '未知']
                    else:
                        columns = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'amount', 'openint', 'cumulative_openint', 'open_askp', 'open_bidp', 'close_askp', 'close_bidp']
                    
                    # 重新排列列名
                    data = data.reindex(columns=[col for col in columns if col in data.columns])
                    
                    # 处理日期时间 - 确保是datetime对象并转换为北京时间
                    data['datetime'] = pd.to_datetime(data['datetime'])
                    
                    # 如果datetime没有时区信息，假定为UTC时间，然后转换为北京时间
                    if not isinstance(data['datetime'].dtype, pd.DatetimeTZDtype):
                        data['datetime'] = data['datetime'].dt.tz_localize('UTC').dt.tz_convert('Asia/Shanghai')
                    else:
                        # 如果已经有时区信息，直接转换为北京时间
                        data['datetime'] = data['datetime'].dt.tz_convert('Asia/Shanghai')
                    
                    # 移除时区信息，保持datetime格式统一
                    data['datetime'] = data['datetime'].dt.tz_localize(None)
                    
                    # 将K线时间从收盘时间调整为开始时间（仅对分钟和小时周期）
                    if kline_period.endswith('M'):  # 分钟线
                        minutes = int(kline_period[:-1])
                        data['datetime'] = data['datetime'] - pd.Timedelta(minutes=minutes)
                    elif kline_period.endswith('H') or kline_period.lower() == '1h':  # 小时线
                        hours = int(kline_period[:-1]) if kline_period.endswith('H') else 1
                        data['datetime'] = data['datetime'] - pd.Timedelta(hours=hours)
                    
                    # 转换请求的日期范围为datetime对象进行过滤
                    start_dt = pd.to_datetime(start_date)
                    end_dt = pd.to_datetime(end_date)
                    
                    # 检查API返回的数据范围
                    original_data_len = len(data)
                    
                    if not data.empty:
                        # 移除NaT值后再获取日期范围
                        valid_dates = data['datetime'].dropna()
                        if not valid_dates.empty:
                            data_start = valid_dates.min().strftime('%Y-%m-%d')
                            data_end = valid_dates.max().strftime('%Y-%m-%d')
                        
                        # 过滤数据，确保只包含请求的日期范围
                        data = data[(data['datetime'] >= start_dt) & (data['datetime'] <= end_dt)]
                        
                        # 设置索引
                        data.set_index('datetime', inplace=True)
                        
                        print(f"API请求成功: 获取到 {len(data)} 条记录")
                        return data
                    else:
                        print("API返回空数据")
                        return pd.DataFrame()
                else:
                    print("API响应格式错误：非JSON格式")
                    return pd.DataFrame()
            elif response.status_code == 500:
                # 服务器内部错误处理
                if retries < max_retries - 1:
                    print(f"服务器内部错误，尝试重试 ({retries+1}/{max_retries})")
                    retries += 1
                    time.sleep(2)  # 等待2秒后重试
                    continue
                else:
                    print(f"服务器内部错误，重试{max_retries}次后仍然失败")
                    # 检查是否是时间范围过小导致的问题
                    start_dt = pd.to_datetime(start_date)
                    end_dt = pd.to_datetime(end_date)
                    days_diff = (end_dt - start_dt).days
                    if days_diff <= 3:
                        print(f"请求的时间范围只有{days_diff}天，可能是周末或假期没有数据")
                    return pd.DataFrame()
            elif response.status_code == 401:
                print("认证错误: 用户名和密码不能为空")
                return pd.DataFrame()
            elif response.status_code == 402:
                print("认证错误: 账号不存在")
                return pd.DataFrame()
            elif response.status_code == 405:
                print("认证错误: 账号已过期")
                return pd.DataFrame()
            elif response.status_code == 406:
                print("认证错误: 密码错误")
                return pd.DataFrame()
            else:
                print(f"API请求失败: 状态码 {response.status_code}")
                if hasattr(response, 'json'):
                    try:
                        error_msg = response.json().get('error', '未知错误')
                        print(f"错误信息: {error_msg}")
                    except:
                        print(f"无法解析错误信息")
                return pd.DataFrame()
                
        except Exception as e:
            if retries < max_retries - 1:
                print(f"请求异常: {str(e)}，尝试重试 ({retries+1}/{max_retries})")
                retries += 1
                time.sleep(2)  # 等待2秒后重试
                continue
            else:
                print(f"请求异常: {str(e)}，重试{max_retries}次后仍然失败")
                return pd.DataFrame()
        
        # 如果没有继续循环，就跳出
        break
    
    return pd.DataFrame()  # 如果所有重试都失败，返回空DataFrame而不是None

def get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type):
    """获取缓存数据库路径和表名"""
    # 确保缓存目录存在
    os.makedirs(cache_dir, exist_ok=True)
    
    db_path = os.path.join(cache_dir, "backtest_data.db")
    
    # TICK数据没有复权概念，表名直接是 {symbol}_tick
    if kline_period.lower() == 'tick':
        table_name = f"{symbol}_tick"
    else:
        table_name = f"{symbol}_{kline_period}_{'hfq' if adjust_type == '1' else 'raw'}"
    
    return db_path, table_name

def save_to_sqlite(data, db_path, table_name):
    """保存数据到SQLite数据库"""
    # 确保目录存在（处理空目录的情况）
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    # 数据预处理：确保datetime列可以被SQLite正确处理
    data_copy = data.copy()
    
    # 处理datetime列（转换为字符串以避免timestamp转换问题）
    if 'datetime' in data_copy.columns:
        # 确保是datetime类型
        data_copy['datetime'] = pd.to_datetime(data_copy['datetime'], errors='coerce')
        
        # 移除时区信息（如果有）
        if isinstance(data_copy['datetime'].dtype, pd.DatetimeTZDtype):
            data_copy['datetime'] = data_copy['datetime'].dt.tz_localize(None)
        
        # 转换为字符串格式（避免timestamp转换错误）
        data_copy['datetime'] = data_copy['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    
    # 将所有inf和-inf替换为None
    data_copy = data_copy.replace([float('inf'), float('-inf')], None)
    
    # 使用事务保证数据一致性
    conn = None
    success = False
    try:
        # 使用绝对路径
        abs_db_path = os.path.abspath(db_path)
        conn = sqlite3.connect(abs_db_path)
        
        # 关闭自动提交模式
        conn.isolation_level = 'DEFERRED'
        
        # 先判断表是否存在，如果存在则删除
        cursor = conn.cursor()
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor.fetchone():
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        
        # 将数据保存到新表
        data_copy.to_sql(table_name, conn, if_exists='replace', index=False)
        
        # 显式提交事务
        conn.commit()
        success = True
        print(f"成功保存 {len(data_copy)} 条记录到 {table_name}")
    except Exception as e:
        # 出错时回滚
        if conn is not None and not success:
            try:
                conn.rollback()
            except sqlite3.OperationalError as rollback_error:
                print(f"回滚事务出错: {rollback_error}")
        print(f"保存数据到SQLite出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 确保连接关闭
        if conn is not None:
            conn.close()

def read_from_sqlite(db_path, table_name):
    """从SQLite数据库读取数据"""
    conn = None
    df = None
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        print(f"从 {table_name} 读取了 {len(df)} 条记录")
        return df
    except sqlite3.Error as e:
        print(f"SQLite读取错误: {e}")
        raise e
    except Exception as e:
        print(f"从SQLite读取数据出错: {e}")
        raise e
    finally:
        # 确保连接关闭
        if conn is not None:
            conn.close()
    return df  # 返回None或空DataFrame而不是引发异常

def append_to_sqlite(data, db_path, table_name):
    """
    追加数据到SQLite表（自动去重，避免重复写入）
    
    Args:
        data: 要追加的数据（DataFrame）
        db_path: 数据库路径
        table_name: 表名
        
    Returns:
        int: 实际新增的记录数
    """
    if data is None or data.empty:
        return 0
    
    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    # 数据预处理：确保datetime列可以被SQLite正确处理
    data = data.copy()
    
    # 处理datetime列（转换为字符串以避免timestamp转换问题）
    if 'datetime' in data.columns:
        data['datetime'] = pd.to_datetime(data['datetime'], errors='coerce')
        
        # 移除时区信息（如果有）
        if isinstance(data['datetime'].dtype, pd.DatetimeTZDtype):
            data['datetime'] = data['datetime'].dt.tz_localize(None)
        
        # 转换为字符串格式（避免timestamp转换错误）
        data['datetime'] = data['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    
    # 将所有inf和-inf替换为None
    data = data.replace([float('inf'), float('-inf')], None)
    
    conn = None
    new_records = 0
    
    try:
        # 使用绝对路径
        abs_db_path = os.path.abspath(db_path)
        conn = sqlite3.connect(abs_db_path)
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            # 表不存在，直接创建并写入所有数据
            data.to_sql(table_name, conn, if_exists='replace', index=False)
            new_records = len(data)
        else:
            # 表存在，检查并添加缺失的列
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {row[1] for row in cursor.fetchall()}
            new_columns = set(data.columns) - existing_columns
            
            if new_columns:
                for col in new_columns:
                    # 获取该列的数据类型
                    dtype = data[col].dtype
                    if dtype == 'object':
                        sql_type = 'TEXT'
                    elif dtype == 'float64':
                        sql_type = 'REAL'
                    elif dtype == 'int64':
                        sql_type = 'INTEGER'
                    else:
                        sql_type = 'TEXT'
                    
                    try:
                        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {sql_type}")
                    except Exception as e:
                        pass  # 列可能已存在
                conn.commit()
            
            # 表存在，读取已有数据进行去重
            try:
                # 只读取datetime列用于去重判断
                existing = pd.read_sql_query(f"SELECT datetime FROM {table_name}", conn)
                
                if not existing.empty:
                    # datetime已经是字符串格式，直接比较
                    existing_dates = set(existing['datetime'])
                    
                    # 过滤掉已存在的数据
                    if 'datetime' in data.columns:
                        # datetime列是字符串，直接比较
                        new_data = data[~data['datetime'].isin(existing_dates)]
                        
                        if not new_data.empty:
                            # 追加新数据
                            new_data.to_sql(table_name, conn, if_exists='append', index=False)
                            new_records = len(new_data)
                    else:
                        # 如果没有datetime列，直接追加
                        data.to_sql(table_name, conn, if_exists='append', index=False)
                        new_records = len(data)
                else:
                    # 表存在但为空，直接追加
                    data.to_sql(table_name, conn, if_exists='append', index=False)
                    new_records = len(data)
                    
            except Exception as e:
                # 如果读取失败，尝试直接追加（可能会有重复）
                data.to_sql(table_name, conn, if_exists='append', index=False)
                new_records = len(data)
        
        conn.commit()
        
    except Exception as e:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
    
    return new_records 