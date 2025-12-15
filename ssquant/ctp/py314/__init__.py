# CTP Python API - Python 314
__version__ = '1.0.0'

try:
    from . import _thostmduserapi
    from . import _thosttraderapi
    from . import thostmduserapi
    from . import thosttraderapi
except ImportError as e:
    print(f"Warning: {e}")
