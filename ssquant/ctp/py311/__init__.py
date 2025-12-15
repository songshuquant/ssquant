# CTP Python API - Python 3.12
__version__ = '1.0.0'

try:
    from . import _thostmduserapi
    from . import _thosttraderapi
    from . import thostmduserapi
    from . import thosttraderapi
except ImportError as e:
    print(f"Warning: {e}")
