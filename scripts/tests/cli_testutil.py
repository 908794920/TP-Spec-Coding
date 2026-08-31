from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from cli import main as climain


@lru_cache(maxsize=1)
def _cached_parser():
    """复用测试进程内的 argparse 树，避免每次 in-process CLI 调用重复注册全部命令。"""
    return climain.build_parser()


def invoke_main(argv: Sequence[str], *, refresh_card: bool = False) -> int:
    """以测试专用快速路径执行 CLI，同时保留 ``main`` 的真实调度和异常语义。

    正式 Card 自动刷新由专门的 Card 测试覆盖；其他 Runtime/Autonomy 测试默认不为
    presentation-only 副作用重复构建 snapshot。需要验证该副作用时显式传
    ``refresh_card=True``。
    """
    parser = _cached_parser()
    original_build_parser = climain.build_parser
    original_refresh = climain.card_trigger.refresh_after_success
    climain.build_parser = lambda: parser
    if not refresh_card:
        climain.card_trigger.refresh_after_success = lambda args: None
    try:
        return climain.main(list(argv))
    finally:
        climain.build_parser = original_build_parser
        climain.card_trigger.refresh_after_success = original_refresh
