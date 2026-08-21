# -*- coding: utf-8 -*-
"""V5.2.5 基座阻塞错误语义（A-06）。

业务角色遇到本模块定义的错误码时不得继续业务工作：不得修改数据库、
不得修改基座、不得删除事件、不得绕过检查；只能停止任务并交给基座修复方。

AI-A 在 commit preflight / reconcile 中抛出并输出这些语义；
manifest/validator 侧的错误码由 AI-C 的 C-06 门禁复用同一常量接入。

设计依据：V5.2.5 AI-A 任务书 §九（BASELINE_BLOCKED）与 A-06。
"""
from __future__ import annotations

# 标准错误码（stderr 首行机器可读前缀，格式：BASELINE_BLOCKED: <CODE>: <detail>）
BASELINE_BLOCKED = "BASELINE_BLOCKED"
BASELINE_MANIFEST_MISMATCH = "BASELINE_MANIFEST_MISMATCH"
BASELINE_VALIDATOR_BROKEN = "BASELINE_VALIDATOR_BROKEN"
BASELINE_ROOT_UNRESOLVED = "BASELINE_ROOT_UNRESOLVED"
PROJECTION_RECONCILIATION_REQUIRED = "PROJECTION_RECONCILIATION_REQUIRED"
ENCODING_VALIDATION_FAILED = "ENCODING_VALIDATION_FAILED"
PROJECTION_COMMIT_FAILED = "PROJECTION_COMMIT_FAILED"


class BaselineBlockedError(Exception):
    """基座阻塞错误基类：业务角色必须停止业务任务。"""

    code = BASELINE_BLOCKED

    def __init__(self, detail: str = "", code: str = ""):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code

    def __str__(self) -> str:
        if self.detail:
            return f"{self.code}: {self.detail}"
        return self.code


class ManifestMismatchError(BaselineBlockedError):
    """manifest 与工作区不一致（由 AI-C 门禁复用）。"""

    code = BASELINE_MANIFEST_MISMATCH


class ValidatorBrokenError(BaselineBlockedError):
    """校验器不可用或解析失败（由 AI-C 门禁复用）。"""

    code = BASELINE_VALIDATOR_BROKEN


class RootUnresolvedError(BaselineBlockedError):
    """TP-Spec-Coding 根目录无法可靠解析。"""

    code = BASELINE_ROOT_UNRESOLVED


class ReconciliationRequiredError(BaselineBlockedError):
    """投影存在漂移，必须先执行 tp-spec reconcile。"""

    code = PROJECTION_RECONCILIATION_REQUIRED


class ProjectionCommitFailedError(BaselineBlockedError):
    """commit 原子替换失败（DB 已回滚、文件已恢复）。"""

    code = PROJECTION_COMMIT_FAILED
