import requests
import pandas as pd
from datetime import datetime, timedelta
from io import StringIO
import os
import time
import sqlite3
import functools
import threading

# 数据库写入锁 - 确保对同一个数据库文件的写入是串行的
_db_write_locks = {}  # {db_path: threading.Lock()}
_db_locks_lock = threading.Lock()  # 用于保护 _db_write_locks 字典的锁

def _get_db_lock(db_path: str) -> threading.Lock:
    """获取指定数据库文件的写入锁（线程安全）"""
    abs_path = os.path.abspath(db_path)
    if abs_path not in _db_write_locks:
        with _db_locks_lock:
            if abs_path not in _db_write_locks:
                _db_write_locks[abs_path] = threading.Lock()
    return _db_write_locks[abs_path]

def _insert_dataframe(cursor, table_name: str, df) -> int:
    """使用原生SQL INSERT插入DataFrame数据（避免pandas to_sql的问题）"""
    if df is None or df.empty:
        return 0

    columns = df.columns.tolist()
    placeholders = ', '.join(['?' for _ in columns])
    col_names = ', '.join([f'"{col}"' for col in columns])
    insert_sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'

    # 将DataFrame转换为元组列表
    rows = [tuple(row) for row in df.values]

    # 批量插入
    cursor.executemany(insert_sql, rows)
    return len(rows)

