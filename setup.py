"""
SSQuant - 期货量化交易框架
标准PyPI打包配置
"""
from setuptools import setup, find_packages
from pathlib import Path

# 读取README
readme_file = Path(__file__).parent / "README.md"
if readme_file.exists():
    with open(readme_file, "r", encoding="utf-8") as f:
        long_description = f.read()
else:
    long_description = "SSQuant - 专业的期货量化交易框架"

# 读取requirements
requirements_file = Path(__file__).parent / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file, "r", encoding="utf-8") as f:
        install_requires = [line.strip() for line in f if line.strip() and not line.startswith('#')]
else:
    install_requires = [
        'pandas>=1.3.0',
        'numpy>=1.20.0',
        'requests>=2.25.0',
    ]

setup(
    name='ssquant',
    version='0.3.2',
    author='SSQuant Team',
    author_email='339093103@qq.com',
    description='专业的期货CTP量化交易框架',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/songshuquant/ssquant-ai',
    
    # 包配置
    packages=find_packages(),
    include_package_data=True,
    
    # 包数据 - 包含CTP二进制文件和资源文件
    package_data={
        'ssquant.ctp': [
            'py*/*.pyd',
            'py*/*.dll',
            'py*/*.py',
            'py*/*.lib',
            '*.h',
            '*.dtd',
            '*.xml',
        ],
        'ssquant.assets': ['*.png', '*.jpg', '*.jpeg'],
    },
    
    # 依赖项
    install_requires=install_requires,
    
    # Python版本要求
    python_requires='>=3.9,<3.15',
    
    # 可选依赖
    extras_require={
        'ml': [
            'scikit-learn>=0.24.0',
            'joblib>=1.0.0',
            'statsmodels>=0.12.0',
        ],
        'dev': [
            'pytest>=6.0.0',
            'black>=21.0',
            'flake8>=3.9.0',
        ],
    },
    
    # 分类
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Financial and Insurance Industry',
        'Intended Audience :: Developers',
        'Topic :: Office/Business :: Financial :: Investment',
        'License :: Other/Proprietary License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Operating System :: Microsoft :: Windows',
    ],
    
    # 关键词
    keywords='futures trading quantitative CTP backtest algorithmic-trading',
    
    # 项目链接
    project_urls={
        'Documentation': 'https://github.com/songshuquant/ssquant-ai#readme',
        'Source': 'https://github.com/songshuquant/ssquant-ai',
        'Bug Reports': 'https://github.com/songshuquant/ssquant-ai/issues',
    },
    
    # 许可证
    license='Proprietary - Non-Commercial Use Only',
    
    # Zip安全
    zip_safe=False,
)

