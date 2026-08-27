"""回测成交记录的仓位解析与展示工具。"""

from typing import Any, Dict, Iterable, List, Optional


def _as_int(value: Any) -> Optional[int]:
    """把可用的数值转换为整数；无效值返回 ``None``。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return int(number)


def infer_position_after(current_position: int, action: str, volume: Any) -> int:
    """根据一笔旧成交记录推导成交后净仓位。

    正数表示多仓，负数表示空仓，零表示空仓。该函数用于兼容没有
    ``position_after`` 快照的旧交易记录；新记录优先使用成交时保存的快照。
    """
    position = int(current_position)
    trade_volume = _as_int(volume)
    if trade_volume is None or trade_volume <= 0:
        return position

    normalized_action = str(action or '').strip()
    if normalized_action in ('开多', '买多'):
        return position + trade_volume
    if normalized_action in ('平多', '卖多'):
        return position - min(trade_volume, max(0, position))
    if normalized_action in ('开空', '卖空'):
        return position - trade_volume
    if normalized_action in ('平空', '买空'):
        return position + min(trade_volume, max(0, -position))
    if normalized_action == '平多开空':
        return -trade_volume
    if normalized_action == '平空开多':
        return trade_volume
    return position


def resolve_trade_positions(trades: Iterable[Dict[str, Any]]) -> List[int]:
    """按成交顺序返回每笔交易的成交后净仓位。

    新版记录中的 ``position_after`` 是权威值。缺少该字段的旧记录会从零仓位
    开始逐笔回放，保证历史结果仍能生成带仓位标记的报告。
    """
    positions: List[int] = []
    current_position = 0
    for trade in trades:
        recorded_position = _as_int(trade.get('position_after'))
        if recorded_position is None:
            current_position = infer_position_after(
                current_position,
                trade.get('action', ''),
                trade.get('volume', 0),
            )
        else:
            current_position = recorded_position
        positions.append(current_position)
    return positions


def format_position(position: Any, compact: bool = False) -> str:
    """格式化净仓位为图表标签或悬浮提示文本。"""
    value = _as_int(position)
    if value is None:
        return ''
    if value > 0:
        return f"多{value}" if compact else f"多{value}手"
    if value < 0:
        return f"空{abs(value)}" if compact else f"空{abs(value)}手"
    return '空仓'
