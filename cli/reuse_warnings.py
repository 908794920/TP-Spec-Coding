# -*- coding: utf-8 -*-
"""V5.2.0 B-13/B-15 复用与成本披露分级告警文案（W1-W5）。

设计依据：历史设计记录 B13-reuse-warning
证据锚点：评审表 Q4（L323）、9.4 第 2 行（L334）、9.4 第 5 行（L337）；
升级计划 §3.5（L180-189）、§3.3（L151）。

所有告警为纯披露性标注，不阻断 workflow、不改变风险等级、不改变授权语义。
"""

# --- 阈值常量（版本化可调，修改记录配置变更与样本依据） ---
# 初始阈值版本
_THRESHOLD_VERSION = "1.0.0"

# W1/W2：unknown ratio 分档阈值（Q4 裁决，30%/50%）
UNKNOWN_RATIO_WARN_THRESHOLD = 0.30   # >30% 触发 W1
UNKNOWN_RATIO_BLOCK_THRESHOLD = 0.50  # >50% 触发 W2

# W4：低复用率阈值（评审表 9.4 第 2 行 deepseek-v4-pro 建议，初始参考值）
REUSE_RATE_LOW_THRESHOLD = 0.20  # <20% 触发 W4

# --- W1：unknown ratio > 30% —— "仅供参考" ---
W1_CN = "[披露提示] 未知比例 >30%：本报表数据仅供参考，不作为关键决策依据。"
W1_EN = "[DISCLOSURE] unknown ratio > 30%: statistics are for reference only, not for key decision basis."


def w1_warnings(
    unknown_session_ratio: float | None,
    unknown_input_bytes_ratio: float | None,
) -> list[str]:
    """生成 W1 告警（仅披露不阻断）。

    触发条件：任一 unknown 指标 > 30% 且 ≤ 50%；双指标独立判定。
    与 W2 互斥（W2 触发时不再展示 W1）。
    """
    msgs: list[str] = []
    if unknown_session_ratio is not None and UNKNOWN_RATIO_WARN_THRESHOLD < unknown_session_ratio <= UNKNOWN_RATIO_BLOCK_THRESHOLD:
        msgs.append(f"{W1_CN} (session_ratio={unknown_session_ratio:.1%})")
    if unknown_input_bytes_ratio is not None and UNKNOWN_RATIO_WARN_THRESHOLD < unknown_input_bytes_ratio <= UNKNOWN_RATIO_BLOCK_THRESHOLD:
        msgs.append(f"{W1_CN} (bytes_ratio={unknown_input_bytes_ratio:.1%})")
    return msgs


# --- W2：unknown ratio > 50% —— "不可作为成本决策依据" ---
W2_CN = "[披露警示] 未知比例 >50%：当前数据质量不足以支持可靠决策，本报表不可作为成本决策依据。"
W2_EN = "[DISCLOSURE] unknown ratio > 50%: data quality insufficient for reliable decisions; not suitable for cost decision basis."


def w2_warnings(
    unknown_session_ratio: float | None,
    unknown_input_bytes_ratio: float | None,
) -> list[str]:
    """生成 W2 告警（仅披露不阻断）。

    触发条件：任一 unknown 指标 > 50%；与 W1 互斥。
    W2 触发时覆盖 W1（不展示 W1 文案）。
    """
    msgs: list[str] = []
    if unknown_session_ratio is not None and unknown_session_ratio > UNKNOWN_RATIO_BLOCK_THRESHOLD:
        msgs.append(f"{W2_CN} (session_ratio={unknown_session_ratio:.1%})")
    if unknown_input_bytes_ratio is not None and unknown_input_bytes_ratio > UNKNOWN_RATIO_BLOCK_THRESHOLD:
        msgs.append(f"{W2_CN} (bytes_ratio={unknown_input_bytes_ratio:.1%})")
    return msgs


# --- W3：net_loss 净亏独立提示 ---
W3_CN = "[净亏提示] 预检自身成本高于节省量（net_saving < 0）：本场景为净亏样本，仅供审计与调优，不计入收益结论。"
W3_EN = "[NET-LOSS] preflight self cost exceeds savings (net_saving < 0): net-loss sample, audit/tuning only, excluded from benefit conclusion."


def w3_warnings(net_saving: float | None) -> list[str]:
    """生成 W3 净亏告警。

    触发条件：net_saving < 0（net_saving = actual_or_comparable_saved - self_cost）。
    与 unknown 比例档位无关，可与 W1/W2/W4 同时出现。
    """
    if net_saving is not None and net_saving < 0:
        return [f"{W3_CN} (net_saving={net_saving})"]
    return []


# --- W4：低复用率提示 ---
W4_CN = "[复用率提示] 复用率低于 20%：预检净收益可能为负，建议核对失效原因与基线口径。"
W4_EN = "[REUSE] reuse_rate below 20%: net benefit may be negative; verify invalidation cause and baseline basis."


def w4_warnings(reuse_rate: float | None, has_reuse_history: bool = True) -> list[str]:
    """生成 W4 低复用率告警。

    触发条件：reuse_rate < 0.20 且仅在有复用历史的会话中触发。
    首次预检无复用率时不展示。
    """
    if not has_reuse_history:
        return []
    if reuse_rate is not None and reuse_rate < REUSE_RATE_LOW_THRESHOLD:
        return [f"{W4_CN} (reuse_rate={reuse_rate:.1%})"]
    return []


# --- W5：B-13 复用告警（复用审查包不替代 VERIFYING） ---
W5_CN = "[复用告警] 复用审查包不替代 VERIFYING 阶段；tp-verification-engineering 必须重新确认包有效并独立审查，不得仅引用旧结论。"
W5_EN = "[REUSE-WARNING] Reusing a review package does not replace VERIFYING; tp-verification-engineering must re-validate the package and independently review; must not cite old conclusions only."


def w5_warning() -> str:
    """生成 W5 复用告警。

    每次复用动作发生时展示，不因"已提示过"而省略。
    """
    return W5_CN


# --- 聚合：为 B-15 成本披露报表生成全部 W1-W4 告警 ---
WARNING_HEADER_CN = "=== 披露告警 ==="
WARNING_HEADER_EN = "=== Disclosure Warnings ==="


def generate_cost_disclosure_warnings(
    unknown_session_ratio: float | None = None,
    unknown_input_bytes_ratio: float | None = None,
    net_saving: float | None = None,
    reuse_rate: float | None = None,
    has_reuse_history: bool = True,
) -> list[str]:
    """为 B-15 成本披露报表生成 W1-W4 告警列表。

    W1 与 W2 互斥：W2 触发时不再展示 W1。
    多告警可叠加：同一报表同时命中多级触发条件时逐条展示，不合并、不吞并。
    """
    w1 = w1_warnings(unknown_session_ratio, unknown_input_bytes_ratio)
    w2 = w2_warnings(unknown_session_ratio, unknown_input_bytes_ratio)
    w3 = w3_warnings(net_saving)
    w4 = w4_warnings(reuse_rate, has_reuse_history)

    result: list[str] = []
    if w1 or w2 or w3 or w4:
        result.append(WARNING_HEADER_CN)
    # W1 与 W2 互斥：W2 触发时不再展示 W1
    if w2:
        result.extend(w2)
    elif w1:
        result.extend(w1)
    result.extend(w3)
    result.extend(w4)
    return result