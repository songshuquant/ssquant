import pandas as pd
from .api_data_fetcher import get_futures_data

def fetch_multiple_data(symbols_and_periods, configs):
    """
    获取多个品种和周期的期货数据
    
    Args:
        symbols_and_periods (list): 包含多个品种和周期配置的列表，每个元素是一个字典，包含symbol, kline_period, adjust_type
        configs (dict): 每个品种的配置字典，键为品种代码，值为该品种的配置参数
        
    Returns:
        dict: 包含多个数据集的字典，键名格式为"{symbol}_{kline_period}_{复权类型}"
    """
    # 创建数据存储字典
    data_dict = {}
    
    # 获取多个品种和周期的数据
    print("开始获取数据...")
    for item in symbols_and_periods:
        symbol = item["symbol"]
        kline_period = item["kline_period"]
        adjust_type = item["adjust_type"]
        
        # 获取该品种的配置
        if symbol not in configs:
            print(f"警告: 未找到品种 {symbol} 的配置，将使用默认配置")
            config = {
                'start_date': '2024-01-01',
                'end_date': '2024-12-31',
                'username': None,
                'password': None,
                'use_cache': True,
                'save_data': True,
                'cache_dir': 'data_cache'
            }
        else:
            config = configs[symbol]
        
        adjust_desc = "不复权" if adjust_type == "0" else "后复权"
        print(f"\n获取 {symbol} {kline_period} {adjust_desc} 数据")
        print(f"日期范围: {config['start_date']} 至 {config['end_date']}")
        
        try:
            # 使用get_futures_data获取数据
            data = get_futures_data(
                symbol=symbol,
                start_date=config['start_date'],
                end_date=config['end_date'],
                username=config['username'],
                password=config['password'],
                kline_period=kline_period,
                adjust_type=adjust_type,
                depth="no",
                use_cache=config.get('use_cache', True),
                cache_dir=config.get('cache_dir', 'data_cache'),
                save_data=config.get('save_data', True)
            )
            
            if data is not None:
                # 将数据存储到字典中
                key = f"{symbol}_{kline_period}_{'不复权' if adjust_type == '0' else '后复权'}"
                data_dict[key] = data
                print(f"成功获取数据: {len(data)} 条记录 ({data.index.min()} 到 {data.index.max()})")
            else:
                print(f"获取数据失败")
        except Exception as e:
            print(f"获取数据时出错：{e}")
    
    # 打印获取结果摘要
    if data_dict:
        print(f"\n数据获取完成，共 {len(data_dict)} 个数据集")
    else:
        print("\n未获取到任何数据")
    
    return data_dict

def get_data_summary(data_dict):
    """
    获取数据集的摘要信息
    
    Args:
        data_dict (dict): 包含多个数据集的字典
        
    Returns:
        pd.DataFrame: 包含数据集摘要信息的DataFrame
    """
    if not data_dict:
        return None
        
    summary_data = []
    for key, data in data_dict.items():
        parts = key.split('_')
        symbol = parts[0]
        kline_period = parts[1]
        adjust_type = '_'.join(parts[2:])  # 处理可能包含下划线的复权类型
        
        summary_data.append({
            '数据集': key,
            '品种': symbol,
            '周期': kline_period,
            '复权类型': adjust_type,
            '记录数': len(data),
            '开始日期': data.index.min(),
            '结束日期': data.index.max(),
            '最低价': data['low'].min(),
            '最高价': data['high'].max(),
            '平均成交量': data['volume'].mean()
        })
    
    return pd.DataFrame(summary_data)

def save_data_to_csv(data_dict, output_dir='data_export'):
    """
    将数据集保存为CSV文件
    
    Args:
        data_dict (dict): 包含多个数据集的字典
        output_dir (str): 输出目录
        
    Returns:
        list: 保存的文件路径列表
    """
    import os
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    saved_files = []
    for key, data in data_dict.items():
        # 生成文件名
        filename = os.path.join(output_dir, f"{key}.csv")
        
        # 保存数据
        data.to_csv(filename)
        saved_files.append(filename)
        print(f"数据已保存到 {filename}")
    
    return saved_files 