def append_kline_fast(data, db_path: str, table_name: str) -> int:
    """
    快速追加K线数据（不做去重检查，适用于实时K线）

    与 append_to_sqlite 的区别：
    - 不读取整个表进行去重（大幅提升性能）
    - 使用 INSERT OR IGNORE 避免重复插入
    - 适用于datetime唯一的实时K线数据

    Args:
        data: 要追加的数据（DataFrame或Dict）
        db_path: 数据库路径
        table_name: 表名

    Returns:
        int: 实际新增的记录数
    """
    if data is None:
        return 0

    # 转换为DataFrame
    if isinstance(data, dict):
        df = pd.DataFrame([data])
    else:
        df = data

    if df.empty:
        return 0

    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # 处理datetime列
    if 'datetime' in df.columns:
        df = df.copy()
        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        if hasattr(df['datetime'].dtype, 'tz') and df['datetime'].dt.tz is not None:
            df['datetime'] = df['datetime'].dt.tz_localize(None)
        df['datetime'] = df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')

    # 将inf替换为None
    df = df.replace([float('inf'), float('-inf')], None)

    # 获取数据库锁
    db_lock = _get_db_lock(db_path)
    new_records = 0

    with db_lock:
        conn = None
        try:
            abs_db_path = os.path.abspath(db_path)
            # 设置超时30秒，避免锁等待失败
            conn = sqlite3.connect(abs_db_path, timeout=30)
            cursor = conn.cursor()
            # 使用DELETE模式，写入更直接（避免WAL的延迟问题）
            cursor.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写

            # 检查表是否存在，不存在则创建
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            table_exists = cursor.fetchone() is not None

            if not table_exists:
                # 创建表
                columns_def = []
                for col in df.columns:
                    dtype = df[col].dtype
                    if dtype == 'object' or col == 'datetime':
                        sql_type = 'TEXT'
                    elif 'float' in str(dtype):
                        sql_type = 'REAL'
                    elif 'int' in str(dtype):
                        sql_type = 'INTEGER'
                    else:
                        sql_type = 'TEXT'
                    columns_def.append(f'"{col}" {sql_type}')

                create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(columns_def)})'
                cursor.execute(create_sql)

                # 为datetime列创建唯一索引（避免重复插入）
                if 'datetime' in df.columns:
                    try:
                        cursor.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "idx_{table_name}_datetime" ON "{table_name}" ("datetime")')
                    except:
                        pass
                conn.commit()
            else:
                # 表已存在，检查并添加缺少的列
                cursor.execute(f'PRAGMA table_info("{table_name}")')
                existing_cols = set(row[1] for row in cursor.fetchall())

                for col in df.columns:
                    if col not in existing_cols:
                        # 确定列类型
                        dtype = df[col].dtype
                        if dtype == 'object' or col == 'datetime':
                            sql_type = 'TEXT'
                        elif 'float' in str(dtype):
                            sql_type = 'REAL'
                        elif 'int' in str(dtype):
                            sql_type = 'INTEGER'
                        else:
                            sql_type = 'TEXT'

                        # 添加缺少的列
                        try:
                            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {sql_type}')
                            # print(f"[DB] 表 {table_name} 添加新列: {col}")
                        except Exception:
                            pass  # 列可能已存在（并发情况）

                conn.commit()

            # 使用 INSERT OR IGNORE 直接插入（如果datetime重复则忽略）
            columns = df.columns.tolist()
            placeholders = ', '.join(['?' for _ in columns])
            col_names = ', '.join([f'"{col}"' for col in columns])
            insert_sql = f'INSERT OR IGNORE INTO "{table_name}" ({col_names}) VALUES ({placeholders})'

            rows = [tuple(row) for row in df.values]
            cursor.executemany(insert_sql, rows)
            new_records = cursor.rowcount
            conn.commit()

        except Exception as e:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    return new_records

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

    def get_next_trading_day(self, date_input) -> str:
        """
        获取指定日期之后的下一个交易日

        用于日线聚合：夜盘K线归属到下一个交易日
        例如：
        - 周五夜盘 → 下一个交易日是周一
        - 节假日前夜盘 → 下一个交易日是节后第一天

        Args:
            date_input: 日期，可以是字符串(YYYYMMDD或YYYY-MM-DD)、datetime、pd.Timestamp

        Returns:
            str: 下一个交易日，格式 YYYY-MM-DD
        """
        # 统一日期格式
        if isinstance(date_input, str):
            if len(date_input) == 8 and '-' not in date_input:
                date_input = f"{date_input[:4]}-{date_input[4:6]}-{date_input[6:]}"
            target_date = pd.to_datetime(date_input)
        else:
            target_date = pd.to_datetime(date_input)

        target_str = target_date.strftime('%Y-%m-%d')

        # 如果有交易日历数据，从中查找
        if self.trading_days and len(self.trading_days) > 0:
            try:
                next_days = [d for d in self.trading_days if d > target_str]
                if next_days:
                    return next_days[0]
            except Exception:
                pass

        # 回退方案：简单加一天（只跳过周末）
        next_date = target_date + timedelta(days=1)
        while next_date.weekday() >= 5:
            next_date += timedelta(days=1)
        return next_date.strftime('%Y-%m-%d')

    def get_prev_trading_day(self, trading_day):
        """
        根据交易日获取上一个交易日（即夜盘实际发生的自然日）

        用于处理 CTP 的 TradingDay：
        - 周五夜盘 21:00，TradingDay 是周一，上一个交易日是周五
        - 节假日前夜盘，TradingDay 是节后第一个交易日，上一个交易日是节前最后一个交易日

        Args:
            trading_day: 交易日，可以是字符串(YYYYMMDD或YYYY-MM-DD)、datetime对象

        Returns:
            str: 上一个交易日，格式 YYYY-MM-DD；如果找不到返回 None
        """
        # 统一日期格式
        if isinstance(trading_day, str):
            # 支持 YYYYMMDD 和 YYYY-MM-DD 两种格式
            if len(trading_day) == 8 and '-' not in trading_day:
                trading_day = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:]}"
            target_date = pd.to_datetime(trading_day)
        else:
            target_date = pd.to_datetime(trading_day)

        target_str = target_date.strftime('%Y-%m-%d')

        # 如果有交易日历数据，从中查找
        if self.trading_days and len(self.trading_days) > 0:
            try:
                # 找到 trading_day 在列表中的位置
                if target_str in self.trading_days:
                    idx = self.trading_days.index(target_str)
                    if idx > 0:
                        return self.trading_days[idx - 1]
                else:
                    # trading_day 不在列表中，找小于它的最大交易日
                    prev_days = [d for d in self.trading_days if d < target_str]
                    if prev_days:
                        return prev_days[-1]
            except Exception:
                pass

        # 回退方案：简单减一天（只跳过周末）
        prev_date = target_date - timedelta(days=1)
        while prev_date.weekday() >= 5:  # 跳过周末
            prev_date -= timedelta(days=1)
        return prev_date.strftime('%Y-%m-%d')

# 创建全局交易日历对象
trading_calendar = TradingCalendar()

# 添加实用函数
def is_trading_day(date):
    """检查日期是否为交易日"""
    return trading_calendar.is_trading_day(date)

