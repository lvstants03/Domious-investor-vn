import logging

logger = logging.getLogger("dominus-investor.mock.numba")
logger.info("Using mock numba module for Python 3.14+ compatibility.")

def njit(*args, **kwargs):
    """Mock decorator for njit (no JIT compiler needed)."""
    if len(args) == 1 and callable(args[0]):
        return args[0]
    def decorator(func):
        return func
    return decorator

def jit(*args, **kwargs):
    """Mock decorator for jit."""
    if len(args) == 1 and callable(args[0]):
        return args[0]
    def decorator(func):
        return func
    return decorator

def prange(*args):
    return range(*args)
