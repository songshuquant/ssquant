"""
SSQuant - 期货量化交易框架
通过 Git 仓库安装: pip install git+https://github.com/songshuquant/ssquant.git
"""
from setuptools import setup, find_packages
from pathlib import Path

readme_file = Path(__file__).parent / "README.md"
if readme_file.exists():
    with open(readme_file, "r", encoding="utf-8") as f:
        long_description = f.read()
else:
    long_description = "SSQuant - 专业的期货量化交易框架"

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
    version='0.4.6',
    author='SSQuant Team',
    author_email='339093103@qq.com',
    description='专业的期货CTP量化交易框架',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/songshuquant/ssquant',

    packages=find_packages(),
    include_package_data=True,

    package_data={
        'ssquant.ctp': [
            'py*/*.pyd',
            'py*/*.dll',
            'py*/*.so',
            'py*/*.py',
            'py*/*.lib',
            '*.h',
            '*.dtd',
            '*.xml',
        ],
        'ssquant.assets': ['*.png', '*.jpg', '*.jpeg'],
    },

    install_requires=install_requires,
    python_requires='>=3.9,<3.15',

    extras_require={
        'ml': [
            'scikit-learn>=0.24.0',
            'joblib>=1.0.0',
            'statsmodels>=0.12.0',
        ],
    },

    project_urls={
        'Homepage': 'https://github.com/songshuquant/ssquant',
        'Repository': 'https://github.com/songshuquant/ssquant',
        'Gitee': 'https://gitee.com/ssquant/ssquant',
    },

    license='MIT',
    zip_safe=False,
)