def get_trading_date_range(start_date, end_date):
    """获取实际的交易日期范围"""
    return trading_calendar.get_trading_date_range(start_date, end_date)

def get_next_trading_day(date_input):
    """获取指定日期之后的下一个交易日"""
    return trading_calendar.get_next_trading_day(date_input)

def get_prev_trading_day(trading_day):
    """根据交易日获取上一个交易日"""
    return trading_calendar.get_prev_trading_day(trading_day)

def get_futures_data(
    symbol,
    start_date=None,
    end_date=None,
    username=None,
    password=None,
    kline_period='D',
    adjust_type='0',
    depth='no',
    use_cache=True,
    cache_dir='data_cache',
    save_data=False,
    start_time=None,
    end_time=None,
    limit=None
):
    """
    从API获取期货数据

    支持三种请求方式（按优先级）:
    1. 精确时间范围: start_time/end_time  (如 '2026-02-11 09:00:00')
    2. 日期范围: start_date/end_date  (如 '2026-02-11')
    3. BAR线数量: limit  (如 500，获取最近500根K线)

    可以组合使用:
    - start_date + limit: 从某日期开始取N根
    - start_time + limit: 从某时间开始取N根
    - 仅 limit: 取最近N根

    Args:
        symbol (str): 期货代码，如"AP888"
        start_date (str): 开始日期，格式为"YYYY-MM-DD"（可选）
        end_date (str): 结束日期，格式为"YYYY-MM-DD"（可选）
        username (str): API用户名/手机号
        password (str): API密码
        kline_period (str): K线周期，支持分钟(1M,5M等)、天(1D)、周(1W)、月(1Y)
        adjust_type (str): 复权类型，0(不复权)、1(后复权)或2(前复权)
        depth (str): 是否获取交易数据统计，"yes"或"no"
        use_cache (bool): 是否使用缓存数据
        cache_dir (str): 缓存目录
        save_data (bool): 是否保存数据，即使use_cache=False
        start_time (str): 精确开始时间，格式为"YYYY-MM-DD HH:MM:SS"（可选）
        end_time (str): 精确结束时间，格式为"YYYY-MM-DD HH:MM:SS"（可选）
        limit (int): 请求的K线数量（可选，获取最近N根）

    Returns:
        pd.DataFrame: 包含OHLCV数据的DataFrame
    """
    # ========== 本地复权开关控制 ==========
    # ENABLE_REMOTE_ADJUST=True 时允许本地复权 (ssquant/data/local_adjust.py)
    # adjust_type: '0'=不复权, '1'=后复权, '2'=前复权
    try:
        from ..config.trading_config import ENABLE_REMOTE_ADJUST
    except ImportError:
        ENABLE_REMOTE_ADJUST = True

    if not ENABLE_REMOTE_ADJUST and adjust_type != '0':
        print(f"[注意] 本地复权已禁用 (ENABLE_REMOTE_ADJUST=False)，adjust_type 已从 '{adjust_type}' 强制改为 '0'")
        adjust_type = '0'

    # ========== v0.4.6 复权重定向 ==========
    # 远程数据库只存 raw 数据，复权由本地 apply_local_adjust 在内存中计算（含 _adjust_factor 列）。
    # 因此本函数内部所有缓存读写、远程 API 请求统一走 raw 路径（adjust_type='0'），
    # 出口处再按用户请求的 _user_adjust_type 现场复权。
    # 旧的 xxx_d_hfq / xxx_d_qfq 缓存表本版本起完全不再读写（保留磁盘上不删）。
    _user_adjust_type = str(adjust_type or '0')
    _is_kline = kline_period.lower() != 'tick'
    if _is_kline:
        adjust_type = '0'

    def _exit_with_adjust(data):
        """K 线统一出口：把 raw 数据按 _user_adjust_type 现场复权后返回。
        非 K 线（tick）或空数据原样返回。"""
        if data is None or (hasattr(data, 'empty') and data.empty):
            return data
        if not _is_kline:
            return data
        from .local_adjust import apply_local_adjust
        return apply_local_adjust(data, symbol, kline_period, _user_adjust_type)

    def _clip_to_range(d, sdt, edt):
        """把 API 直取的数据严格裁到 [sdt, edt]，与缓存命中路径对齐。
        API 在边界日可能多吐邻近交易日的 bar，不裁会导致首次跑 vs 后续跑不一致。"""
        if d is None or (hasattr(d, 'empty') and d.empty):
            return d
        if sdt is None and edt is None:
            return d
        if isinstance(d.index, pd.DatetimeIndex):
            idx = d.index
            if isinstance(idx.dtype, pd.DatetimeTZDtype):
                idx = idx.tz_localize(None)
            mask = pd.Series(True, index=d.index)
            if sdt is not None:
                mask &= (idx >= sdt)
            if edt is not None:
                mask &= (idx <= edt)
            return d[mask.values]
        return d


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
            # 按数量获取 TICK 数据
            if limit and not start_date and not end_date and not start_time and not end_time:
                conn = sqlite3.connect(db_path, timeout=30)
                cursor = conn.cursor()
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                if not cursor.fetchone():
                    print(f"❌ TICK表不存在: {table_name}")
                    conn.close()
                    return pd.DataFrame()
                query = f"""
                    SELECT * FROM (
                        SELECT * FROM "{table_name}"
                        ORDER BY datetime DESC
                        LIMIT ?
                    ) sub ORDER BY datetime ASC
                """
                data = pd.read_sql_query(query, conn, params=(limit,))
                conn.close()
                if data.empty:
                    print(f"❌ TICK表无数据: {table_name}")
                    return pd.DataFrame()
                data['datetime'] = pd.to_datetime(data['datetime'], format='mixed')
                data = data.set_index('datetime')
                data['datetime'] = data.index
                print(f"✅ 成功加载 {len(data)} 条TICK数据 (limit={limit})")
                print(f"数据范围: {data.index[0]} 至 {data.index[-1]}")
                print("="*80)
                return data

            data = read_from_sqlite(db_path, table_name)

            if data is None or data.empty:
                print(f"❌ TICK表为空或不存在: {table_name}")
                # 列出可用的tick表（sqlite3已在顶层导入）
                conn = sqlite3.connect(db_path, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_tick'")
                available = [row[0] for row in cursor.fetchall()]
                conn.close()
                if available:
                    print(f"可用的TICK表: {available}")
                else:
                    print("数据库中没有TICK表，请先采集TICK数据")
                return pd.DataFrame()

            # 转换datetime（支持带毫秒和不带毫秒的格式）
            data['datetime'] = pd.to_datetime(data['datetime'], format='mixed')

            # 按时间/日期筛选
            if start_time or end_time:
                # 精确时间模式
                tick_start = pd.to_datetime(start_time) if start_time else data['datetime'].min()
                tick_end = pd.to_datetime(end_time) if end_time else data['datetime'].max()
            elif start_date or end_date:
                # 日期模式
                tick_start = pd.to_datetime(start_date) if start_date else data['datetime'].min()
                tick_end = (pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)) if end_date else data['datetime'].max()
            else:
                tick_start = data['datetime'].min()
                tick_end = data['datetime'].max()

            data = data[(data['datetime'] >= tick_start) & (data['datetime'] <= tick_end)]

            # 如果指定了 limit，截取最近 N 条
            if limit and len(data) > limit:
                data = data.tail(limit)

            if data.empty:
                print(f"❌ 指定范围内没有TICK数据")
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
    # 注意: username/password 的空值检查推迟到实际调用 fetch_data_from_api 之前
    # 这样本地 SQLite 缓存完全覆盖时无需账号即可直接返回数据

    # ========== 判断请求模式 ==========
    # 模式优先级: start_time/end_time > start_date/end_date > limit
    use_limit_only = False
    use_time_range = False

    if start_time or end_time:
        # 模式A: 精确时间范围
        use_time_range = True
    elif start_date or end_date:
        # 模式B: 日期范围（原有逻辑）
        use_time_range = False
    elif limit:
        # 模式C: 仅按数量获取最近N根
        use_limit_only = True
    else:
        raise ValueError("必须提供 start_date/end_date、start_time/end_time 或 limit 中的至少一个")

    print("="*80)
    from .local_adjust import get_adjust_label
    print(f"【数据请求开始】{symbol} {kline_period} {get_adjust_label(adjust_type)}")
    print("="*80)

    # ========== 模式C: 仅按数量获取 ==========
    if use_limit_only:
        print(f"请求模式: 按数量获取最近 {limit} 根K线")
        data = fetch_data_from_api(symbol, None, None, username, password,
                                   kline_period, adjust_type, depth, limit=limit)
        if data is not None and not data.empty:
            if save_data:
                db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
                try:
                    save_to_sqlite(data.reset_index(), db_path, table_name)
                except Exception as e:
                    print(f"缓存更新失败: {e}")
            print(f"返回数据条数: {len(data)}")
            print("="*80)
            return _exit_with_adjust(data)
        else:
            print("未能获取任何数据或数据为空")
            print("="*80)
            return pd.DataFrame()

    # ========== 模式A: 精确时间范围 ==========
    if use_time_range:
        _start = start_time or (start_date + ' 00:00:00' if start_date else None)
        _end = end_time or (end_date + ' 23:59:59' if end_date else None)
        print(f"请求模式: 精确时间范围")
        print(f"  start_time: {_start or '(不限)'}")
        print(f"  end_time: {_end or '(不限)'}")
        if limit:
            print(f"  limit: {limit}")

        data = fetch_data_from_api(symbol, None, None, username, password,
                                   kline_period, adjust_type, depth,
                                   start_time=_start, end_time=_end, limit=limit)
        if data is not None and not data.empty:
            if save_data:
                db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
                try:
                    save_to_sqlite(data.reset_index(), db_path, table_name)
                except Exception as e:
                    print(f"缓存更新失败: {e}")
            print(f"返回数据条数: {len(data)}")
            print("="*80)
            return _exit_with_adjust(data)
        else:
            print("未能获取任何数据或数据为空")
            print("="*80)
            return pd.DataFrame()

    # ========== 模式B: 日期范围（原有逻辑）==========
    # 获取当前系统时间并显示
    current_date = pd.to_datetime(datetime.now().date())
    print(f"请求模式: 日期范围")
    print(f"当前系统日期: {current_date.strftime('%Y-%m-%d')}")
    print(f"原始请求日期范围: {start_date} 到 {end_date}")

    # 转换日期字符串为datetime对象，用于比较
    # 容错处理：如果日期无效（如2月31日、4月31日），自动修正为有效日期
    import re

    def _parse_date_safe(date_str, default_dt, is_end=False):
        """安全解析日期字符串，处理无效日期（如4月31日）"""
        if not date_str:
            return default_dt, None
        try:
            dt = pd.to_datetime(date_str)
            return dt, None
        except Exception:
            # 尝试提取年月，修正为月初/月末
            match = re.match(r'(\d{4})\-(\d{1,2})', str(date_str))
            if match:
                year, month = int(match.group(1)), int(match.group(2))
                try:
                    if is_end:
                        dt = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
                        fixed_str = dt.strftime('%Y-%m-%d')
                        print(f"日期修正: 无效日期 '{date_str}' -> {fixed_str}")
                        return dt, fixed_str
                    else:
                        dt = pd.Timestamp(year=year, month=month, day=1)
                        fixed_str = dt.strftime('%Y-%m-%d')
                        print(f"日期修正: 无效日期 '{date_str}' -> {fixed_str}")
                        return dt, fixed_str
                except Exception:
                    pass
            # 完全无法解析，使用默认日期
            print(f"日期修正: 无法解析 '{date_str}'，使用默认日期 {default_dt.strftime('%Y-%m-%d')}")
            return default_dt, default_dt.strftime('%Y-%m-%d')

    start_dt, start_fixed = _parse_date_safe(start_date, current_date - pd.Timedelta(days=365), is_end=False)
    if start_fixed:
        start_date = start_fixed

    end_dt, end_fixed = _parse_date_safe(end_date, current_date, is_end=True)
    if end_fixed:
        end_date = end_fixed

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

    # 注意：end_dt 需要包含当天全天的数据，所以设置为当天 23:59:59
    # 这一步必须在 if 分支外执行，否则单日请求（如22日到22日）时 end_dt 仍为 00:00:00
    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    # 检查缓存
    if use_cache:
        db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
        if os.path.exists(db_path):
            print(f"使用缓存数据: {db_path}")
            try:
                used_raw_cache_fallback = False
                try:
                    data = read_from_sqlite(db_path, table_name)
                except Exception:
                    if str(adjust_type) == '2':
                        _, raw_table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, '0')
                        print(f"qfq缓存不可用，尝试回退到 raw 缓存: {raw_table_name}")
                        data = read_from_sqlite(db_path, raw_table_name)
                        used_raw_cache_fallback = True
                    else:
                        raise

                # 检查数据是否为空
                if data is None or data.empty:
                    print("缓存数据为空，将从API重新获取数据")
                    raise ValueError("缓存数据为空")

                data['datetime'] = pd.to_datetime(data['datetime'])
                if used_raw_cache_fallback:
                    from .local_adjust import apply_local_adjust
                    data = apply_local_adjust(data, symbol, kline_period, adjust_type)

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
                    return _exit_with_adjust(filtered_data)
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
                        return _exit_with_adjust(filtered_data)
                    else:
                        # 没有成功获取到任何新数据，使用已有的部分缓存数据
                        if has_data_in_range:
                            print(f"使用缓存中的有效数据 ({len(data_in_range)} 条记录)")
                            filtered_data = data_in_range
                            filtered_data.set_index('datetime', inplace=True)
                            print("="*80)
                            return _exit_with_adjust(filtered_data)
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
                                # 与缓存命中路径对齐：严格裁到 [start_dt, end_dt]
                                new_data = _clip_to_range(new_data, start_dt, end_dt)
                                print(f"返回数据条数: {len(new_data)}")
                                print("="*80)
                                return _exit_with_adjust(new_data)
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

    if data is not None and not data.empty:
        # 可选：缓存数据到本地
        if use_cache or save_data:
            db_path, table_name = get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type)
            try:
                save_to_sqlite(data.reset_index(), db_path, table_name)
            except Exception as e:
                print(f"缓存更新失败: {e}")
        # 与缓存命中路径对齐：严格裁到 [start_dt, end_dt]
        data = _clip_to_range(data, start_dt, end_dt)
        print(f"返回数据条数: {len(data)}")
        print("="*80)
        return _exit_with_adjust(data)
    else:
        print("未能获取任何数据或数据为空")
        print("="*80)
        return pd.DataFrame()  # 返回空DataFrame而不是None

