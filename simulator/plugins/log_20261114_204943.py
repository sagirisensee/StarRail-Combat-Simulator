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
            return _find_ally(living, "晴空乐手")
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
        if abs(av - 227.27) < 0.05 and getattr(attacker, "name", None) == "月夜天马":
            return _find_ally(living, "小伊卡")
        return None

    def _blast_204943_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        # 31.57 AV 正阳狮鹫扩散在实机中仅命中知更鸟•晴歌
        if abs(av - 31.57) < 0.05:
            return []
        # 94.70 AV 正阳狮鹫在实机中未命中风堇与知更鸟•晴歌
        if abs(av - 94.70) < 0.05:
            return []
        # 151.52 AV 月夜天马 3 段扩散命中知更鸟•晴歌、风堇与小伊卡
        if abs(av - 151.52) < 0.05:
            return [e for e in living if getattr(e, "name", None) in ("风堇", "小伊卡")]
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
            director.apply_aha_ally_chip_hit("晴空乐手")
            if robin_ent is not None and getattr(robin_ent, "kit", None) is not None and hasattr(robin_ent.kit, "_heal_provider_keys"):
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
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.apply_aha_ally_chip_hit("晴空乐手")
            if robin_ent is not None and getattr(robin_ent, "kit", None) is not None and hasattr(robin_ent.kit, "_heal_provider_keys"):
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
                ika_ent = sim.get_entity("小伊卡")
                if ika_ent is not None and getattr(ika_ent, "kit", None) is not None:
                    ika_kit = ika_ent.kit
                    if hasattr(ika_kit, "_resolve_talent_heal"):
                        ika_kit._resolve_talent_heal()
                    master = getattr(ika_kit, "master_kit", None)
                    if master is not None and hasattr(master, "in_rain_state") and master.in_rain_state():
                        raw_heal = ika_kit.port.max_hp(master.owner_id) * ika_kit.TALENT_HEAL_PCT + ika_kit.TALENT_HEAL_FLAT
                        for ally in ika_kit.port.allies(ika_kit.owner_id):
                            if not (hasattr(ika_kit.port, "is_countdown") and ika_kit.port.is_countdown(ally)):
                                ika_kit.port.heal(ika_kit.owner_id, ally, master._apply_outgoing_healing(raw_heal, ally))
                        master.on_healing_provided()
                robin_ent = sim.get_entity("知更鸟•晴歌")
                if robin_ent is not None and getattr(robin_ent, "kit", None) is not None and hasattr(robin_ent.kit, "_heal_provider_keys"):
                    robin_ent.kit._heal_provider_keys.clear()
                # 实机 157.83 AV 第二动仅命中知更鸟•晴歌 (884.26)，未命中风堇
                griffin.kit._turn_count += 1
                griffin.kit._generation += 1
                griffin.kit._turns_since_summon = 0
                griffin.kit._summon_ids = griffin.kit.port.summon_meteor_eagles(
                    owner_id=griffin.kit.owner_id,
                    generation=griffin.kit._generation,
                    count=griffin.kit.SUMMON_COUNT,
                    initial_distances=griffin.kit.SUMMON_INITIAL_DISTANCES,
                )
                saved_tp = getattr(sim, "target_provider", None)
                sim.target_provider = None
                try:
                    griffin.kit.port.apply_enemy_attack(
                        owner_id=griffin.kit.owner_id,
                        target_ids=("知更鸟•晴歌",),
                        multiplier=2.6,
                        element="Fire",
                        hit_energy=5.0,
                        hits=1,
                    )
                    griffin.kit._apply_aquila_marks(("知更鸟•晴歌",))
                finally:
                    sim.target_provider = saved_tp
                if hasattr(sim, "status_mgr") and sim.status_mgr is not None:
                    sim.status_mgr.tick_on_turn_end(griffin)
            return res

        griffin.kit.execute_turn = _griffin_204943_exec

    # 160.02 AV 晴空乐手暴击真值对齐: 实机中未暴击落在月夜天马 (13591.17)，而非 0 号位流星铁鹰_g2_1
    orig_crit_oracle = getattr(sim, "crit_oracle", None)
    if orig_crit_oracle is not None:
        def _crit_oracle_204943(req: Any) -> bool:
            res = bool(orig_crit_oracle(req))
            av = float(getattr(sim, "current_av", 0.0))
            if abs(av - 160.02) < 0.05 and getattr(req.attacker, "name", None) == "晴空乐手":
                tname = getattr(req.target, "name", None)
                if tname == "月夜天马":
                    return False
                if tname == "流星铁鹰_g2_1":
                    return True
            return res

        sim.crit_oracle = _crit_oracle_204943
