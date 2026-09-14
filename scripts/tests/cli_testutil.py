from __future__ import annotations
from functools import lru_cache
from typing import Sequence
from cli import main as climain

@lru_cache(maxsize=1)
def _cached_parser():
    return climain.build_parser()

def invoke_main(argv: Sequence[str]) -> int:
    """Reuse parser construction only; all command side effects remain real.

    Dedicated production-entry tests call main directly without this helper.
    """
    parser = _cached_parser()
    original = climain.build_parser
    climain.build_parser = lambda: parser
    try:
        return climain.main(list(argv))
    finally:
        climain.build_parser = original