def _try_data_server_api(symbol, start_date=None, end_date=None, kline_period='1M',
                         adjust_type='0', depth='no',
                         start_time=None, end_time=None, limit=None):
    """
    尝试从 data_server REST API 获取数据（鉴权通过后优先使用）

    data_server 负责从 1M 聚合为目标周期，客户端直接请求目标周期即可。
    如果上层需要复权，在返回后由 apply_local_adjust() 进行本地复权。

    支持三种请求模式:
    1. 精确时间范围: start_time/end_time
    2. 日期范围: start_date/end_date
    3. 按数量获取: limit

    Returns:
        DataFrame（成功）或 None（data_server 无数据或不可用）
    """
    try:
        from .auth_manager import get_ordered_data_server_api_bases
        api_bases = get_ordered_data_server_api_bases()
        if not api_bases:
            return None

        normalized_period = kline_period.strip().upper()

        # 直接请求目标周期（data_server 服务端完成 1M→目标周期 的聚合）
        params = {
            'symbol': symbol.lower(),
            'period': normalized_period,
            'adjust_type': '0',
        }

        # 根据请求模式填充参数
        if start_time or end_time:
            if start_time:
                params['start_time'] = start_time
            if end_time:
                params['end_time'] = end_time
            desc = f"({start_time or '...'}~{end_time or '...'})"
        elif start_date or end_date:
            if start_date:
                params['start_date'] = start_date
            if end_date:
                params['end_date'] = end_date
            desc = f"({start_date or '...'}~{end_date or '...'})"
        else:
            desc = ""

        if limit:
            params['limit'] = limit
            desc = f"(limit={limit})" if not desc else f"{desc} limit={limit}"
        elif 'start_time' not in params and 'start_date' not in params:
            params['limit'] = 5000
            desc = "(limit=5000 default)"

        for api_base in api_bases:
            url = f"{api_base}/api/futures/history"
            try:
                resp = requests.get(url, params=params, timeout=(20, 180))
            except requests.exceptions.ConnectionError:
                continue
            except Exception:
                continue

            if resp.status_code != 200:
                continue

            try:
                result = resp.json()
            except Exception:
                continue

            if result.get('code') != 0:
                continue

            data_obj = result.get('data', {})
            records = data_obj.get('klines', []) if isinstance(data_obj, dict) else data_obj

            if not records:
                continue

            df = pd.DataFrame(records)

            if df.empty or 'datetime' not in df.columns:
                continue

            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
            df = df[~df.index.duplicated(keep='last')]

            print(f"[data_server API] 获取 {normalized_period} 数据: {symbol} {desc} {len(df)} 条 (via {api_base})")

            # 本地复权（当前为占位直通，后续实现算法后自动生效）
            if adjust_type != '0':
                from .local_adjust import apply_local_adjust
                df = apply_local_adjust(df, symbol, kline_period, adjust_type)

            return df

        return None

    except Exception:
        return None


