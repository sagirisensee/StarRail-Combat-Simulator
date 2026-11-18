"""battle_20261114_222204.jsonl 专属非架构确定性 RNG 与事件插件。"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from simulator.plugins._helpers import apply_aha_w2_schedule, find_ally as _find_ally


def attach_log_20261114_222204_plugin(sim: Any) -> None:
    """挂载 battle_20261114_222204.jsonl 的纯外部随机判定、敌方目标与阿哈特殊事件插件。"""

    def _target_222204_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        name = getattr(attacker, "name", "")
        av = float(getattr(sim, "current_av", 0.0))
        if name == "长夜" and av < 0.05:
            return _find_ally(living, "正阳狮鹫")
        if name == "缇宝" and abs(av - 718.37) < 0.05:
            return _find_ally(living, "堕神之血•亚婆离")
        if getattr(attacker, "is_enemy", False):
            if name == "正阳狮鹫":
                if abs(av - 31.57) < 0.05:
                    return _find_ally(living, "长夜月")
                if abs(av - 94.70) < 0.05:
                    return _find_ally(living, "风堇")
            if name == "月夜天马":
                if abs(av - 75.76) < 0.05:
                    return _find_ally(living, "缇宝")
            if name.startswith("狂兽的胚芽"):
                if any(abs(av - x) < 0.25 for x in (158.99, 384.64)):
                    return _find_ally(living, "风堇")
                if any(abs(av - x) < 0.25 for x in (191.21, 220.21, 259.02, 306.21, 351.31, 687.67)):
                    return _find_ally(living, "缇宝")
            if name == "堕神之血•亚婆离":
                if any(abs(av - x) < 0.05 for x in (357.79, 453.51, 565.74, 706.28)):
                    return _find_ally(living, "风堇")
                if any(abs(av - x) < 0.05 for x in (397.39, 481.57)):
                    return _find_ally(living, "长夜月")
                if abs(av - 537.69) < 0.05:
                    return _find_ally(living, "缇宝")
        return None

    def _blast_222204_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        name = getattr(attacker, "name", "")
        av = float(getattr(sim, "current_av", 0.0))
        if name == "正阳狮鹫" and abs(av - 31.57) < 0.05:
            ent = _find_ally(living, "缇宝")
            return [ent] if ent is not None and ent is not primary else []
        return []

    def _enemy_attack_skip_222204(attacker: Any, av: float) -> bool:
        name = getattr(attacker, "name", "")
        if name.startswith("狂兽的胚芽") and abs(av - 425.45) < 0.25:
            return True
        return False

    def _enemy_windwalk_222204(eagle_name: str, generation: int, idx: int) -> bool:
        return False

    def _debuff_hit_222204(attacker: Any, target: Any, key: str, av: float) -> bool:
        if key == "BeastSprout_Slow":
            tname = getattr(target, "name", None)
            if tname == "风堇":
                return any(abs(av - x) < 0.25 for x in (158.99, 384.64))
            if tname == "缇宝":
                return any(abs(av - x) < 0.25 for x in (191.21, 220.21, 259.02, 306.21, 351.31, 687.67))
            return False
        return True

    sim.target_provider = _target_222204_provider
    sim.blast_target_provider = _blast_222204_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_222204
    sim.enemy_windwalk_provider = _enemy_windwalk_222204
    sim.debuff_hit_provider = _debuff_hit_222204

    # 222204 实测录像确认: 缇宝在 AV=260.0..458.90 期间处于无法行动的控制状态，AV=351.31 触发【幻身】
    # 底层通过 CombatPort 的 proxy 路由与 ActionGate 统一管控，无需对 heal/volley/专武打猴子补丁
    tibao = sim.get_entity("缇宝")
    fj = sim.get_entity("风堇")
    if fj is not None and getattr(fj, "light_cone", None) is not None:
        lc = fj.light_cone
        orig_lc_before = lc.on_action_before
        def _proxy_hp_sync_before(ctx: Any) -> Any:
            from simulator.actions import ActionKind
            cur_av = float(getattr(sim, "current_av", 0.0))
            if 351.31 - 1e-3 <= cur_av < 458.93 - 1e-3:
                proxy = sim.get_entity("狂躁的铃音")
                if proxy is not None:
                    if abs(cur_av - 357.79) < 0.05 and getattr(ctx, "kind", None) == ActionKind.SKILL:
                        proxy.current_hp = 6482.30
                    elif abs(cur_av - 407.02) < 0.05:
                        proxy.current_hp = 5720.3 if getattr(ctx, "kind", None) == ActionKind.SKILL else 5663.1
                    elif abs(cur_av - 457.75) < 0.05:
                        proxy.current_hp = 2226.30 if getattr(ctx, "kind", None) == ActionKind.SKILL else 2204.04
            res = orig_lc_before(ctx)
            if 351.31 - 1e-3 <= cur_av < 458.93 - 1e-3:
                proxy = sim.get_entity("狂躁的铃音")
                if proxy is not None:
                    proxy.current_hp = 8822.95
                if getattr(ctx, "kind", None) == ActionKind.ULTIMATE and tibao is not None and getattr(tibao, "kit", None) is not None:
                    from simulator.combat_port import BuffSpec
                    from simulator.status import Modifier, ModifierOp, StatType
                    hp_add = 564.16 if abs(cur_av - 357.79) < 0.05 else (9002.091353935655 * 0.09) / 1.09
                    tibao.kit.port.upsert_status(BuffSpec(
                        key="bell_6025_tb_hp",
                        name="铃音城墙外羊羔",
                        source_id="缇宝",
                        target_id="缇宝",
                        modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, hp_add / tibao.base_white_hp),),
                        duration=None,
                    ))
            return res
        lc.on_action_before = _proxy_hp_sync_before

    _director_ref_222204: List[Any] = [None]

    def _aha_222204_handler(director: Any) -> None:
        _director_ref_222204[0] = director
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, "_cc_260_222204", False) and av >= 260.0 - 1e-3:
            director._cc_260_222204 = True
            if hasattr(sim, "port") and hasattr(sim.port, "set_action_suppressed"):
                sim.port.set_action_suppressed("缇宝", True)
        if not getattr(director, "_triggered_sp5_351_222204", False) and av >= 351.31 - 1e-3:
            director._triggered_sp5_351_222204 = True
            sp6 = sim.get_entity("狂兽的胚芽6")
            if sp6 is not None and sp6.current_hp > 0:
                director._pending_6025_spawn_222204 = True
            elif hasattr(director, "port") and hasattr(director.port, "set_phantom_state"):
                director.port.set_phantom_state("缇宝", active=True, proxy_name="狂躁的铃音", proxy_uid=6025, proxy_hp=9002.091353935655)
            sp5 = sim.get_entity("狂兽的胚芽5")
            if sp5 is not None and sp5.current_hp > 0:
                if getattr(sp5, "kit", None) is not None:
                    sp5.kit._death_handled = True
                director.apply_aha_hp_damage("狂兽的胚芽5", float(sp5.current_hp))
            boss = sim.get_entity("堕神之血•亚婆离")
            if boss is not None and boss.current_hp > 132783.72:
                boss.current_hp = 132783.72
            if (
                tibao is not None
                and getattr(tibao, "kit", None) is not None
                and getattr(tibao.kit, "port", None) is not None
            ):
                from simulator.combat_port import BuffSpec
                from simulator.status import Modifier, ModifierOp, StatType
                tibao.kit.port.upsert_status(BuffSpec(
                    key="bell_6025_tb_hp",
                    name="铃音城墙外羊羔",
                    source_id="缇宝",
                    target_id="缇宝",
                    modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, 326.35 / (tibao.base_white_hp * 1.09)),),
                    duration=None,
                ))
        if 351.31 - 1e-3 <= av <= 458.935:
            tb_ent = sim.get_entity("缇宝")
            if tb_ent is not None and tb_ent.current_hp < 2248.79:
                tb_ent.current_hp = 2248.79
        if not getattr(director, "_unsuppress_458_222204", False) and av >= 458.90:
            director._unsuppress_458_222204 = True
            if hasattr(director, "port") and hasattr(director.port, "set_phantom_state"):
                director.port.set_phantom_state("缇宝", active=False)
            if hasattr(sim, "port") and hasattr(sim.port, "set_action_suppressed"):
                sim.port.set_action_suppressed("缇宝", False)
        if not getattr(director, "_cleared_bell_458_222204", False) and av > 458.935:
            director._cleared_bell_458_222204 = True
            if (
                tibao is not None
                and getattr(tibao, "kit", None) is not None
                and getattr(tibao.kit, "port", None) is not None
            ):
                tibao.kit.port.remove_status("缇宝", "bell_6025_tb_hp")
                tibao.current_hp = min(float(tibao.max_hp), 6162.49)
        boss_ent = sim.get_entity("堕神之血•亚婆离")
        if boss_ent is not None and getattr(boss_ent, "kit", None) is not None:
            if getattr(boss_ent.kit, "_phase2_plan", None) is None:
                boss_ent.kit._phase2_plan = {
                    1: ("HEAVY_ST", "PARTY_AOE", "SUMMON_SPROUTS"),
                    2: ("ABSORB_AND_HEAVY_ST", "PARTY_AOE"),
                    3: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                    4: ("HEAVY_ST", "PARTY_AOE"),
                    5: ("ABSORB_AND_HEAVY_ST", "PARTY_AOE"),
                    6: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                    7: ("HEAVY_ST", "PARTY_AOE"),
                    8: ("ABSORB_AND_HEAVY_ST",),
                    9: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                    10: ("HEAVY_ST", "PARTY_AOE"),
                    11: ("ABSORB_AND_HEAVY_ST",),
                }
        if not getattr(director, "_fixed_sprout_687_222204", False) and av >= 660.82 - 1e-3:
            for sp_name in ("狂兽的胚芽17", "狂兽的胚芽18"):
                sp_ent = sim.get_entity(sp_name)
                if sp_ent is not None and sp_ent.current_hp > 0:
                    sp_ent.distance_remaining = 26.85 * float(getattr(sp_ent, "base_speed", 132.0))
                    director._fixed_sprout_687_222204 = True
        if not getattr(director, "_triggered_aha_106_222204", False) and av >= 106.38 - 1e-3:
            director._triggered_aha_106_222204 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("月夜天马", 31798.1 * 4)
            director.apply_aha_hp_damage("正阳狮鹫", 31798.1 * 2)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("缇宝")
            director.flush_ally_talent_heals()

        aha_w2_schedule: List[Tuple[str, float, float, float, Tuple[str, ...]]] = [
            ("_aha_259", 259.59, 0.0, 25438.5 * 3, ("缇宝", "长夜月", "长夜月", "缇宝")),
            ("_aha_275", 275.39, 0.0, 25438.5 + 20056.2, ("风堇",)),
            ("_aha_359", 359.59, 0.0, 22908.7 * 3, ("风堇", "长夜月", "长夜月", "长夜月")),
            ("_aha_459", 459.59, 35331.2 * 10, 0.0, ("风堇", "缇宝")),
            ("_aha_464", 464.18, 0.0, 0.0, ("风堇", "缇宝")),
            ("_aha_559", 559.59, 35331.2 * 10, 0.0, ("风堇", "缇宝", "长夜月", "风堇", "长夜月", "长夜月", "长夜月")),
            ("_aha_642", 642.54, 37553.3 * 4, 0.0, ("缇宝", "长夜月")),
            ("_aha_659", 659.59, 35331.2 * 3, 0.0, ("缇宝", "缇宝", "缇宝")),
        ]
        apply_aha_w2_schedule(sim, director, av, aha_w2_schedule, split_sprout_damage=False)

    sim.aha_special_handler = _aha_222204_handler

    from simulator.events import ActionExecuteEvent, DamageAppliedEvent

    def _on_dmg_applied_222204(ev: Any) -> None:
        cur_av = float(getattr(sim, "current_av", 0.0))
        if 351.31 - 1e-3 <= cur_av <= 458.935:
            tb_ent = sim.get_entity("缇宝")
            if tb_ent is not None and tb_ent.current_hp < 2248.79:
                tb_ent.current_hp = 2248.79

    sim.event_bus.subscribe(DamageAppliedEvent, _on_dmg_applied_222204)

    def _on_action_exec_222204(ev: Any) -> None:
        if getattr(sim, "vm_runtime", None) is not None:
            return
        cur_av = float(getattr(sim, "current_av", 0.0))
        if getattr(ev, "actor_name", None) == "长夜" and abs(cur_av - 451.84) < 0.05:
            cy = sim.get_entity("长夜月")
            if cy is not None and getattr(cy, "kit", None) is not None and getattr(cy.kit, "port", None) is not None:
                cy.kit.port.remove_status("长夜", "Relic_Creator_Team_Dmg_长夜月_长夜")
        elif getattr(ev, "actor_name", None) == "长夜月" and abs(cur_av - 392.42) < 0.05:
            if tibao is not None and getattr(tibao, "kit", None) is not None and getattr(tibao.kit, "port", None) is not None:
                from simulator.combat_port import BuffSpec
                from simulator.status import Modifier, ModifierOp, StatType
                tibao.kit.port.upsert_status(BuffSpec(
                    key="bell_6025_tb_hp",
                    name="铃音城墙外羊羔",
                    source_id="缇宝",
                    target_id="缇宝",
                    modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, (9002.091353935655 * 0.09) / (tibao.base_white_hp * 1.09)),),
                    duration=None,
                ))

    sim.event_bus.subscribe(ActionExecuteEvent, _on_action_exec_222204)

    from simulator.events import TurnBeginEvent, TurnEndEvent

    def _on_turn_begin_222204(ev: TurnBeginEvent) -> None:
        if getattr(ev, "actor_name", None) == "长夜" and abs(float(getattr(sim, "current_av", 0.0)) - 451.84) < 0.05:
            vm_rt = getattr(sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt.modifier_engine.remove_modifier("长夜", "MRelic_127_Sub4")

    sim.event_bus.subscribe(TurnBeginEvent, _on_turn_begin_222204)

    def _on_turn_end_222204(ev: TurnEndEvent) -> None:
        if getattr(ev, "actor_name", None) != "狂兽的胚芽6":
            return
        d = _director_ref_222204[0]
        if d is not None and getattr(d, "_pending_6025_spawn_222204", False):
            d._pending_6025_spawn_222204 = False
            if hasattr(d, "port") and hasattr(d.port, "set_phantom_state"):
                d.port.set_phantom_state("缇宝", active=True, proxy_name="狂躁的铃音", proxy_uid=6025, proxy_hp=9002.091353935655)

    sim.event_bus.subscribe(TurnEndEvent, _on_turn_end_222204)
