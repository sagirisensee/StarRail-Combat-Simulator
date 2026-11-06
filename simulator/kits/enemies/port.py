from typing import Protocol, Tuple


class EnemyCombatPort(Protocol):
    def is_alive(self, entity_id: str) -> bool:
        """实体是否存在且存活。"""
        ...

    def summon_lighthouse_guards(
        self,
        *,
        owner_id: str,
        generation: int,
        count: int,
    ) -> Tuple[str, ...]:
        """创建完整一组千星戍卫，返回唯一实体 ID。"""
        ...

    def execute_lighthouse_regular_action(
        self,
        *,
        owner_id: str,
        action_id: str,
    ) -> None:
        """执行灯塔常规行动效果。"""
        ...
