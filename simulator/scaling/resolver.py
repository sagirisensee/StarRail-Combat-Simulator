"""
技能等级与倍率解析器 (Skill Scaling Resolver).
严格根据官方 4.6 资产库，将已培养等级 + 星魂升级 (E3/E5) 解析为实际生效等级，并检索确凿 ParamList。
"""

from typing import Dict, Optional, Tuple, Any
from ..assets.models import CharacterAsset, CharacterSkillAsset, EidolonSkillBonus
from ..assets.repository import AssetRepository
from .models import SkillBinding


class SkillScaling:
    """角色技能星魂与等级自适应缩放器。"""

    def __init__(
        self,
        character_asset: CharacterAsset,
        *,
        eidolon: int = 0,
        trained_levels: Optional[Dict[str, int]] = None
    ):
        self.character = character_asset
        self.eidolon = max(0, min(6, int(eidolon)))
        self.trained_levels = trained_levels or {}

        # 建立语义键 -> SkillBinding 映射
        self._bindings: Dict[str, SkillBinding] = {}
        self._init_bindings()

    def _init_bindings(self) -> None:
        type_to_semantic = {
            "Normal": "basic",
            "BPSkill": "skill",
            "Ultra": "ultra",
            "Talent": "talent",
            "Maze": "technique",
        }
        for sid, skill in self.character.skills.items():
            sem = type_to_semantic.get(skill.type)
            if sem and sem not in self._bindings:
                default_lvl = 6 if sem == "basic" else (1 if sem == "technique" else 10)
                self._bindings[sem] = SkillBinding(
                    semantic_key=sem,
                    skill_id=sid,
                    skill_type=skill.type,
                    skill_name=skill.name,
                    default_trained_level=default_lvl,
                )
            # 同时也支持直接用 skill_id 访问
            self._bindings[str(sid)] = SkillBinding(
                semantic_key=str(sid),
                skill_id=sid,
                skill_type=skill.type,
                skill_name=skill.name,
                default_trained_level=10,
            )

    def get_skill_asset(self, skill_key: str) -> Optional[CharacterSkillAsset]:
        binding = self._bindings.get(skill_key)
        if not binding:
            # 尝试直接通过 ID 查找
            return self.character.skills.get(skill_key)
        return self.character.skills.get(binding.skill_id)

    def effective_level(self, skill_key: str) -> int:
        """计算指定技能在当前星魂下的最终生效等级。"""
        binding = self._bindings.get(skill_key)
        if not binding:
            return 10

        skill = self.character.skills.get(binding.skill_id)
        if not skill:
            return 10

        # 若该技能没有多等级数据（如秘技），返回 1
        if len(skill.params_by_level) <= 1:
            return 1

        # 玩家基础培养等级
        trained = self.trained_levels.get(skill_key, binding.default_trained_level)

        # 统计解锁星魂带来的技能等级增益
        bonus_delta = 0
        max_allowed = 15 if binding.skill_type != "Normal" else 10
        for bonus in self.character.eidolon_skill_bonuses:
            if bonus.eidolon <= self.eidolon and bonus.skill_type == binding.skill_type:
                bonus_delta += bonus.delta
                max_allowed = max(max_allowed, bonus.max_level)

        effective = min(trained + bonus_delta, max_allowed)

        # 确保有效等级在数据表范围内
        available_levels = sorted(skill.params_by_level.keys())
        if effective not in skill.params_by_level:
            # 若超出上限，截断至最大可用等级；若低于下限，取最小可用等级
            if effective > available_levels[-1]:
                effective = available_levels[-1]
            elif effective < available_levels[0]:
                effective = available_levels[0]

        return effective

    def params(self, skill_key: str) -> Tuple[float, ...]:
        """获取指定技能在当前生效等级下的完整参数元组。"""
        skill = self.get_skill_asset(skill_key)
        if not skill or not skill.params_by_level:
            return ()
        eff_lvl = self.effective_level(skill_key)
        return skill.params_by_level.get(eff_lvl, ())

    def value(self, skill_key: str, index: int, default: float = 0.0) -> float:
        """获取指定技能在当前生效等级下的第 index 项参数。"""
        p = self.params(skill_key)
        if 0 <= index < len(p):
            return p[index]
        return default

    def eidolon_value(self, rank: int, index: int, default: float = 0.0) -> float:
        """获取指定星魂 (1~6) 的第 index 项官方参数。"""
        eid = self.character.eidolons.get(int(rank))
        if eid and 0 <= index < len(eid.params):
            return float(eid.params[index])
        return default

    def dump_status(self) -> Dict[str, Any]:
        """输出所有技能的当前生效等级与参数概览。"""
        res = {}
        for sem in ("basic", "skill", "ultra", "talent", "technique"):
            if sem in self._bindings:
                lvl = self.effective_level(sem)
                p = self.params(sem)
                b = self._bindings[sem]
                res[sem] = {
                    "name": b.skill_name,
                    "effective_level": lvl,
                    "params": list(p),
                }
        return res


class SkillScalingFactory:
    """缩放器创建工厂。"""

    @staticmethod
    def create(
        character_id_or_name: str,
        *,
        eidolon: int = 0,
        trained_levels: Optional[Dict[str, int]] = None
    ) -> Optional[SkillScaling]:
        repo = AssetRepository.get_instance()
        char_asset = repo.get_character(character_id_or_name)
        if not char_asset:
            return None
        return SkillScaling(char_asset, eidolon=eidolon, trained_levels=trained_levels)
