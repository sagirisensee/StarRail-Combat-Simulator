"""星穹铁道战技点（Skill Points / SP）资源池管理模块。

核心规则：
1. 默认上限为 5 点，特定角色天赋（如花火《叙述的诡计》）可提高上限（如提升至 7 点）；
2. 战斗开局通常默认有 3 点基础 SP；
3. 普攻通常恢复 1 点 SP（不可超过上限，超出计入溢出统计）；
4. 战技通常消耗 1 点 SP（若点数不足则无法施放，需降级为普攻）；
5. 部分大招/天赋可批量回复战技点（如花火大招回复 4 点 SP）；
6. 自动记录战技点的产出、消耗、溢出浪费及流水日志。
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class SPRecord:
    av: float
    actor: str
    change: int
    action: str
    current: int
    max_sp: int


class SkillPointManager:
    def __init__(self, initial_sp: int = 3, max_sp: int = 5):
        self.max_sp: int = max_sp
        self.current_sp: int = min(initial_sp, max_sp)
        self.total_generated: int = 0
        self.total_consumed: int = 0
        self.total_wasted: int = 0
        self.history: List[SPRecord] = []

    def set_max_sp(self, new_max: int):
        """提升/改变战技点上限（如花火天赋）。"""
        self.max_sp = new_max
        if self.current_sp > self.max_sp:
            self.current_sp = self.max_sp

    def can_consume(self, cost: int = 1) -> bool:
        """检查是否有足够的战技点。"""
        return self.current_sp >= cost

    def consume(self, cost: int, actor_name: str, action_desc: str = "施放战技", current_av: float = 0.0) -> bool:
        """尝试消耗战技点。若点数充足扣除并返回 True，否则返回 False。"""
        if not self.can_consume(cost):
            return False

        self.current_sp -= cost
        self.total_consumed += cost
        self.history.append(SPRecord(
            av=round(current_av, 2),
            actor=actor_name,
            change=-cost,
            action=action_desc,
            current=self.current_sp,
            max_sp=self.max_sp
        ))
        return True

    def generate(self, amount: int, actor_name: str, action_desc: str = "施放普攻", current_av: float = 0.0) -> int:
        """恢复战技点。若超出上限则记为溢出。返回实际恢复点数。"""
        actual_gain = min(amount, self.max_sp - self.current_sp)
        wasted = amount - actual_gain

        self.current_sp += actual_gain
        self.total_generated += amount
        self.total_wasted += wasted

        desc = action_desc
        if wasted > 0:
            desc += f" (溢出浪费 {wasted} 点!)"

        self.history.append(SPRecord(
            av=round(current_av, 2),
            actor=actor_name,
            change=actual_gain,
            action=desc,
            current=self.current_sp,
            max_sp=self.max_sp
        ))
        return actual_gain

    def get_summary(self) -> Dict[str, Any]:
        """获取整场战斗的战技点收支统计。"""
        return {
            "current": self.current_sp,
            "max": self.max_sp,
            "total_generated": self.total_generated,
            "total_consumed": self.total_consumed,
            "total_wasted": self.total_wasted,
            "net_balance": self.total_generated - self.total_consumed
        }
