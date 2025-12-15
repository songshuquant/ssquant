"""
调试工具模块

提供调试相关的工具函数
"""

from ..config.path_config import setup_python_path
import importlib
import sys
import os

# 确保使用正确的模块路径
setup_python_path()

def check_module_exists(module_name):
    """
    检查模块是否存在
    
    Args:
        module_name (str): 模块名称，如 'data.api_data_fetcher'
        
    Returns:
        bool: 是否存在
    """
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False

def get_module_path(module_name):
    """
    获取模块文件路径
    
    Args:
        module_name (str): 模块名称
        
    Returns:
        str: 模块文件路径，如果不存在则返回None
    """
    if check_module_exists(module_name):
        module = importlib.import_module(module_name)
        return module.__file__
    return None

def check_function_exists(module_name, function_name):
    """
    检查模块中是否存在指定函数
    
    Args:
        module_name (str): 模块名称
        function_name (str): 函数名称
        
    Returns:
        bool: 是否存在
    """
    try:
        module = importlib.import_module(module_name)
        return hasattr(module, function_name)
    except ImportError:
        return False

def check_data_modules():
    """
    检查数据相关模块的加载情况
    
    Returns:
        dict: 检查结果
    """
    results = {
        "modules": {},
        "functions": {},
        "paths": {}
    }
    
    # 检查模块是否存在
    modules_to_check = [
        "data.data_source",
        "data.api_data_fetcher",
        "data.multi_data_fetcher",
        "api.strategy_api"
    ]
    
    for module in modules_to_check:
        results["modules"][module] = check_module_exists(module)
        results["paths"][module] = get_module_path(module)
    
    # 检查关键函数是否存在
    function_checks = [
        ("data.api_data_fetcher", "get_futures_data"),
        ("data.multi_data_fetcher", "fetch_multiple_data"),
        ("api.strategy_api", "create_strategy_api")
    ]
    
    for module, function in function_checks:
        key = f"{module}.{function}"
        results["functions"][key] = check_function_exists(module, function)
    
    # 检查系统路径
    results["sys_path"] = sys.path
    
    return results

def print_debug_info():
    """
    打印调试信息
    """
    results = check_data_modules()
    
    print("\n========== 模块加载情况检查 ==========")
    
    print("\n模块存在性检查:")
    for module, exists in results["modules"].items():
        status = "[OK]" if exists else "[MISSING]"
        print(f"{module}: {status}")
    
    print("\n函数存在性检查:")
    for func_path, exists in results["functions"].items():
        status = "[OK]" if exists else "[MISSING]"
        print(f"{func_path}: {status}")
    
    print("\n模块文件路径:")
    for module, path in results["paths"].items():
        if path:
            print(f"{module}: {path}")
        else:
            print(f"{module}: 未找到")
    
    print("\nPython系统路径:")
    for i, path in enumerate(results["sys_path"]):
        print(f"{i}: {path}")
    
    print("\n========== 检查完成 ==========")

if __name__ == "__main__":
    print_debug_info() 