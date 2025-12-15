"""
数据导入DB示例 - 将本地数据导入SQLite数据库

支持的数据格式:
  - CSV  (.csv)      - 最常用的文本格式
  - Excel (.xlsx/.xls) - Microsoft Excel格式
  - JSON (.json)     - JavaScript对象表示法
  - Parquet (.parquet) - 列式存储，适合大数据
  - Feather (.feather) - 高性能二进制格式
  - Pickle (.pkl)    - Python序列化格式

数据库位置: data_cache/backtest_data.db
"""

import pandas as pd
import sqlite3
import os
from datetime import datetime
from typing import Optional


# ==================== 数据字段说明 ====================

"""
==================== TICK数据字段（CTP原始字段名）====================

必需字段:
    datetime        - 时间戳，格式: '2025-12-11 10:30:25.500' 或 datetime对象
    LastPrice       - 最新价（最近成交价）
    BidPrice1       - 买一价（最优买价）
    AskPrice1       - 卖一价（最优卖价）
    BidVolume1      - 买一量
    AskVolume1      - 卖一量
    Volume          - 累计成交量
    OpenInterest    - 持仓量

可选字段（完整CTP行情）:
    TradingDay      - 交易日，格式: '20251211'
    InstrumentID    - 合约代码，如 'rb2601'
    ExchangeID      - 交易所代码，如 'SHFE'
    PreSettlementPrice - 昨结算价
    PreClosePrice   - 昨收盘价
    PreOpenInterest - 昨持仓量
    OpenPrice       - 今开盘价
    HighestPrice    - 最高价
    LowestPrice     - 最低价
    Turnover        - 成交金额
    UpdateTime      - 更新时间，格式: '10:30:25'
    UpdateMillisec  - 毫秒数，如 500
    UpperLimitPrice - 涨停价
    LowerLimitPrice - 跌停价

数据库表名格式: {symbol}_tick
    例如: rb888_tick, au888_tick, IF2601_tick


==================== K线数据字段 ====================

必需字段:
    datetime        - K线时间戳，格式: '2025-12-11 10:30:00' 或 datetime对象
    open            - 开盘价
    high            - 最高价
    low             - 最低价
    close           - 收盘价
    volume          - 成交量

可选字段:
    amount          - 成交额
    open_interest   - 持仓量（期货）
    symbol          - 合约代码

数据库表名格式: {symbol}_{period}_{adjust}
    例如: rb888_1m_hfq (后复权), rb888_1h_raw (不复权), rb888_D_hfq (日线后复权)
    
    period取值: 1m, 5m, 15m, 30m, 1h, 4h, D, W, M
    adjust取值: hfq (后复权), raw (不复权)
"""


# ==================== 支持的文件格式 ====================
SUPPORTED_FORMATS = {
    '.csv': 'CSV (逗号分隔)',
    '.xlsx': 'Excel 2007+ (.xlsx)',
    '.xls': 'Excel 97-2003 (.xls)',
    '.json': 'JSON (JavaScript对象表示法)',
    '.parquet': 'Parquet (列式存储)',
    '.feather': 'Feather (高性能二进制)',
    '.pkl': 'Pickle (Python序列化)',
    '.pickle': 'Pickle (Python序列化)',
}


# ==================== 数据库路径配置 ====================
DB_PATH = "./data_cache/backtest_data.db"


