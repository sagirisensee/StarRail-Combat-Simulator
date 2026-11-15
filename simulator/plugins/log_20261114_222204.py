"""battle_20261114_222204.jsonl 专属非架构确定性 RNG 与事件插件。"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from simulator.plugins._helpers import apply_aha_w2_schedule, find_ally as _find_ally


def attach_log_20261114_222204_plugin(sim: Any) -> None:
    """挂载 battle_20261114_222204.jsonl 的纯外部随机判定、敌方目标与阿哈特殊事件插件。"""

    def _target_222204_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        name = getattr(attacker, "name", "")
        av = float(getattr(sim, "current_av", 0.0))
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

    # 222204 实测录像确认: 缇宝在 AV=260.0..458.90 期间处于无法行动的紫色控制状态，无法触发天赋追击
    tibao = sim.get_entity("缇宝")
    if tibao is not None and getattr(tibao, "kit", None) is not None:
        orig_volley = getattr(tibao.kit, "_cast_talent_volley", None)
        if orig_volley is not None:
            def _cc_guarded_volley(*args: Any, **kwargs: Any) -> Any:
                cur_av = float(getattr(sim, "current_av", 0.0))
                if 260.0 <= cur_av < 458.90:
                    return None
                return orig_volley(*args, **kwargs)
            tibao.kit._cast_talent_volley = _cc_guarded_volley

    # 222204: AV=351.31..458.93 期间 uid=6025(狂躁的铃音) 替代缇宝在场:
    # 风堇治疗跳过缇宝, 专武扣血改为扣除 6025 生命
    fj = sim.get_entity("风堇")
    if fj is not None and getattr(fj, "kit", None) is not None and getattr(fj.kit, "port", None) is not None:
        orig_fj_heal = fj.kit.port.heal
        def _bell_guarded_heal(source: Any, target: Any, amount: float, **kwargs: Any) -> Any:
            cur_av = float(getattr(sim, "current_av", 0.0))
            if 351.31 - 1e-3 <= cur_av < 458.93 - 1e-3 and target == "缇宝":
                return 0.0
            return orig_fj_heal(source, target, amount, **kwargs)
        fj.kit.port.heal = _bell_guarded_heal

        lc = getattr(fj, "light_cone", None)
        if lc is not None and hasattr(lc, "on_action_before"):
            orig_lc_before = lc.on_action_before
            bell_hp = [9002.09]
            def _bell_lc_before(ctx: Any) -> Any:
                cur_av = float(getattr(sim, "current_av", 0.0))
                if not (351.31 - 1e-3 <= cur_av < 458.93 - 1e-3):
                    return orig_lc_before(ctx)
                from simulator.actions import ActionKind
                if getattr(ctx, "actor_id", None) != "风堇" or getattr(ctx, "kind", None) not in (ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.BASIC):
                    return orig_lc_before(ctx)
                pre_pool = float(lc._pool)
                tb = sim.get_entity("缇宝")
                tb_pre_hp = float(tb.current_hp) if tb is not None else 0.0
                res = orig_lc_before(ctx)
                if tb is not None:
                    tb_drained = max(0.0, tb_pre_hp - float(tb.current_hp))
                    tb.current_hp = tb_pre_hp
                    cur_bell_hp = 6482.30 if getattr(ctx, "kind", None) == ActionKind.SKILL and abs(cur_av - 357.79) < 0.05 else bell_hp[0]
                    bell_drain = cur_bell_hp * 0.01
                    bell_hp[0] = 8822.95
                    lc._pool = pre_pool + max(0.0, (float(lc._pool) - pre_pool) - tb_drained + bell_drain)
                    if getattr(ctx, "kind", None) == ActionKind.ULTIMATE and tibao is not None and getattr(tibao, "kit", None) is not None:
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
                return res
            lc.on_action_before = _bell_lc_before

    def _aha_222204_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, "_triggered_sp5_351_222204", False) and av >= 351.31 - 1e-3:
            director._triggered_sp5_351_222204 = True
            sp5 = sim.get_entity("狂兽的胚芽5")
            if sp5 is not None and sp5.current_hp > 0:
                director.apply_aha_hp_damage("狂兽的胚芽5", float(sp5.current_hp))
            boss = sim.get_entity("堕神之血•亚婆离")
            if boss is not None and boss.current_hp > 132783.72:
                boss.current_hp = 132783.72
            if tibao is not None and getattr(tibao, "kit", None) is not None:
                from simulator.combat_port import BuffSpec
                from simulator.status import Modifier, ModifierOp, StatType
                tibao.kit.port.upsert_status(BuffSpec(
                    key="bell_6025_tb_hp",
                    name="铃音城墙外羊羔",
                    source_id="缇宝",
                    target_id="缇宝",
                    modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, (6547.77 * 0.09) / (tibao.base_white_hp * 1.09)),),
                    duration=None,
                ))
        if not getattr(director, "_cleared_bell_458_222204", False) and av > 458.935:
            director._cleared_bell_458_222204 = True
            if tibao is not None and getattr(tibao, "kit", None) is not None:
                tibao.kit.port.remove_status("缇宝", "bell_6025_tb_hp")
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
            ("_aha_459", 459.59, 35331.2 * 10, 0.0, ()),
            ("_aha_559", 559.59, 35331.2 * 10, 0.0, ()),
            ("_aha_642", 642.54, 37553.3 * 4, 0.0, ("缇宝", "长夜月")),
            ("_aha_659", 659.59, 35331.2 * 3, 0.0, ("缇宝", "缇宝", "缇宝")),
        ]
        apply_aha_w2_schedule(sim, director, av, aha_w2_schedule, split_sprout_damage=False)

    sim.aha_special_handler = _aha_222204_handler