def fetch_data_from_api(symbol, start_date, end_date, username, password,
                        kline_period, adjust_type, depth, max_retries=3,
                        start_time=None, end_time=None, limit=None):
    """
    从API获取数据的辅助函数

    数据源: 仅使用 data_server API（kanpan789 仅用于鉴权，不用于数据获取）

    支持三种请求模式:
    1. 精确时间范围: start_time/end_time
    2. 日期范围: start_date/end_date
    3. 按数量获取: limit
    """
    # ========== 鉴权检查 ==========
    from .auth_manager import verify_auth
    if not verify_auth(username, password):
        from .auth_manager import get_auth_message
        print(f"[数据请求] 鉴权失败: {get_auth_message()}，无法获取数据")
        return pd.DataFrame()

    # ========== 从 data_server API 获取 ==========
    ds_df = _try_data_server_api(symbol, start_date, end_date, kline_period, adjust_type, depth,
                                  start_time=start_time, end_time=end_time, limit=limit)
    if ds_df is not None:
        return ds_df

    # data_server 不可用或无数据
    req_desc = f"({start_time or start_date or ''}~{end_time or end_date or ''})"
    if limit:
        req_desc += f" limit={limit}"
    print(f"[数据请求] data_server 无法获取 {symbol} {kline_period} {req_desc}")
    print(f"[数据请求] 请确认 data_server 是否已启动，以及数据库中是否有对应数据")
    return pd.DataFrame()

