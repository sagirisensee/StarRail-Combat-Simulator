import pytest
from simulator.kits.enemies.base import EnemyActionContext
from simulator.kits.enemies.events import FriendlyHitResolved, EnemyActionCompleted
from simulator.kits.enemies.lighthouse import LighthouseBossKit


class FakeEnemyPort:
    def __init__(self):
        self.alive = {"「灯塔」"}
        self.regular_actions = []

    def is_alive(self, entity_id: str) -> bool:
        return entity_id in self.alive

    def summon_lighthouse_guards(
        self,
        *,
        owner_id: str,
        generation: int,
        count: int,
    ):
        ids = tuple(f"{owner_id}:guard:{generation}:{index}" for index in range(count))
        self.alive.update(ids)
        return ids

    def execute_lighthouse_regular_action(
        self,
        *,
        owner_id: str,
        action_id: str,
    ):
        self.regular_actions.append((owner_id, action_id))


def test_lighthouse_opening_and_regular_turn():
    port = FakeEnemyPort()
    kit = LighthouseBossKit("「灯塔」", port)

    opening = kit.on_battle_start()
    assert opening is not None
    assert opening.reset_distance == 20000.0
    assert kit.wish_stacks == 12
    assert len(kit.guard_ids) == 3
    assert kit.generation == 1

    # 重复开场不重召
    assert kit.on_battle_start() is None

    # 有戍卫时行动，走常规行动，距离 10000.0
    result = kit.execute_turn(EnemyActionContext("turn:1", "「灯塔」"))
    assert result.reset_distance == 10000.0
    assert port.regular_actions == [("「灯塔」", "turn:1")]


def test_lighthouse_resummon_when_all_guards_die():
    port = FakeEnemyPort()
    kit = LighthouseBossKit("「灯塔」", port)
    kit.on_battle_start()

    old_ids = kit.guard_ids
    port.alive.remove(old_ids[0])

    # 还有2只存活，不重召；常规攻击后移除所有众愿层数并退出除恶状态
    result = kit.execute_turn(EnemyActionContext("turn:1", "「灯塔」"))
    assert result.reset_distance == 10000.0
    assert kit.generation == 1
    assert kit.in_chue is False
    assert kit.wish_stacks == 0

    # 全部死亡
    port.alive.difference_update(old_ids)

    # 死亡本身未行动时不重召，灯塔行动时才重召
    assert kit.generation == 1
    result = kit.execute_turn(EnemyActionContext("turn:2", "「灯塔」"))
    assert result.reset_distance == 20000.0
    assert kit.generation == 2
    assert kit.wish_stacks == 12
    assert set(kit.guard_ids).isdisjoint(old_ids)


def test_lighthouse_wish_stacks_damage_interception():
    port = FakeEnemyPort()
    kit = LighthouseBossKit("「灯塔」", port)
    kit.on_battle_start()

    # 12 层免伤 60%，受到 1000 变为 400
    assert kit.intercept_incoming_damage("「灯塔」", 1000.0) == pytest.approx(400.0)

    # 我方命中一次，扣 1 层
    kit.on_event(
        FriendlyHitResolved(
            action_id="attack:1",
            hit_id="attack:1:hit:1",
            source_id="ally",
            target_id="「灯塔」",
        )
    )
    assert kit.wish_stacks == 11
    assert kit.intercept_incoming_damage("「灯塔」", 1000.0) == pytest.approx(450.0)

    # 戍卫行动一次，加 1 层 (上限12)
    kit.on_event(
        EnemyActionCompleted(
            action_id="guard_act:1",
            actor_id=kit.guard_ids[0],
        )
    )
    assert kit.wish_stacks == 12
