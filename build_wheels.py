#!/usr/bin/env python
"""
SSQuant Wheel 构建脚本

为每个 Python 版本构建独立的 wheel 包，用户安装时只会下载对应版本的 CTP 文件。

使用方法:
    1. 构建所有版本:
       python build_wheels.py
    
    2. 构建特定版本:
       python build_wheels.py --versions 39 310 311
    
    3. 仅构建源码分发包:
       python build_wheels.py --sdist-only

注意事项:
    - 需要安装对应版本的 Python 才能构建该版本的 wheel
    - Windows 上使用 py 启动器 (py -3.9, py -3.10 等)
    - 构建完成后，wheel 文件在 dist/ 目录下
    - 上传到 PyPI: twine upload dist/*
"""
import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

# 支持的 Python 版本
SUPPORTED_VERSIONS = ['39', '310', '311', '312', '313', '314']

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
CTP_DIR = PROJECT_ROOT / 'ssquant' / 'ctp'
DIST_DIR = PROJECT_ROOT / 'dist'
BUILD_DIR = PROJECT_ROOT / 'build'


def get_python_executable(version: str) -> str:
    """
    获取指定版本的 Python 可执行文件路径
    
    Args:
        version: 版本号，如 '39', '310', '311'
    
    Returns:
        Python 可执行文件路径或命令
    """
    # 转换版本格式: '39' -> '3.9', '310' -> '3.10'
    if len(version) == 2:
        major, minor = version[0], version[1]
    else:
        major, minor = version[0], version[1:]
    version_dot = f"{major}.{minor}"
    
    # Windows 上使用 py 启动器
    if sys.platform == 'win32':
        return f'py -{version_dot}'
    else:
        # Linux/Mac 尝试多种路径
        candidates = [
            f'python{version_dot}',
            f'/usr/bin/python{version_dot}',
            f'/usr/local/bin/python{version_dot}',
        ]
        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
        return f'python{version_dot}'


def check_python_available(version: str) -> bool:
    """检查指定版本的 Python 是否可用"""
    python_exe = get_python_executable(version)
    try:
        result = subprocess.run(
            f'{python_exe} --version',
            shell=True,
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def backup_other_versions(keep_version: str) -> dict:
    """
    备份其他版本的 CTP 目录
    
    Args:
        keep_version: 要保留的版本号
    
    Returns:
        备份信息字典 {版本号: 备份路径}
    """
    backup_info = {}
    
    for version in SUPPORTED_VERSIONS:
        if version != keep_version:
            src_dir = CTP_DIR / f'py{version}'
            if src_dir.exists():
                backup_dir = CTP_DIR / f'_backup_py{version}'
                print(f"  备份 py{version} -> _backup_py{version}")
                shutil.move(str(src_dir), str(backup_dir))
                backup_info[version] = backup_dir
    
    return backup_info


def restore_backups(backup_info: dict):
    """恢复备份的目录"""
    for version, backup_dir in backup_info.items():
        src_dir = CTP_DIR / f'py{version}'
        if backup_dir.exists():
            print(f"  恢复 _backup_py{version} -> py{version}")
            shutil.move(str(backup_dir), str(src_dir))


def clean_build_dirs():
    """清理构建目录"""
    for dir_name in ['build', 'ssquant.egg-info']:
        dir_path = PROJECT_ROOT / dir_name
        if dir_path.exists():
            shutil.rmtree(dir_path)


def build_wheel_for_version(version: str) -> bool:
    """
    为指定 Python 版本构建 wheel
    
    Args:
        version: Python 版本号，如 '39', '310'
    
    Returns:
        是否构建成功
    """
    # 转换版本格式显示
    if len(version) == 2:
        version_display = f"3.{version[1]}"
    else:
        version_display = f"3.{version[1:]}"
    
    print(f"\n{'='*60}")
    print(f"构建 Python {version_display} wheel")
    print(f"{'='*60}")
    
    # 检查 CTP 目录是否存在
    ctp_version_dir = CTP_DIR / f'py{version}'
    if not ctp_version_dir.exists():
        print(f"  ⚠ 跳过: py{version} 目录不存在")
        return False
    
    # 检查 Python 是否可用
    if not check_python_available(version):
        print(f"  ⚠ 跳过: Python {version_display} 不可用")
        return False
    
    python_exe = get_python_executable(version)
    print(f"  使用: {python_exe}")
    
    # 备份其他版本
    print("  备份其他版本...")
    backup_info = backup_other_versions(version)
    
    try:
        # 清理之前的构建
        clean_build_dirs()
        
        # 构建 wheel
        print("  构建 wheel...")
        cmd = f'{python_exe} -m pip wheel --no-deps --wheel-dir "{DIST_DIR}" .'
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"  ✗ 构建失败:")
            print(result.stderr)
            return False
        
        print(f"  ✓ 构建成功")
        return True
        
    finally:
        # 恢复备份
        print("  恢复备份...")
        restore_backups(backup_info)
        clean_build_dirs()


def build_sdist():
    """构建源码分发包"""
    print(f"\n{'='*60}")
    print("构建源码分发包 (sdist)")
    print(f"{'='*60}")
    
    clean_build_dirs()
    
    cmd = f'{sys.executable} -m build --sdist --outdir "{DIST_DIR}"'
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"  ✗ 构建失败:")
        print(result.stderr)
        return False
    
    print(f"  ✓ 构建成功")
    clean_build_dirs()
    return True


def main():
    parser = argparse.ArgumentParser(
        description='为每个 Python 版本构建独立的 wheel 包'
    )
    parser.add_argument(
        '--versions', '-v',
        nargs='+',
        choices=SUPPORTED_VERSIONS,
        default=SUPPORTED_VERSIONS,
        help=f'要构建的 Python 版本 (默认: {" ".join(SUPPORTED_VERSIONS)})'
    )
    parser.add_argument(
        '--sdist-only',
        action='store_true',
        help='仅构建源码分发包'
    )
    parser.add_argument(
        '--no-sdist',
        action='store_true',
        help='不构建源码分发包'
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='清理 dist 目录后再构建'
    )
    
    args = parser.parse_args()
    
    # 清理 dist 目录
    if args.clean and DIST_DIR.exists():
        print("清理 dist 目录...")
        shutil.rmtree(DIST_DIR)
    
    # 创建 dist 目录
    DIST_DIR.mkdir(exist_ok=True)
    
    if args.sdist_only:
        # 仅构建 sdist
        build_sdist()
    else:
        # 构建 wheels
        success_count = 0
        fail_count = 0
        
        for version in args.versions:
            if build_wheel_for_version(version):
                success_count += 1
            else:
                fail_count += 1
        
        # 构建 sdist (作为后备)
        if not args.no_sdist:
            build_sdist()
        
        # 输出汇总
        print(f"\n{'='*60}")
        print("构建完成汇总")
        print(f"{'='*60}")
        print(f"  成功: {success_count} 个版本")
        print(f"  失败/跳过: {fail_count} 个版本")
        print(f"  输出目录: {DIST_DIR}")
        print()
        
        # 列出生成的文件
        print("生成的文件:")
        for f in sorted(DIST_DIR.iterdir()):
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name} ({size_mb:.1f} MB)")
    
    print(f"\n下一步: 使用 'twine upload dist/*' 上传到 PyPI")


if __name__ == '__main__':
    main()

