"""Unit tests for ``simulator.vm.stage_data_loader`` (Phase 2 Blueprint).

Verifies:
1. Stage 30126122 wave structure, Lv.95 HardLevelGroup(3) + EliteGroup(164) monster
   stats, weaknesses, resistances, skill multipliers, multi-phase HP, summon chains,
   and BattleEventConfig parameters against ``simulator/stage_30126122.py`` and
   ``simulator/kits/enemies/`` ground-truth constants.
2. Stage 30510021 wave structure, Lv.100 HardLevelGroup(3) + InfiniteEliteGroup(368/374)
   monster stats, skill parameter overrides, and BattleEventConfig parameters against
   ``simulator/stage_30510021.py``.
"""

from __future__ import annotations

import math
import unittest

from simulator.vm._test_stage_30126122_refs import (
    APOLI_BASE_SPEED,
    APOLI_PHASE1_BARRIER_RATIO,
    APOLI_PHASE1_HP,
    APOLI_PHASE2_BARRIER_RATIO,
    APOLI_PHASE2_HP,
    APOLI_TOUGHNESS,
    APOLI_WEAKNESSES,
    EAGLE_HP,
    EAGLE_SPEED,
    EAGLE_TOUGHNESS,
    EAGLE_WEAKNESSES,
    ENEMY_LV95_BASE_ATK,
    GRIFFIN_HP,
    GRIFFIN_SPEED,
    GRIFFIN_TOUGHNESS,
    GRIFFIN_WEAKNESSES,
    MAX_WAVES,
    PEGASUS_HP,
    PEGASUS_SPEED,
    PEGASUS_TOUGHNESS,
    PEGASUS_WEAKNESSES,
    SPROUT_HP,
    SPROUT_INTERVAL_SPEED,
    SPROUT_WEAKNESSES,
    STAGE_ID,
)
from simulator.vm.stage_data_loader import StageDataLoader, load_stage_spec


