"""
CTP动态加载器 - 自动匹配当前Python版本

根据当前Python版本自动加载对应的CTP二进制文件
支持 Python 3.9, 3.10, 3.11, 3.12, 3.13, 3.14
"""
import sys
import os
import platform
from pathlib import Path

# 全局变量
CTP_AVAILABLE = False
thostmduserapi = None
thosttraderapi = None
_load_error = None


def get_python_version_tag():
    """获取Python版本标签 (例如: py39, py310, py311)"""
    major = sys.version_info.major
    minor = sys.version_info.minor
    return f"py{major}{minor}"


def get_ctp_directory():
    """
    获取当前Python版本对应的CTP目录
    
    Returns:
        Path: CTP文件目录路径
        
    Raises:
        RuntimeError: 如果系统不支持或找不到对应版本的CTP文件
    """
    # 检查操作系统
    if platform.system() != 'Windows':
        raise RuntimeError(
            "CTP仅支持Windows系统\n"
            "如需在Linux/Mac上运行，请使用纯回测模式"
        )
    
    # 检查架构
    if platform.architecture()[0] != '64bit':
        raise RuntimeError(
            "CTP仅支持64位Python\n"
            f"当前架构: {platform.architecture()[0]}"
        )
    
    # 当前文件所在目录
    current_dir = Path(__file__).parent
    
    # 获取Python版本标签
    py_version = get_python_version_tag()
    ctp_dir = current_dir / py_version
    
    # 检查是否有对应版本的CTP文件
    if not ctp_dir.exists():
        # 列出可用的版本
        available_versions = []
        for item in current_dir.iterdir():
            if item.is_dir() and item.name.startswith('py'):
                available_versions.append(item.name)
        
        error_msg = (
            f"找不到 Python {sys.version_info.major}.{sys.version_info.minor} 对应的CTP文件\n"
            f"查找路径: {ctp_dir}\n\n"
        )
        
        if available_versions:
            error_msg += f"可用的Python版本: {', '.join(sorted(available_versions))}\n"
            error_msg += "\n解决方案:\n"
            error_msg += "  1. 使用支持的Python版本重新安装\n"
            error_msg += f"  2. 访问 https://github.com/songshuquant/ssquant-ai 获取完整版本\n"
        else:
            error_msg += "没有找到任何CTP文件\n"
            error_msg += "请访问 https://github.com/songshuquant/ssquant-ai 下载完整安装包\n"
        
        raise RuntimeError(error_msg)
    
    return ctp_dir


def load_ctp_modules():
    """
    加载CTP模块
    
    Returns:
        tuple: (thostmduserapi, thosttraderapi) 模块对象
        
    Raises:
        ImportError: 如果无法加载CTP模块
    """
    try:
        # 获取CTP目录
        ctp_dir = get_ctp_directory()
        
        # 添加到系统路径（插入到最前面，确保优先加载）
        ctp_dir_str = str(ctp_dir)
        if ctp_dir_str not in sys.path:
            sys.path.insert(0, ctp_dir_str)
        
        # Windows下Python 3.8+需要显式添加DLL目录
        if platform.system() == 'Windows' and hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(ctp_dir_str)
            except Exception:
                # 如果添加失败（例如路径无效），尝试修改环境变量作为后备方案
                os.environ['PATH'] = ctp_dir_str + os.pathsep + os.environ['PATH']
        else:
            # 旧版本Python或非Windows系统
            os.environ['PATH'] = ctp_dir_str + os.pathsep + os.environ['PATH']
        
        # 导入CTP模块（动态加载，静态分析器无法识别）
        import thostmduserapi as md_api  # type: ignore
        import thosttraderapi as td_api  # type: ignore
        
        return md_api, td_api
        
    except Exception as e:
        raise ImportError(f"无法加载CTP模块: {e}")


def get_ctp_info():
    """
    获取CTP加载信息
    
    Returns:
        dict: CTP信息字典
    """
    info = {
        'available': CTP_AVAILABLE,
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}",
        'platform': platform.system(),
        'architecture': platform.architecture()[0],
    }
    
    if CTP_AVAILABLE:
        try:
            ctp_dir = get_ctp_directory()
            info['ctp_path'] = str(ctp_dir)
            info['version_tag'] = get_python_version_tag()
        except:
            pass
    else:
        info['error'] = str(_load_error)
    
    return info


def print_ctp_status():
    """打印CTP状态信息"""
    info = get_ctp_info()
    
    print("\n" + "="*70)
    print("CTP模块状态")
    print("="*70)
    print(f"Python版本: {info['python_version']}")
    print(f"操作系统: {info['platform']}")
    print(f"架构: {info['architecture']}")
    print(f"状态: {'可用' if info['available'] else '不可用'}")
    
    if info['available']:
        print(f"CTP路径: {info.get('ctp_path', 'N/A')}")
        print(f"版本标签: {info.get('version_tag', 'N/A')}")
    else:
        print(f"\n错误信息:\n{info.get('error', 'Unknown')}")
    
    print("="*70 + "\n")


# 自动加载CTP模块
try:
    thostmduserapi, thosttraderapi = load_ctp_modules()
    CTP_AVAILABLE = True
except Exception as e:
    _load_error = e
    CTP_AVAILABLE = False


# 导出接口
__all__ = [
    'CTP_AVAILABLE',
    'thostmduserapi',
    'thosttraderapi',
    'get_ctp_info',
    'print_ctp_status',
]


# 测试代码
if __name__ == "__main__":
    print_ctp_status()
    
    if CTP_AVAILABLE:
        print("测试导入成功！")
        print(f"行情API: {thostmduserapi}")
        print(f"交易API: {thosttraderapi}")
    else:
        print("\n提示: CTP模块不可用")
        print("回测功能仍然可以正常使用")

