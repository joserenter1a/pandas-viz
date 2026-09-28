"""pandas-viz: visualize pandas pipelines step by step."""

from .tracer import Tracer, trace
from .worker import run_code

__all__ = ["Tracer", "trace", "run_code", "load_ipython_extension"]


def load_ipython_extension(ipython):
    """``%load_ext pandas_viz`` registers the ``%%pandasviz`` cell magic."""
    from .notebook import load_ipython_extension as load

    load(ipython)