class TestStageDataLoader(unittest.TestCase):
    loader: StageDataLoader

    @classmethod
    def setUpClass(cls) -> None:
        cls.loader = StageDataLoader()

    def test_stage_30126122_waves_and_metadata(self) -> None:
        stage = self.loader.load_stage(STAGE_ID)
        self.assertEqual(stage.stage_id, 30126122)
        self.assertEqual(stage.stage_type, "Challenge")
        self.assertEqual(stage.level, 95)
        self.assertEqual(stage.hard_level_group, 3)
        self.assertEqual(stage.default_elite_group, 164)
        self.assertTrue(stage.is_elite_battle)
        self.assertEqual(stage.num_waves, MAX_WAVES)
        self.assertEqual(stage.num_waves, 2)

        # HardLevelGroup=3, Level=95 curve assertions
        curve = stage.hard_level_curve
        self.assertTrue(math.isclose(curve.atk_ratio, 34.75065, rel_tol=1e-9))
        self.assertTrue(math.isclose(curve.def_ratio, 5.47619, rel_tol=1e-9))
        self.assertTrue(math.isclose(curve.hp_ratio, 375.4385, rel_tol=1e-9))
        self.assertTrue(math.isclose(curve.speed_ratio, 1.32, rel_tol=1e-9))
        self.assertTrue(math.isclose(curve.stance_ratio, 1.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(curve.status_probability, 0.36, rel_tol=1e-9))
        self.assertTrue(math.isclose(curve.status_resistance, 0.1, rel_tol=1e-9))

        # Wave composition
        w1, w2 = stage.waves
        self.assertEqual(w1.monster_ids, (402302001, 402301001))
        self.assertEqual(w2.monster_ids, (5034010,))

        # Summoned monsters automatically discovered and compiled
        self.assertIn(402201001, stage.summon_monsters)  # 流星铁鹰 summoned by 正阳狮鹫
        self.assertIn(503201002, stage.summon_monsters)  # 狂兽的胚芽 summoned by 亚婆离

    def test_stage_30126122_monster_panels_alignment(self) -> None:
        stage = self.loader.load_stage(30126122)

        # 1. 月夜天马 (MoonlitPegasus, 402302001, Template 4023020)
        pegasus = stage.get_monster(402302001)
        self.assertEqual(pegasus.monster_template_id, 4023020)
        self.assertEqual(pegasus.name, "月夜天马")
        self.assertEqual(pegasus.rank, "Elite")
        self.assertTrue(math.isclose(pegasus.atk, ENEMY_LV95_BASE_ATK, rel_tol=1e-7))
        self.assertTrue(math.isclose(pegasus.def_, 210.0 * 5.47619, rel_tol=1e-7))
        self.assertTrue(math.isclose(pegasus.hp, PEGASUS_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(pegasus.speed, PEGASUS_SPEED, rel_tol=1e-7))
        self.assertTrue(math.isclose(pegasus.toughness, PEGASUS_TOUGHNESS, rel_tol=1e-9))
        self.assertTrue(math.isclose(pegasus.ui_toughness, 160.0, rel_tol=1e-9))
        self.assertEqual(list(pegasus.weaknesses), PEGASUS_WEAKNESSES)
        for elem in ("Physical", "Ice", "Thunder", "Wind"):
            self.assertTrue(math.isclose(pegasus.damage_res[elem], 0.2, abs_tol=1e-9))
        for elem in PEGASUS_WEAKNESSES:
            self.assertTrue(math.isclose(pegasus.damage_res[elem], 0.0, abs_tol=1e-9))

        # 2. 正阳狮鹫 (SunlitGriffin, 402301001, Template 4023010)
        griffin = stage.get_monster(402301001)
        self.assertEqual(griffin.monster_template_id, 4023010)
        self.assertEqual(griffin.name, "正阳狮鹫")
        self.assertEqual(griffin.rank, "Elite")
        self.assertTrue(math.isclose(griffin.atk, ENEMY_LV95_BASE_ATK, rel_tol=1e-7))
        self.assertTrue(math.isclose(griffin.hp, GRIFFIN_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(griffin.speed, GRIFFIN_SPEED, rel_tol=1e-7))
        self.assertTrue(math.isclose(griffin.initial_delay_ratio, 0.5, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.initial_distance, 5000.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.toughness, GRIFFIN_TOUGHNESS, rel_tol=1e-9))
        self.assertEqual(list(griffin.weaknesses), GRIFFIN_WEAKNESSES)
        self.assertEqual(griffin.summon_ids, (402201001,))

        # 3. 流星铁鹰 (MeteorEagle, 402201001, Template 4022010)
        eagle = stage.get_monster(402201001)
        self.assertEqual(eagle.monster_template_id, 4022010)
        self.assertEqual(eagle.name, "流星铁鹰")
        self.assertEqual(eagle.rank, "MinionLv2")
        self.assertTrue(math.isclose(eagle.atk, ENEMY_LV95_BASE_ATK, rel_tol=1e-7))
        self.assertTrue(math.isclose(eagle.hp, EAGLE_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(eagle.speed, EAGLE_SPEED, rel_tol=1e-7))
        self.assertTrue(math.isclose(eagle.toughness, EAGLE_TOUGHNESS, rel_tol=1e-9))
        self.assertEqual(list(eagle.weaknesses), EAGLE_WEAKNESSES)

        # Verify exact rational HP ratios relative to Eagle HP in stage_30126122.py
        self.assertTrue(math.isclose(pegasus.hp / eagle.hp, 16.0 / 3.0, rel_tol=1e-12))
        self.assertTrue(math.isclose(griffin.hp / eagle.hp, 6.0, rel_tol=1e-12))

        # 4. 堕神之血•亚婆离 (ApoliBoss, 5034010, Template 5034010)
        apoli = stage.get_monster(5034010)
        self.assertEqual(apoli.monster_template_id, 5034010)
        self.assertEqual(apoli.name, "堕神之血•亚婆离")
        self.assertEqual(apoli.rank, "LittleBoss")
        self.assertEqual(apoli.max_phase, 2)
        self.assertTrue(math.isclose(apoli.atk, ENEMY_LV95_BASE_ATK, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.phase_hp(1), APOLI_PHASE1_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.phase_hp(2), APOLI_PHASE2_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.phase_hp(2) / apoli.phase_hp(1), 2.0, rel_tol=1e-12))
        self.assertTrue(math.isclose(apoli.speed, APOLI_BASE_SPEED, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.toughness, APOLI_TOUGHNESS, rel_tol=1e-9))
        self.assertEqual(list(apoli.weaknesses), APOLI_WEAKNESSES)
        self.assertTrue(math.isclose(apoli.debuff_resist.get("STAT_CTRL", 0.0), 1.0, abs_tol=1e-9))
        self.assertEqual(apoli.summon_ids, (503201002,))

        # 5. 狂兽的胚芽 (BeastSprout, 503201002, Template 5032010)
        sprout = stage.get_monster(503201002)
        self.assertEqual(sprout.monster_template_id, 5032010)
        self.assertEqual(sprout.name, "狂兽的胚芽")
        self.assertTrue(math.isclose(sprout.hp, SPROUT_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(sprout.hp / eagle.hp, 2.0, rel_tol=1e-12))
        self.assertEqual(list(sprout.weaknesses), SPROUT_WEAKNESSES)

    def test_stage_30126122_skills_and_battle_events_alignment(self) -> None:
        stage = self.loader.load_stage(30126122)

        # Pegasus skills vs simulator/kits/enemies/pegasus.py
        pegasus = stage.get_monster(402302001)
        self.assertEqual(pegasus.skill("Skill01").damage_type, "Quantum")
        self.assertTrue(math.isclose(pegasus.skill("Skill01").param(0), 3.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(pegasus.skill("Skill01").sp_hit_base, 5.0, rel_tol=1e-9))

        self.assertEqual(pegasus.skill("Skill02").damage_type, "Quantum")
        self.assertTrue(math.isclose(pegasus.skill("Skill02").param(0), 2.6, rel_tol=1e-9))
        self.assertTrue(math.isclose(pegasus.skill("Skill02").sp_hit_base, 10.0, rel_tol=1e-9))

        self.assertEqual(pegasus.skill("Skill04").damage_type, "Quantum")
        self.assertTrue(math.isclose(pegasus.skill("Skill04").param(0), 4.5, rel_tol=1e-9))
        self.assertTrue(math.isclose(pegasus.skill("Skill04").sp_hit_base, 20.0, rel_tol=1e-9))

        # Griffin skills vs simulator/kits/enemies/griffin.py
        griffin = stage.get_monster(402301001)
        self.assertEqual(griffin.skill("Skill01").damage_type, "Fire")
        self.assertTrue(math.isclose(griffin.skill("Skill01").param(0), 3.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.skill("Skill01").sp_hit_base, 5.0, rel_tol=1e-9))

        # Skill02: 2.6 AoE Fire + initial action delay ratios (0.5, 0.8, 1.1) for 3 summoned Eagles
        self.assertEqual(griffin.skill("Skill02").damage_type, "Fire")
        self.assertTrue(math.isclose(griffin.skill("Skill02").param(0), 2.6, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.skill("Skill02").param(1), 0.5, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.skill("Skill02").param(2), 0.8, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.skill("Skill02").param(3), 1.1, rel_tol=1e-9))

        # Skill04: 4.0 main target + 3.0 adjacent Fire blast
        self.assertEqual(griffin.skill("Skill04").damage_type, "Fire")
        self.assertTrue(math.isclose(griffin.skill("Skill04").param(0), 4.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin.skill("Skill04").param(1), 3.0, rel_tol=1e-9))

        # Eagle skills vs simulator/kits/enemies/eagle.py
        eagle = stage.get_monster(402201001)
        self.assertEqual(eagle.skill("Skill01").damage_type, "Wind")
        self.assertTrue(math.isclose(eagle.skill("Skill01").param(0), 2.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(eagle.skill("Skill01").sp_hit_base, 5.0, rel_tol=1e-9))

        # Apoli skills vs simulator/kits/enemies/apoli.py
        apoli = stage.get_monster(5034010)
        self.assertEqual(apoli.skill("Skill01").damage_type, "Quantum")
        self.assertTrue(math.isclose(apoli.skill("Skill01").param(0), 5.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(apoli.skill("Skill01").sp_hit_base, 10.0, rel_tol=1e-9))

        self.assertEqual(apoli.skill("Skill02").damage_type, "Quantum")
        self.assertTrue(math.isclose(apoli.skill("Skill02").param(0), 1.8, rel_tol=1e-9))
        self.assertTrue(math.isclose(apoli.skill("Skill02").sp_hit_base, 10.0, rel_tol=1e-9))

        # Skill03: absorb sprout & heal 4% MaxHP, +10% dmg buff for 2 turns
        self.assertTrue(math.isclose(apoli.skill("Skill03").param(0), 0.1, rel_tol=1e-9))
        self.assertTrue(math.isclose(apoli.skill("Skill03").param(2), 0.04, rel_tol=1e-9))

        # PassiveSkill01 & PassiveSkill02: barrier trigger=0.70, barrier ratio=0.65, dmg reduction=0.75, break penalty=0.35, floor=0.30
        p1 = apoli.skill("PassiveSkill01")
        p2 = apoli.skill("PassiveSkill02")
        self.assertTrue(math.isclose(p1.param(1), 0.70, rel_tol=1e-9))
        self.assertTrue(math.isclose(p1.param(2), APOLI_PHASE1_BARRIER_RATIO, rel_tol=1e-9))
        self.assertTrue(math.isclose(p1.param(3), 0.75, rel_tol=1e-9))
        self.assertTrue(math.isclose(p1.param(4), 0.35, rel_tol=1e-9))
        self.assertTrue(math.isclose(p1.param(5), 2.0, rel_tol=1e-9))  # Phase 2 HP multiplier
        self.assertTrue(math.isclose(p1.param(6), 0.30, rel_tol=1e-9))

        self.assertTrue(math.isclose(p2.param(0), 0.70, rel_tol=1e-9))
        self.assertTrue(math.isclose(p2.param(1), APOLI_PHASE2_BARRIER_RATIO, rel_tol=1e-9))
        self.assertTrue(math.isclose(p2.param(2), 0.75, rel_tol=1e-9))
        self.assertTrue(math.isclose(p2.param(3), 0.35, rel_tol=1e-9))
        self.assertTrue(math.isclose(p2.param(5), 0.50, rel_tol=1e-9))  # Phase 2 berserk +50% speed ratio
        self.assertTrue(math.isclose(p2.param(6), 0.30, rel_tol=1e-9))

        # PassiveSkill03: death backlash 0.02 (2% of Phase 1 MaxHP)
        self.assertTrue(math.isclose(apoli.skill("PassiveSkill03").param(3), 0.02, rel_tol=1e-9))

        # Sprout skills vs simulator/kits/enemies/sprout.py
        sprout = stage.get_monster(503201002)
        self.assertEqual(sprout.skill("Skill01").damage_type, "Quantum")
        self.assertTrue(math.isclose(sprout.skill("Skill01").base_param(0), 2.2, rel_tol=1e-9))
        self.assertTrue(math.isclose(sprout.skill("Skill01").param(0), 2.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(sprout.skill("Skill02").param(0), 0.02, rel_tol=1e-9))

        # BattleEvents: 30149 (Stage turbulence) and 20041 (Apoli sprout summon interval)
        be_map = {be.battle_event_id: be for be in stage.battle_events}
        self.assertIn(30149, be_map)
        be_30149 = be_map[30149]
        self.assertEqual(be_30149.ability_list, ("BattleEventAbility_Challenge_Month_49",))
        self.assertEqual(be_30149.param_list, (5.0, 20.0))
        self.assertTrue(math.isclose(be_30149.base_speed, 100.0, rel_tol=1e-9))

        self.assertIn(20041, be_map)
        be_20041 = be_map[20041]
        self.assertTrue(math.isclose(be_20041.effective_speed, SPROUT_INTERVAL_SPEED, rel_tol=1e-9))
        self.assertTrue(math.isclose(be_20041.action_value or 0.0, 10000.0 / 132.0, rel_tol=1e-7))

    def test_stage_30510021_infinite_group_and_lv100_panels(self) -> None:
        stage = load_stage_spec(30510021)
        self.assertEqual(stage.stage_id, 30510021)
        self.assertEqual(stage.level, 100)
        self.assertEqual(stage.hard_level_group, 3)
        self.assertEqual(stage.stage_infinite_group_id, 30510021)
        self.assertEqual(stage.num_waves, 2)

        # Wave 1: InfiniteMonsterGroup 305100211 -> [402302001, 8033020], InfiniteEliteGroup 368 (HP=6.8, ATK=1.1)
        w1, w2 = stage.waves
        self.assertEqual(w1.monster_ids, (402302001, 8033020))
        self.assertEqual(w1.elite_group, 368)

        pegasus_100 = w1.monsters[0]
        beacon_100 = w1.monsters[1]
        self.assertTrue(math.isclose(pegasus_100.hp, 4904294.0, rel_tol=2e-4))
        self.assertTrue(math.isclose(beacon_100.hp, 4291259.0, rel_tol=2e-4))
        self.assertEqual(list(beacon_100.weaknesses), ["Fire", "Wind", "Quantum"])

        # Summoned 千星戍卫 (8032040) in Wave 1
        guard_100 = stage.get_monster(8032040)
        self.assertEqual(guard_100.name, "千星戍卫")
        self.assertTrue(math.isclose(guard_100.hp, 459777.8, rel_tol=1e-5))
        self.assertTrue(math.isclose(guard_100.speed, 145.2, rel_tol=1e-5))
        self.assertTrue(math.isclose(guard_100.toughness, 90.0, rel_tol=1e-9))
        self.assertEqual(list(guard_100.weaknesses), ["Wind", "Quantum"])

        # Wave 2: InfiniteMonsterGroup 305100212 -> [503401002], InfiniteEliteGroup 374 (HP=6.3, ATK=1.1)
        self.assertEqual(w2.monster_ids, (503401002,))
        self.assertEqual(w2.elite_group, 374)
        apoli_100 = w2.monsters[0]
        self.assertTrue(math.isclose(apoli_100.phase_hp(1), 6389558.5, rel_tol=1e-5))
        self.assertTrue(math.isclose(apoli_100.phase_hp(2), 12779116.9, rel_tol=1e-5))
        # 503401002 overrides barrier ratio in PassiveSkill01[2] and PassiveSkill02[1] to 0.95
        self.assertTrue(math.isclose(apoli_100.skill("PassiveSkill01").param(2), 0.95, rel_tol=1e-9))
        self.assertTrue(math.isclose(apoli_100.skill("PassiveSkill02").param(1), 0.95, rel_tol=1e-9))

        sprout_100 = stage.get_monster(503201002)
        self.assertTrue(math.isclose(sprout_100.hp, 1703882.3, rel_tol=1e-5))

        # BattleEvent 30503 (ChallengePeakBattle countdown / infinite wave event)
        be_map = {be.battle_event_id: be for be in stage.battle_events}
        self.assertIn(30503, be_map)
        self.assertEqual(be_map[30503].param_list, (0.5, 7.0, 4.0, 0.5))

    def test_wave_scoped_summons_and_multi_subgroup_infinite_waves(self) -> None:
        import copy

        custom_loader = StageDataLoader()
        _ = custom_loader.stages
        _ = custom_loader.infinite_waves
        _ = custom_loader.infinite_groups
        _ = custom_loader.infinite_monster_groups

        # 构造两波次无限波次：Wave 0 包含多子组 [305100211, 305100212]
        w0 = copy.deepcopy(custom_loader.infinite_waves[305100211])
        w0["MonsterGroupIDList"] = [305100211, 305100212]
        custom_loader._infinite_wave_by_id[9999001] = w0
        w1 = copy.deepcopy(custom_loader.infinite_waves[305100212])
        custom_loader._infinite_wave_by_id[9999002] = w1

        custom_loader._infinite_group_by_id[9999000] = {
            "WaveGroupID": 9999000,
            "WaveIDList": [9999001, 9999002],
        }
        st_row = copy.deepcopy(custom_loader.stages[30510021])
        st_row["StageID"] = 9999000
        for item in st_row["StageConfigData"]:
            if item.get("BFLIFKBEOPJ") == "_StageInfiniteGroup":
                item["MNDFOPKBHKP"] = "9999000"
        custom_loader._stage_by_id[9999000] = st_row

        stage = custom_loader.load_stage(9999000)
        self.assertEqual(stage.num_waves, 2)
        self.assertEqual(stage.waves[0].infinite_monster_group_ids, (305100211, 305100212))
        self.assertEqual(stage.waves[0].monster_ids, (402302001, 8033020, 503401002))
        self.assertIn(8032040, stage.waves[0].summon_monsters)
        self.assertNotIn(8032040, stage.waves[1].summon_monsters)
        with self.assertRaises(KeyError):
            stage.get_summon_monster(8032040, wave_index=1)

        # 验证同 ID 召唤物在不同 EliteGroup 波次下各自独立缩放 (6.8 vs 6.3)
        custom_loader._infinite_monster_group_by_id[9999368] = {
            "InfiniteMonsterGroupID": 9999368,
            "MonsterList": [503401002],
            "EliteGroup": 368,
        }
        custom_loader._infinite_wave_by_id[9999001]["MonsterGroupIDList"] = [9999368]
        stage2 = custom_loader.load_stage(9999000)
        s_w0 = stage2.get_summon_monster(503201002, wave_index=0)
        s_w1 = stage2.get_summon_monster(503201002, wave_index=1)
        self.assertTrue(math.isclose(s_w0.hp / s_w1.hp, 6.8 / 6.3, rel_tol=1e-9))

    def test_extract_monster_battle_events_raises_on_corrupt_json(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tbgd = Path(tmp)
            ab_dir = tbgd / "Config" / "ConfigAbility" / "Monster"
            ab_dir.mkdir(parents=True)
            (ab_dir / "Broken_Monster_Ability.json").write_text("{bad json", encoding="utf-8")

            tmp_loader = StageDataLoader(tbgd_root=tbgd, load_textmap=False)
            curve = self.loader.get_hard_level_curve(3, 95)
            with self.assertRaises(RuntimeError) as ctx:
                tmp_loader._extract_monster_battle_events(
                    {"JsonConfig": "Config/ConfigCharacter/Monster/Broken_Monster_Config.json", "AbilityList": []},
                    curve,
                )
            self.assertIn("Broken_Monster_Ability.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