def ensure_db_dir():
    """确保数据库目录存在"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
        print(f"✅ 创建目录: {db_dir}")


def get_file_format(file_path: str) -> Optional[str]:
    """获取文件格式"""
    _, ext = os.path.splitext(file_path.lower())
    if ext in SUPPORTED_FORMATS:
        return ext
    return None


def read_data_file(file_path: str) -> Optional[pd.DataFrame]:
    """
    读取各种格式的数据文件
    
    支持格式: CSV, Excel, JSON, Parquet, Feather, Pickle
    
    Args:
        file_path: 文件路径
        
    Returns:
        DataFrame或None（读取失败时）
    """
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return None
    
    ext = get_file_format(file_path)
    if ext is None:
        print(f"❌ 不支持的文件格式: {file_path}")
        print(f"💡 支持的格式: {', '.join(SUPPORTED_FORMATS.keys())}")
        return None
    
    try:
        print(f"📂 读取文件: {file_path}")
        print(f"📋 文件格式: {SUPPORTED_FORMATS[ext]}")
        
        if ext == '.csv':
            df = pd.read_csv(file_path)
            
        elif ext in ['.xlsx', '.xls']:
            # Excel文件可能需要openpyxl或xlrd
            try:
                df = pd.read_excel(file_path)
            except ImportError as e:
                if 'openpyxl' in str(e):
                    print("❌ 读取Excel需要安装openpyxl: pip install openpyxl")
                elif 'xlrd' in str(e):
                    print("❌ 读取.xls文件需要安装xlrd: pip install xlrd")
                else:
                    print(f"❌ 读取Excel失败: {e}")
                return None
                
        elif ext == '.json':
            # JSON可能是数组或对象格式
            try:
                df = pd.read_json(file_path)
            except ValueError:
                # 尝试按行读取（JSON Lines格式）
                df = pd.read_json(file_path, lines=True)
                
        elif ext == '.parquet':
            try:
                df = pd.read_parquet(file_path)
            except ImportError:
                print("❌ 读取Parquet需要安装pyarrow: pip install pyarrow")
                return None
                
        elif ext == '.feather':
            try:
                df = pd.read_feather(file_path)
            except ImportError:
                print("❌ 读取Feather需要安装pyarrow: pip install pyarrow")
                return None
                
        elif ext in ['.pkl', '.pickle']:
            df = pd.read_pickle(file_path)
            
        else:
            print(f"❌ 未实现的格式: {ext}")
            return None
        
        print(f"✅ 成功读取 {len(df)} 条记录")
        print(f"📋 列名: {list(df.columns)}")
        return df
        
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return None


def process_tick_dataframe(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    处理TICK数据DataFrame，统一字段名和格式
    
    Args:
        df: 原始DataFrame
        
    Returns:
        处理后的DataFrame或None
    """
    # 字段映射（兼容其他格式）
    field_mapping = {
        # 小写版本
        'last_price': 'LastPrice',
        'lastprice': 'LastPrice',
        'bid_price1': 'BidPrice1',
        'bidprice1': 'BidPrice1',
        'bid1': 'BidPrice1',
        'ask_price1': 'AskPrice1',
        'askprice1': 'AskPrice1',
        'ask1': 'AskPrice1',
        'bid_volume1': 'BidVolume1',
        'bidvolume1': 'BidVolume1',
        'ask_volume1': 'AskVolume1',
        'askvolume1': 'AskVolume1',
        'open_interest': 'OpenInterest',
        'openinterest': 'OpenInterest',
        'oi': 'OpenInterest',
        # 价格相关
        'price': 'LastPrice',
        'last': 'LastPrice',
        'close': 'LastPrice',  # 有些数据用close表示最新价
        # 成交量
        'vol': 'Volume',
        'qty': 'Volume',
    }
    
    # 执行字段映射
    df_columns_lower = {col.lower(): col for col in df.columns}
    for old_name, new_name in field_mapping.items():
        if old_name in df_columns_lower and new_name not in df.columns:
            df.rename(columns={df_columns_lower[old_name]: new_name}, inplace=True)
    
    # 检查必需字段
    required_fields = ['LastPrice', 'BidPrice1', 'AskPrice1', 'Volume']
    missing_fields = [f for f in required_fields if f not in df.columns]
    
    if missing_fields:
        print(f"❌ 缺少必需字段: {missing_fields}")
        print(f"💡 TICK数据必需字段: datetime, LastPrice, BidPrice1, AskPrice1, Volume")
        print(f"📋 当前列名: {list(df.columns)}")
        return None
    
    # 处理时间字段
    if 'datetime' not in df.columns:
        # 尝试从其他字段组合
        if 'TradingDay' in df.columns and 'UpdateTime' in df.columns:
            df['datetime'] = pd.to_datetime(
                df['TradingDay'].astype(str) + ' ' + df['UpdateTime'].astype(str)
            )
            if 'UpdateMillisec' in df.columns:
                df['datetime'] = df['datetime'] + pd.to_timedelta(df['UpdateMillisec'], unit='ms')
        elif 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['time'])
        elif 'date' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'])
        elif 'timestamp' in df.columns:
            df['datetime'] = pd.to_datetime(df['timestamp'])
        else:
            print("❌ 找不到时间字段（datetime/time/date/timestamp/TradingDay+UpdateTime）")
            return None
    else:
        df['datetime'] = pd.to_datetime(df['datetime'])
    
    # 按时间排序（不设置索引，保持datetime为普通列，与实时落盘一致）
    df.sort_values('datetime', inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # 统一TICK字段顺序（与实时落盘保持一致）
    # 标准顺序: datetime 在第一位，然后是 CTP 原始字段
    standard_order = [
        'datetime', 'InstrumentID', 'TradingDay', 'ActionDay', 
        'UpdateTime', 'UpdateMillisec', 'LastPrice', 'Volume', 'OpenInterest',
        'BidPrice1', 'AskPrice1', 'BidVolume1', 'AskVolume1',
        'BidPrice2', 'AskPrice2', 'BidVolume2', 'AskVolume2',
        'BidPrice3', 'AskPrice3', 'BidVolume3', 'AskVolume3',
        'BidPrice4', 'AskPrice4', 'BidVolume4', 'AskVolume4',
        'BidPrice5', 'AskPrice5', 'BidVolume5', 'AskVolume5',
        'Turnover', 'PreSettlementPrice', 'PreClosePrice', 'PreOpenInterest',
        'OpenPrice', 'HighestPrice', 'LowestPrice', 'ClosePrice',
        'UpperLimitPrice', 'LowerLimitPrice', 'SettlementPrice',
        'ExchangeID', 'ExchangeInstID'
    ]
    
    # 按标准顺序排列已有的列，其他列追加到末尾
    ordered_cols = []
    remaining_cols = df.columns.tolist()
    
    for col in standard_order:
        if col in remaining_cols:
            ordered_cols.append(col)
            remaining_cols.remove(col)
    
    # 追加标准顺序中没有的其他列
    ordered_cols.extend(remaining_cols)
    df = df[ordered_cols]
    
    return df


def process_kline_dataframe(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    处理K线数据DataFrame，统一字段名和格式
    
    Args:
        df: 原始DataFrame
        
    Returns:
        处理后的DataFrame或None
    """
    # 字段映射
    field_mapping = {
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume',
        'vol': 'volume',
        'qty': 'volume',
        'amount': 'amount',
        'turnover': 'amount',
        'open_interest': 'open_interest',
        'oi': 'open_interest',
        'OpenInterest': 'open_interest',
    }
    
    # 执行字段映射
    for old_name, new_name in field_mapping.items():
        if old_name in df.columns and new_name not in df.columns:
            df.rename(columns={old_name: new_name}, inplace=True)
    
    # 检查必需字段
    required_fields = ['open', 'high', 'low', 'close', 'volume']
    missing_fields = [f for f in required_fields if f not in df.columns]
    
    if missing_fields:
        print(f"❌ 缺少必需字段: {missing_fields}")
        print(f"💡 K线数据必需字段: datetime, open, high, low, close, volume")
        print(f"📋 当前列名: {list(df.columns)}")
        return None
    
    # 处理时间字段
    if 'datetime' not in df.columns:
        if 'date' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'])
        elif 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['time'])
        elif 'timestamp' in df.columns:
            df['datetime'] = pd.to_datetime(df['timestamp'])
        else:
            print("❌ 找不到时间字段（datetime/date/time/timestamp）")
            return None
    else:
        df['datetime'] = pd.to_datetime(df['datetime'])
    
    # 按时间排序（不设置索引，保持datetime为普通列，与实时落盘一致）
    df.sort_values('datetime', inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # 统一K线字段顺序（与API和实时落盘保持一致）
    # 标准顺序: datetime, symbol, open, high, low, close, volume, amount, openint/open_interest, cumulative_openint
    standard_order = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'amount', 'open_interest', 'openint', 'cumulative_openint']
    
    # 按标准顺序排列已有的列，其他列追加到末尾
    ordered_cols = []
    remaining_cols = df.columns.tolist()
    
    for col in standard_order:
        if col in remaining_cols:
            ordered_cols.append(col)
            remaining_cols.remove(col)
    
    # 追加标准顺序中没有的其他列
    ordered_cols.extend(remaining_cols)
    df = df[ordered_cols]
    
    return df


def import_tick_data(file_path: str, symbol: str, replace: bool = False) -> int:
    """
    从文件导入TICK数据到数据库
    
    支持格式: CSV, Excel, JSON, Parquet, Feather, Pickle
    
    Args:
        file_path: 文件路径
        symbol: 品种代码（如 'rb888', 'au888'）
        replace: 是否替换已有数据（True=替换，False=追加）
    
    Returns:
        导入的数据条数
    """
    print(f"\n{'='*60}")
    print(f"导入TICK数据")
    print(f"{'='*60}")
    
    # 读取文件
    df = read_data_file(file_path)
    if df is None:
        return 0
    
    # 处理数据
    df = process_tick_dataframe(df)
    if df is None:
        return 0
    
    print(f"📅 数据范围: {df['datetime'].iloc[0]} 至 {df['datetime'].iloc[-1]}")
    print(f"📊 数据列: {list(df.columns)}")
    
    # 写入数据库
    ensure_db_dir()
    table_name = f"{symbol}_tick"
    
    conn = sqlite3.connect(DB_PATH)
    try:
        if_exists = 'replace' if replace else 'append'
        # 使用 index=False，与实时落盘保持一致
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        print(f"✅ 成功导入 {len(df)} 条TICK数据到表 [{table_name}]")
        print(f"📁 数据库: {DB_PATH}")
    finally:
        conn.close()
    
    return len(df)


def import_kline_data(file_path: str, symbol: str, period: str = '1m', 
                      adjust: str = 'hfq', replace: bool = False) -> int:
    """
    从文件导入K线数据到数据库
    
    支持格式: CSV, Excel, JSON, Parquet, Feather, Pickle
    
    Args:
        file_path: 文件路径
        symbol: 品种代码（如 'rb888', 'au888'）
        period: K线周期（1m, 5m, 15m, 30m, 1h, 4h, D, W, M）
        adjust: 复权类型（hfq=后复权, raw=不复权）
        replace: 是否替换已有数据
    
    Returns:
        导入的数据条数
    """
    print(f"\n{'='*60}")
    print(f"导入K线数据")
    print(f"{'='*60}")
    
    # 读取文件
    df = read_data_file(file_path)
    if df is None:
        return 0
    
    # 处理数据
    df = process_kline_dataframe(df)
    if df is None:
        return 0
    
    print(f"📅 数据范围: {df['datetime'].iloc[0]} 至 {df['datetime'].iloc[-1]}")
    
    # 写入数据库
    ensure_db_dir()
    table_name = f"{symbol}_{period}_{adjust}"
    
    conn = sqlite3.connect(DB_PATH)
    try:
        if_exists = 'replace' if replace else 'append'
        # 使用 index=False，与实时落盘保持一致
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        print(f"✅ 成功导入 {len(df)} 条K线数据到表 [{table_name}]")
        print(f"📁 数据库: {DB_PATH}")
    finally:
        conn.close()
    
    return len(df)


def batch_import(folder_path: str, data_type: str = 'tick', 
                 period: str = '1m', adjust: str = 'hfq', replace: bool = False):
    """
    批量导入文件夹中的所有数据文件
    
    文件名格式要求: {symbol}_xxx.csv 或 {symbol}.csv
    例如: rb888_20251211.csv, au888.parquet
    
    Args:
        folder_path: 文件夹路径
        data_type: 数据类型 ('tick' 或 'kline')
        period: K线周期（仅data_type='kline'时有效）
        adjust: 复权类型（仅data_type='kline'时有效）
        replace: 是否替换已有数据
    """
    print(f"\n{'='*60}")
    print(f"批量导入 - {folder_path}")
    print(f"{'='*60}")
    
    if not os.path.exists(folder_path):
        print(f"❌ 文件夹不存在: {folder_path}")
        return
    
    # 获取所有支持的文件
    files = []
    for ext in SUPPORTED_FORMATS.keys():
        files.extend([f for f in os.listdir(folder_path) if f.lower().endswith(ext)])
    
    if not files:
        print(f"📭 未找到支持的数据文件")
        print(f"💡 支持的格式: {', '.join(SUPPORTED_FORMATS.keys())}")
        return
    
    print(f"📂 找到 {len(files)} 个文件")
    
    success_count = 0
    fail_count = 0
    
    for file_name in files:
        file_path = os.path.join(folder_path, file_name)
        
        # 从文件名提取symbol
        base_name = os.path.splitext(file_name)[0]
        symbol = base_name.split('_')[0]  # 取第一部分作为symbol
        
        print(f"\n--- 处理: {file_name} (symbol={symbol}) ---")
        
        try:
            if data_type == 'tick':
                count = import_tick_data(file_path, symbol, replace)
            else:
                count = import_kline_data(file_path, symbol, period, adjust, replace)
            
            if count > 0:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"❌ 导入失败: {e}")
            fail_count += 1
    
    print(f"\n{'='*60}")
    print(f"批量导入完成: 成功 {success_count} 个, 失败 {fail_count} 个")
    print(f"{'='*60}")


def list_db_tables():
    """列出数据库中的所有表"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return
    
    print(f"\n{'='*60}")
    print(f"数据库表列表: {DB_PATH}")
    print(f"{'='*60}")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        if not tables:
            print("📭 数据库为空，没有表")
            return
        
        print(f"\n共 {len(tables)} 个表:\n")
        
        for (table_name,) in tables:
            # 获取表的行数和列信息
            count = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
            cursor = conn.execute(f"PRAGMA table_info([{table_name}])")
            columns = [row[1] for row in cursor.fetchall()]
            
            # 判断数据类型
            if '_tick' in table_name:
                data_type = "TICK"
            elif any(p in table_name for p in ['_1m_', '_5m_', '_15m_', '_30m_', '_1h_', '_4h_', '_D_', '_W_', '_M_']):
                data_type = "K线"
            else:
                data_type = "未知"
            
            print(f"  📊 {table_name}")
            print(f"     类型: {data_type} | 记录数: {count:,}")
            print(f"     列: {', '.join(columns[:8])}{'...' if len(columns) > 8 else ''}")
            print()
    finally:
        conn.close()


def query_table_sample(table_name: str, limit: int = 5):
    """查询表的示例数据"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return
    
    print(f"\n{'='*60}")
    print(f"表 [{table_name}] 示例数据")
    print(f"{'='*60}")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql(f"SELECT * FROM [{table_name}] LIMIT {limit}", conn)
        print(f"\n前 {limit} 条记录:")
        print(df.to_string())
    except Exception as e:
        print(f"❌ 查询失败: {e}")
    finally:
        conn.close()


def create_sample_data():
    """创建各种格式的示例数据"""
    import numpy as np
    
    print("\n📝 创建示例数据...")
    
    # 生成示例TICK数据
    base_time = datetime(2025, 12, 11, 9, 0, 0)
    times = [base_time + pd.Timedelta(milliseconds=500*i) for i in range(100)]
    
    base_price = 3500.0
    prices = base_price + np.cumsum(np.random.randn(100) * 2)
    
    tick_df = pd.DataFrame({
        'datetime': times,
        'LastPrice': prices,
        'BidPrice1': prices - 1,
        'AskPrice1': prices + 1,
        'BidVolume1': np.random.randint(10, 100, 100),
        'AskVolume1': np.random.randint(10, 100, 100),
        'Volume': np.cumsum(np.random.randint(1, 10, 100)),
        'OpenInterest': 100000 + np.cumsum(np.random.randint(-50, 50, 100)),
    })
    
    # 生成示例K线数据
    kline_times = [base_time + pd.Timedelta(minutes=i) for i in range(100)]
    opens = [base_price]
    for i in range(1, 100):
        opens.append(opens[-1] + np.random.randn() * 5)
    
    kline_df = pd.DataFrame({
        'datetime': kline_times,
        'open': opens,
        'high': [o + abs(np.random.randn() * 3) for o in opens],
        'low': [o - abs(np.random.randn() * 3) for o in opens],
        'close': [o + np.random.randn() * 2 for o in opens],
        'volume': np.random.randint(100, 1000, 100),
        'open_interest': 100000 + np.cumsum(np.random.randint(-100, 100, 100)),
    })
    
    # 保存为不同格式
    sample_dir = "./sample_data"
    os.makedirs(sample_dir, exist_ok=True)
    
    formats_created = []
    
    # CSV
    tick_df.to_csv(f"{sample_dir}/sample_tick.csv", index=False)
    kline_df.to_csv(f"{sample_dir}/sample_kline.csv", index=False)
    formats_created.append("CSV")
    
    # JSON
    tick_df.to_json(f"{sample_dir}/sample_tick.json", orient='records', date_format='iso')
    kline_df.to_json(f"{sample_dir}/sample_kline.json", orient='records', date_format='iso')
    formats_created.append("JSON")
    
    # Pickle
    tick_df.to_pickle(f"{sample_dir}/sample_tick.pkl")
    kline_df.to_pickle(f"{sample_dir}/sample_kline.pkl")
    formats_created.append("Pickle")
    
    # Excel (需要openpyxl)
    try:
        tick_df.to_excel(f"{sample_dir}/sample_tick.xlsx", index=False)
        kline_df.to_excel(f"{sample_dir}/sample_kline.xlsx", index=False)
        formats_created.append("Excel")
    except ImportError:
        print("⚠️ Excel格式需要安装openpyxl: pip install openpyxl")
    
    # Parquet (需要pyarrow)
    try:
        tick_df.to_parquet(f"{sample_dir}/sample_tick.parquet", index=False)
        kline_df.to_parquet(f"{sample_dir}/sample_kline.parquet", index=False)
        formats_created.append("Parquet")
    except ImportError:
        print("⚠️ Parquet格式需要安装pyarrow: pip install pyarrow")
    
    # Feather (需要pyarrow)
    try:
        tick_df.to_feather(f"{sample_dir}/sample_tick.feather")
        kline_df.to_feather(f"{sample_dir}/sample_kline.feather")
        formats_created.append("Feather")
    except ImportError:
        print("⚠️ Feather格式需要安装pyarrow: pip install pyarrow")
    
    print(f"✅ 示例数据已保存到: {sample_dir}/")
    print(f"📋 已创建格式: {', '.join(formats_created)}")
    print(f"   - sample_tick.* (TICK数据)")
    print(f"   - sample_kline.* (K线数据)")
    
    return sample_dir


# ==================== 主程序 ====================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("数据导入DB工具")
    print("="*60)
    print(f"\n支持的文件格式:")
    for ext, desc in SUPPORTED_FORMATS.items():
        print(f"  {ext:10} - {desc}")
    
    # 选择操作
    print("""
请选择操作:
  1. 导入TICK数据（单个文件）
  2. 导入K线数据（单个文件）
  3. 批量导入TICK数据（文件夹）
  4. 批量导入K线数据（文件夹）
  5. 创建示例数据（各种格式）
  6. 查看数据库中的所有表
  7. 查询表的示例数据
  0. 退出
""")
    
    choice = input("请输入选项 (0-7): ").strip()
    
    if choice == '1':
        file_path = input("请输入TICK数据文件路径: ").strip()
        symbol = input("请输入品种代码 (如 rb888): ").strip()
        replace = input("是否替换已有数据? (y/n): ").strip().lower() == 'y'
        import_tick_data(file_path, symbol, replace)
    
    elif choice == '2':
        file_path = input("请输入K线数据文件路径: ").strip()
        symbol = input("请输入品种代码 (如 rb888): ").strip()
        period = input("请输入K线周期 (1m/5m/15m/30m/1h/4h/D/W/M) [默认1m]: ").strip() or '1m'
        adjust = input("请输入复权类型 (hfq/raw) [默认hfq]: ").strip() or 'hfq'
        replace = input("是否替换已有数据? (y/n): ").strip().lower() == 'y'
        import_kline_data(file_path, symbol, period, adjust, replace)
    
    elif choice == '3':
        folder_path = input("请输入TICK数据文件夹路径: ").strip()
        replace = input("是否替换已有数据? (y/n): ").strip().lower() == 'y'
        batch_import(folder_path, 'tick', replace=replace)
    
    elif choice == '4':
        folder_path = input("请输入K线数据文件夹路径: ").strip()
        period = input("请输入K线周期 (1m/5m/15m/30m/1h/4h/D/W/M) [默认1m]: ").strip() or '1m'
        adjust = input("请输入复权类型 (hfq/raw) [默认hfq]: ").strip() or 'hfq'
        replace = input("是否替换已有数据? (y/n): ").strip().lower() == 'y'
        batch_import(folder_path, 'kline', period, adjust, replace)
    
    elif choice == '5':
        sample_dir = create_sample_data()
        print(f"\n💡 你可以尝试导入这些示例文件来测试各种格式")
    
    elif choice == '6':
        list_db_tables()
    
    elif choice == '7':
        list_db_tables()
        table_name = input("\n请输入要查询的表名: ").strip()
        if table_name:
            query_table_sample(table_name)
    
    elif choice == '0':
        print("👋 再见!")
    
    else:
        print("❌ 无效选项")
    
    print("\n" + "="*60)
    print("操作完成")
    print("="*60)
