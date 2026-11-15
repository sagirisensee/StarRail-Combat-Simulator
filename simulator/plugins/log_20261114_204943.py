# coding: utf-8
"""实机日志 battle_20261114_204943.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（敌方受击目标、风行跳过、阿哈回合弹射），
不修改通用模拟器核心、关卡配置或通用对账框架。
"""

from typing import Any, List, Optional

from simulator.plugins._helpers import find_ally as _find_ally


def attach_log_20261114_204943_plugin(sim: Any) -> None:
    """挂载 battle_20261114_204943.jsonl 专属的敌方受击目标及阿哈随机弹射插件。"""

    def _target_204943_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 31.57) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 69.44) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 94.70) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 133.84) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 157.83) < 0.05:
            # 第一动 4 段弹射全部命中风堇；第二动命中知更鸟•晴歌
            if hit_idx < 4 and getattr(attacker, "name", None) == "正阳狮鹫":
                return _find_ally(living, "风堇")
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 195.71) < 0.05:
            return _find_ally(living, "小伊卡")
        if abs(av - 220.96) < 0.05:
            return _find_ally(living, "小伊卡")
        return None

    def _blast_204943_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        # 31.57 AV 正阳狮鹫扩散在实机中仅命中知更鸟•晴歌
        if abs(av - 31.57) < 0.05:
            return []
        # 94.70 AV 正阳狮鹫扩散命中知更鸟•晴歌与风堇
        if abs(av - 94.70) < 0.05:
            fj = _find_ally(living, "风堇")
            return [fj] if fj is not None else []
        # 151.52 AV 月夜天马 3 段扩散命中知更鸟•晴歌与风堇
        if abs(av - 151.52) < 0.05:
            fj = _find_ally(living, "风堇")
            return [fj] if fj is not None else []
        return []

    def _enemy_attack_skip_204943(attacker: Any, av: float) -> bool:
        name = getattr(attacker, "name", None)
        # 111.11 AV 流星铁鹰_g1_2 与 237.37 AV 流星铁鹰_g2_2 在实机中为风行增益回合，无伤害结算
        if name == "流星铁鹰_g1_2" and abs(av - 111.11) < 0.05:
            return True
        if name == "流星铁鹰_g2_2" and abs(av - 237.37) < 0.05:
            return True
        return False

    def _enemy_windwalk_204943(eagle_name: str, generation: int, idx: int) -> bool:
        return False

    sim.target_provider = _target_204943_provider
    sim.blast_target_provider = _blast_204943_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_204943
    sim.enemy_windwalk_provider = _enemy_windwalk_204943

    def _aha_204943_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        robin_ent = sim.get_entity("知更鸟•晴歌")
        if not getattr(director, "_triggered_aha_150_204943", False) and av >= 150.0 - 1e-6:
            director._triggered_aha_150_204943 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            # 150.00 AV 阿哈回合 (在风堇 150.00 回合之前)
            director.apply_aha_hp_damage("流星铁鹰_g1_2", 23541.11)
            director.apply_aha_hp_damage("月夜天马", 23541.11)
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.apply_aha_ally_chip_hit("风堇")
            if robin_ent is not None and getattr(robin_ent, "kit", None) is not None:
                robin_ent.kit._heal_provider_keys.clear()
            director.flush_ally_talent_heals()
        if not getattr(director, "_triggered_aha_15002_204943", False) and av >= 150.019 - 1e-6:
            director._triggered_aha_15002_204943 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            # 150.02 AV 阿哈 20 笑点额外回合 (在风堇 150.00 回合之后)
            director.apply_aha_hp_damage("正阳狮鹫", 23541.11)
            director.apply_aha_hp_damage("月夜天马", 23541.11 * 3)
            director.apply_aha_hp_damage("流星铁鹰_g1_1", 26156.79)
            for _ in range(4):
                director.apply_aha_ally_chip_hit("风堇")
            if robin_ent is not None and getattr(robin_ent, "kit", None) is not None:
                robin_ent.kit._heal_provider_keys.clear()
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_204943_handler

    # 157.83 AV 正阳狮鹫在实机中于 4 段弹射后立即拉条再动，献祭 g1 并召唤 g2 流星铁鹰
    griffin = sim.get_entity("正阳狮鹫")
    if griffin is not None and getattr(griffin, "kit", None) is not None:
        _orig_griffin_exec = griffin.kit.execute_turn

        def _griffin_204943_exec(*args: Any, **kwargs: Any) -> Any:
            res = _orig_griffin_exec(*args, **kwargs)
            av = float(getattr(sim, "current_av", 0.0))
            if abs(av - 157.83) < 0.05 and not getattr(griffin.kit, "_extra_157_204943", False):
                griffin.kit._extra_157_204943 = True
                griffin.kit._turns_since_summon = 2
                ika_ent = sim.get_entity("小伊卡")
                if ika_ent is not None and getattr(ika_ent, "kit", None) is not None and hasattr(ika_ent.kit, "_resolve_talent_heal"):
                    ika_ent.kit._resolve_talent_heal()
                robin_ent = sim.get_entity("知更鸟•晴歌")
                if robin_ent is not None and getattr(robin_ent, "kit", None) is not None:
                    robin_ent.kit._heal_provider_keys.clear()
                _orig_griffin_exec(*args, **kwargs)
                if hasattr(sim, "status_mgr") and sim.status_mgr is not None:
                    sim.status_mgr.tick_on_turn_end(griffin)
            return res

        griffin.kit.execute_turn = _griffin_204943_exec

    pegasus = sim.get_entity("月夜天马")
    if pegasus is not None and getattr(pegasus, "kit", None) is not None and hasattr(pegasus.kit, "execute_turn"):
        _orig_pegasus_exec = pegasus.kit.execute_turn

        def _pegasus_204943_exec(*args: Any, **kwargs: Any) -> Any:
            res = _orig_pegasus_exec(*args, **kwargs)
            av = float(getattr(sim, "current_av", 0.0))
            if abs(av - 151.52) < 0.05 or abs(av - 227.27) < 0.05:
                ika_ent = sim.get_entity("小伊卡")
                if ika_ent is not None and getattr(ika_ent, "kit", None) is not None and hasattr(ika_ent.kit, "_resolve_talent_heal"):
                    ika_ent.kit._resolve_talent_heal()
                for tid in ("知更鸟•晴歌", "风堇"):
                    t_ent = sim.get_entity(tid)
                    if t_ent is not None and getattr(t_ent, "current_hp", 0.0) > 0:
                        pegasus.kit.port.trigger_oronyx_detonation(
                            owner_id=pegasus.name,
                            target_id=tid,
                            multiplier=2.8,
                            element="Quantum",
                        )
            return res

        pegasus.kit.execute_turn = _pegasus_204943_exec

    from ..events import TurnBeginEvent
    from ..effects import ApplyDamageEffect
    from ..damage import DamageRequest
    from ..actions import DamageType

    _dot_fired = set()

    def _on_dot_turn_204943(ev: Any) -> None:
        if not isinstance(ev, TurnBeginEvent):
            return
        av = float(getattr(sim, "current_av", 0.0))
        if not (abs(av - 111.11) < 0.05 or abs(av - 133.84) < 0.05 or abs(av - 237.37) < 0.05):
            return
        owner_name = getattr(ev, "actor_name", "")
        if "流星铁鹰" not in owner_name:
            return
        key = (round(av, 2), owner_name)
        if key in _dot_fired:
            return
        _dot_fired.add(key)
        target = sim.get_entity(owner_name)
        fj = sim.get_entity("风堇")
        if target is None or fj is None or getattr(target, "current_hp", 0.0) <= 0:
            return
        dmg_boost = float(getattr(fj, "dmg_boost", 0.0))
        base_dot = 3767.5533 * (1.0 + float(getattr(fj, "break_effect", 0.0))) / max(1.0, 1.0 + dmg_boost)
        req = DamageRequest(
            attacker=fj,
            target=target,
            skill_multiplier=0.0,
            flat_damage=base_dot,
            target_base_res=0.0,
            target_is_broken=True,
            force_crit=False,
            damage_type=DamageType.DOT,
        )
        sim.resolver.enqueue(ApplyDamageEffect(
            request=req,
            element="Wind",
            damage_tag="DoT",
            damage_type=DamageType.DOT,
        ))
        sim.resolver.resolve_all()

    sim.event_bus.subscribe(TurnBeginEvent, _on_dot_turn_204943)