def get_cache_db_and_table(symbol, kline_period, cache_dir, adjust_type):
    """获取缓存数据库路径和表名"""
    # 确保缓存目录存在
    os.makedirs(cache_dir, exist_ok=True)

    db_path = os.path.join(cache_dir, "backtest_data.db")

    # TICK数据没有复权概念，表名直接是 {symbol}_tick
    if kline_period.lower() == 'tick':
        table_name = f"{symbol}_tick"
    else:
        from .local_adjust import get_adjust_suffix
        table_name = f"{symbol}_{kline_period}_{get_adjust_suffix(adjust_type)}"

    return db_path, table_name

def save_to_sqlite(data, db_path, table_name):
    """保存数据到SQLite数据库（使用数据库锁保证线程安全）"""
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

    # 获取数据库写入锁（确保同一数据库的写入是串行的）
    db_lock = _get_db_lock(db_path)
    replace_all = table_name.lower().endswith('_qfq')

    with db_lock:  # 加锁
        conn = None
        success = False
        try:
            # 使用绝对路径
            abs_db_path = os.path.abspath(db_path)
            conn = sqlite3.connect(abs_db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写

            if not data_copy.empty:
                # 检查表是否存在（大小写不敏感）
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND LOWER(name)=LOWER('{table_name}')")
                result = cursor.fetchone()

                if result:
                    # 表存在：使用实际表名
                    actual_table_name = result[0]
                    table_name = actual_table_name  # 使用实际表名

                    # 检查并自动添加缺失的列
                    cursor.execute(f'PRAGMA table_info("{table_name}")')
                    existing_columns = {row[1].lower() for row in cursor.fetchall()}

                    for col in data_copy.columns:
                        if col.lower() not in existing_columns:
                            # 根据数据类型确定SQL类型
                            dtype = data_copy[col].dtype
                            if pd.api.types.is_integer_dtype(dtype):
                                sql_type = 'INTEGER'
                            elif pd.api.types.is_float_dtype(dtype):
                                sql_type = 'REAL'
                            else:
                                sql_type = 'TEXT'

                            # 添加新列
                            alter_sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {sql_type}'
                            cursor.execute(alter_sql)
                            print(f"[自动添加列] {table_name}.{col} ({sql_type})")

                    # 清空数据后插入
                    cursor.execute(f'DELETE FROM "{actual_table_name}"')
                else:
                    # 表不存在：创建新表
                    columns_def = []
                    for col in data_copy.columns:
                        dtype = data_copy[col].dtype
                        if pd.api.types.is_integer_dtype(dtype):
                            sql_type = 'INTEGER'
                        elif pd.api.types.is_float_dtype(dtype):
                            sql_type = 'REAL'
                        else:
                            sql_type = 'TEXT'
                        columns_def.append(f'"{col}" {sql_type}')

                    create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(columns_def)})'
                    cursor.execute(create_sql)

                # 批量插入数据
                columns = data_copy.columns.tolist()
                placeholders = ', '.join(['?' for _ in columns])
                col_names = ', '.join([f'"{col}"' for col in columns])
                insert_sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'

                rows = [tuple(row) for row in data_copy.values]
                cursor.executemany(insert_sql, rows)
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
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写
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

        # 判断是否是TICK数据（表名含_tick或数据有毫秒）
        is_tick_data = '_tick' in table_name.lower()

        if is_tick_data:
            # TICK数据保留毫秒精度（格式：2026-01-06 10:34:00.500）
            def format_with_ms(dt):
                if pd.isna(dt):
                    return ''
                return dt.strftime('%Y-%m-%d %H:%M:%S.') + f'{dt.microsecond // 1000:03d}'
            data['datetime'] = data['datetime'].apply(format_with_ms)
        else:
            # K线数据只需要秒级精度
            data['datetime'] = data['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')

    # 将所有inf和-inf替换为None
    data = data.replace([float('inf'), float('-inf')], None)

    conn = None
    new_records = 0

    # 获取数据库写入锁（确保同一数据库的写入是串行的）
    db_lock = _get_db_lock(db_path)
    replace_all = table_name.lower().endswith('_qfq')

    with db_lock:  # 加锁
        try:
            # 使用绝对路径
            abs_db_path = os.path.abspath(db_path)
            conn = sqlite3.connect(abs_db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写

            # 检查表是否存在，不存在则先创建空表
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            table_exists = cursor.fetchone() is not None

            if not table_exists:
                # 表不存在，先手动创建表结构
                # 根据DataFrame的列名和类型生成CREATE TABLE语句
                columns_def = []
                for col in data.columns:
                    dtype = data[col].dtype
                    if dtype == 'object' or col == 'datetime':
                        sql_type = 'TEXT'
                    elif 'float' in str(dtype):
                        sql_type = 'REAL'
                    elif 'int' in str(dtype):
                        sql_type = 'INTEGER'
                    else:
                        sql_type = 'TEXT'
                    columns_def.append(f'"{col}" {sql_type}')

                create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(columns_def)})'
                cursor.execute(create_sql)
                conn.commit()
                table_exists = True  # 现在表已创建

            # 表已存在，执行追加逻辑
            if table_exists:
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

                if replace_all:
                    cursor.execute(f'DELETE FROM "{table_name}"')
                    new_records = _insert_dataframe(cursor, table_name, data)
                    conn.commit()
                    return

                # 表存在，读取已有数据进行去重
                try:
                    # 只读取datetime列用于去重判断
                    existing = pd.read_sql_query(f'SELECT datetime FROM "{table_name}"', conn)

                    if not existing.empty:
                        # datetime已经是字符串格式，直接比较
                        existing_dates = set(existing['datetime'])

                        # 过滤掉已存在的数据
                        if 'datetime' in data.columns:
                            # datetime列是字符串，直接比较
                            new_data = data[~data['datetime'].isin(existing_dates)]

                            if not new_data.empty:
                                # 使用原生SQL INSERT插入数据（避免pandas to_sql的问题）
                                new_records = _insert_dataframe(cursor, table_name, new_data)
                        else:
                            # 如果没有datetime列，直接追加
                            new_records = _insert_dataframe(cursor, table_name, data)
                    else:
                        # 表存在但为空，直接追加
                        new_records = _insert_dataframe(cursor, table_name, data)

                except Exception as e:
                    # 如果读取失败，尝试直接追加
                    new_records = _insert_dataframe(cursor, table_name, data)

            conn.commit()

        except Exception as e:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    return new_records