"""Official TurnBasedGameData Stage & Monster read-only data loader (Phase 2).

Reads official ExcelOutput and Config JSON tables under ``data/TurnBasedGameData``:
- ``ExcelOutput/StageConfig.json``
- ``ExcelOutput/StageInfiniteGroup.json``
- ``ExcelOutput/StageInfiniteWaveConfig.json``
- ``ExcelOutput/StageInfiniteMonsterGroup.json``
- ``ExcelOutput/MonsterConfig.json``
- ``ExcelOutput/MonsterTemplateConfig.json``
- ``ExcelOutput/HardLevelGroup.json``
- ``ExcelOutput/EliteGroup.json``
- ``ExcelOutput/InfiniteEliteGroup.json``
- ``ExcelOutput/MonsterSkillConfig.json``
- ``ExcelOutput/BattleEventConfig.json``
- ``TextMap/TextMapCHS.json`` (optional, for human-readable monster/skill names)
- ``Config/ConfigCharacter/Monster/*.json`` (for multi-phase HP ratios & preloaded BattleEvents)

Produces immutable, pure-data dataclasses describing stage waves, monster panel
stats at the stage's true level, monster skills & multipliers, summoned monster
specs, and stage/monster BattleEvent configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

_SHARED_EXCEL_CACHE: dict[tuple[str, str], tuple[tuple[int, int], Any]] = {}
_SHARED_TEXTMAP_CACHE: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}


DEFAULT_TBGD_ROOT = (
    Path(__file__).resolve().parents[2] / "data" / "TurnBasedGameData"
)

ALL_DAMAGE_TYPES: tuple[str, ...] = (
    "Physical",
    "Fire",
    "Ice",
    "Thunder",
    "Wind",
    "Quantum",
    "Imaginary",
)


def _unwrap_value(raw: Any, default: float = 0.0) -> float:
    """Extract numeric ``Value`` from a TurnBasedGameData wrapper dict or scalar."""
    if raw is None:
        return default
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, Mapping) and "Value" in raw:
        val = raw["Value"]
        if isinstance(val, (int, float)):
            return float(val)
    return default


def _snap_rational_base(base_value: float, modify_ratio: float) -> float:
    """Recover exact rational product when ``modify_ratio`` is a 6-digit truncated fraction.

    In ``MonsterConfig.json``, ratios such as ``1.454545`` (``16/11`` on ``HPBase=1023``
    -> ``1488``) or ``1.384615`` (``18/13`` on ``HPBase=1209`` -> ``1674``) are serialized
    with 6 decimal places. When ``modify_ratio`` matches a small-denominator fraction
    within ``1e-6`` that evenly divides ``base_value``, return the exact rational product.
    """
    if abs(modify_ratio - 1.0) < 1e-12:
        return float(base_value)
    frac = Fraction(modify_ratio).limit_denominator(64)
    if abs(float(frac) - modify_ratio) <= 1e-6:
        scaled_num = base_value * frac.numerator
        if abs(scaled_num - round(scaled_num)) < 1e-9 and int(round(scaled_num)) % frac.denominator == 0:
            return float(int(round(scaled_num)) // frac.denominator)
    return float(base_value) * float(modify_ratio)


@dataclass(frozen=True)
class HardLevelCurveSpec:
    """Level scaling curve row from ``HardLevelGroup.json``."""

    hard_level_group: int
    level: int
    hp_ratio: float
    atk_ratio: float
    def_ratio: float
    speed_ratio: float
    stance_ratio: float
    status_probability: float
    status_resistance: float


@dataclass(frozen=True)
class EliteGroupSpec:
    """Elite scaling multipliers from ``EliteGroup.json`` or ``InfiniteEliteGroup.json``."""

    elite_group: int
    hp_ratio: float = 1.0
    atk_ratio: float = 1.0
    def_ratio: float = 1.0
    speed_ratio: float = 1.0
    stance_ratio: float = 1.0
    source_table: str = "EliteGroup"


@dataclass(frozen=True)
class CompiledMonsterSkillSpec:
    """Compiled monster skill metadata and parameter array from ``MonsterSkillConfig.json``."""

    skill_id: int
    name: str
    trigger_key: str
    skill_type_desc: str
    damage_type: Optional[str]
    attack_type: Optional[str]
    sp_hit_base: float
    base_params: tuple[float, ...]
    effective_params: tuple[float, ...]
    is_passive: bool = False
    is_blast: bool = False
    is_aoe: bool = False
    hit_count: int = 1
    has_mark_target: bool = False
    delay_ratio: float = 1.0

    def param(self, index: int, default: float = 0.0) -> float:
        """Return effective skill parameter at ``index`` (0-based)."""
        if 0 <= index < len(self.effective_params):
            return self.effective_params[index]
        return default

    def base_param(self, index: int, default: float = 0.0) -> float:
        """Return un-overridden base skill parameter at ``index`` (0-based)."""
        if 0 <= index < len(self.base_params):
            return self.base_params[index]
        return default


@dataclass(frozen=True)
class CompiledMonsterPhaseSpec:
    """Phase configuration for multi-phase boss monsters."""

    phase_num: int
    max_hp_multiplier: float
    max_hp: float
    raw_max_hp: float
    stance_multiplier: float = 1.0
    max_toughness: float = 0.0


@dataclass(frozen=True)
class CompiledBattleEventSpec:
    """Compiled BattleEvent configuration from ``BattleEventConfig.json``."""

    battle_event_id: int
    name: str
    team: str
    event_sub_type: str
    ability_list: tuple[str, ...]
    override_properties: Mapping[str, float]
    base_speed: float
    hard_level_scaling: bool
    effective_speed: float
    action_value: Optional[float]
    param_list: tuple[float, ...]
    description_key: str = ""


@dataclass(frozen=True)
class CompiledMonsterSpec:
    """Compiled monster panel, resistances, skills, phases, and summon metadata."""

    monster_id: int
    monster_template_id: int
    name: str
    rank: str
    level: int
    hard_level_group: int
    elite_group: int
    # Template base values
    hp_base: float
    atk_base: float
    def_base: float
    speed_base: float
    stance_base: float
    crit_damage_base: float
    status_resistance_base: float
    initial_delay_ratio: float
    initial_distance: float
    stance_count: int
    stance_type: Optional[str]
    # MonsterConfig modify ratios
    hp_modify_ratio: float
    atk_modify_ratio: float
    def_modify_ratio: float
    speed_modify_ratio: float
    stance_modify_ratio: float
    # Computed final panel at stage level
    hp: float
    raw_hp: float
    atk: float
    def_: float
    speed: float
    toughness: float
    ui_toughness: float
    status_probability: float
    status_resistance: float
    # Weaknesses & resistances
    weaknesses: tuple[str, ...]
    damage_res: Mapping[str, float]
    debuff_resist: Mapping[str, float]
    # Multi-phase & skills
    max_phase: int
    phases: tuple[CompiledMonsterPhaseSpec, ...]
    skills: Mapping[int, CompiledMonsterSkillSpec]
    skills_by_key: Mapping[str, CompiledMonsterSkillSpec]
    # Summons & config paths
    summon_ids: tuple[int, ...]
    custom_values: Mapping[str, Any]
    json_config_path: str
    ai_path: str
    ability_list: tuple[str, ...] = ()
    battle_events: tuple[CompiledBattleEventSpec, ...] = ()
    custom_value_tags: tuple[str, ...] = ()

    def skill(self, key_or_id: str | int) -> CompiledMonsterSkillSpec:
        """Lookup a monster skill by ``SkillTriggerKey`` (e.g. ``'Skill01'``) or ``SkillID``."""
        if isinstance(key_or_id, int):
            return self.skills[key_or_id]
        return self.skills_by_key[key_or_id]

    def phase_hp(self, phase_num: int = 1) -> float:
        """Return computed MaxHP for ``phase_num`` (1-indexed)."""
        for p in self.phases:
            if p.phase_num == phase_num:
                return p.max_hp
        raise KeyError(f"Phase {phase_num} not found for monster {self.monster_id}")


@dataclass(frozen=True)
class CompiledWaveSpec:
    """Single wave composition and wave-level scaling metadata."""

    wave_index: int
    monster_ids: tuple[int, ...]
    monsters: tuple[CompiledMonsterSpec, ...]
    elite_group: int
    infinite_wave_id: Optional[int] = None
    infinite_monster_group_id: Optional[int] = None
    infinite_monster_group_ids: tuple[int, ...] = ()
    max_monster_count: Optional[int] = None
    max_teammate_count: Optional[int] = None
    wave_ability: Optional[str] = None
    wave_ability_params: tuple[float, ...] = ()
    clear_previous_ability: bool = False
    summon_monsters: Mapping[int, CompiledMonsterSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledStageSpec:
    """Complete compiled stage specification for a given ``StageID``."""

    stage_id: int
    stage_name: str
    stage_type: str
    level: int
    hard_level_group: int
    default_elite_group: int
    hard_level_curve: HardLevelCurveSpec
    is_elite_battle: bool
    stage_infinite_group_id: Optional[int]
    stage_config_data: Mapping[str, str]
    waves: tuple[CompiledWaveSpec, ...]
    battle_events: tuple[CompiledBattleEventSpec, ...]
    summon_monsters: Mapping[int, CompiledMonsterSpec] = field(default_factory=dict)
    stage_affix_abilities: tuple[tuple[str, tuple[float, ...]], ...] = ()
    challenge_mode: str = "Other"
    has_cycle_aha_extra_turn: bool = False

    @property
    def num_waves(self) -> int:
        return len(self.waves)

    def get_summon_monster(self, monster_id: int, wave_index: Optional[int] = None) -> CompiledMonsterSpec:
        """Find a compiled summoned monster scoped to ``wave_index`` if specified."""
        if wave_index is not None:
            wave = self.waves[wave_index]
            if monster_id in wave.summon_monsters:
                return wave.summon_monsters[monster_id]
            for m in wave.summon_monsters.values():
                if m.monster_template_id == monster_id:
                    return m
            raise KeyError(
                f"Summon monster {monster_id} not found in wave {wave_index} of stage {self.stage_id}"
            )
        if monster_id in self.summon_monsters:
            return self.summon_monsters[monster_id]
        for m in self.summon_monsters.values():
            if m.monster_template_id == monster_id:
                return m
        raise KeyError(f"Summon monster {monster_id} not found in stage {self.stage_id}")

    def get_monster(self, monster_id: int, wave_index: Optional[int] = None) -> CompiledMonsterSpec:
        """Find a compiled monster by ``MonsterID`` in waves or summon registry."""
        if wave_index is not None:
            wave = self.waves[wave_index]
            for m in wave.monsters:
                if m.monster_id == monster_id or m.monster_template_id == monster_id:
                    return m
            if monster_id in wave.summon_monsters:
                return wave.summon_monsters[monster_id]
            for m in wave.summon_monsters.values():
                if m.monster_template_id == monster_id:
                    return m
            raise KeyError(f"Monster {monster_id} not found in wave {wave_index} of stage {self.stage_id}")
        for w in self.waves:
            for m in w.monsters:
                if m.monster_id == monster_id or m.monster_template_id == monster_id:
                    return m
        if monster_id in self.summon_monsters:
            return self.summon_monsters[monster_id]
        for m in self.summon_monsters.values():
            if m.monster_template_id == monster_id:
                return m
        raise KeyError(f"Monster {monster_id} not found in stage {self.stage_id}")


class StageDataLoader:
    """Read-only loader and compiler for official HSR stage and monster tables."""

    def __init__(self, tbgd_root: Path | str = DEFAULT_TBGD_ROOT, load_textmap: bool = True) -> None:
        self.tbgd_root = Path(tbgd_root)
        self.excel_root = self.tbgd_root / "ExcelOutput"
        self._load_textmap = load_textmap

        self._stage_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._monster_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._template_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._hard_level_by_key: Optional[dict[tuple[int, int], dict[str, Any]]] = None
        self._elite_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._infinite_elite_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._skill_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._battle_event_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._infinite_group_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._infinite_wave_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._infinite_monster_group_by_id: Optional[dict[int, dict[str, Any]]] = None
        self._textmap: Optional[dict[str, str]] = None
        self._char_config_cache: dict[str, dict[str, Any]] = {}
        self._compiled_monster_cache: dict[tuple[Any, ...], CompiledMonsterSpec] = {}

    def _read_excel_json(self, filename: str) -> list[dict[str, Any]]:
        path = self.excel_root / filename
        key = (os.path.abspath(str(self.tbgd_root)), filename)
        try:
            st = path.stat()
            sig = (int(st.st_mtime_ns), int(st.st_size))
        except OSError:
            sig = None
        if sig is not None:
            cached = _SHARED_EXCEL_CACHE.get(key)
            if cached is not None and cached[0] == sig:
                return cached[1]
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if sig is not None:
            _SHARED_EXCEL_CACHE[key] = (sig, data)
        return data

    def _try_read_excel_json(self, filename: str) -> list[dict[str, Any]]:
        if not (self.excel_root / filename).exists():
            return []
        try:
            rows = self._read_excel_json(filename)
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    @property
    def stages(self) -> dict[int, dict[str, Any]]:
        if self._stage_by_id is None:
            self._stage_by_id = {
                int(row["StageID"]): row for row in self._read_excel_json("StageConfig.json")
            }
        return self._stage_by_id

    @property
    def monsters(self) -> dict[int, dict[str, Any]]:
        if self._monster_by_id is None:
            self._monster_by_id = {
                int(row["MonsterID"]): row for row in self._read_excel_json("MonsterConfig.json")
            }
        return self._monster_by_id

    @property
    def monster_templates(self) -> dict[int, dict[str, Any]]:
        if self._template_by_id is None:
            self._template_by_id = {
                int(row["MonsterTemplateID"]): row
                for row in self._read_excel_json("MonsterTemplateConfig.json")
            }
        return self._template_by_id

    @property
    def hard_level_groups(self) -> dict[tuple[int, int], dict[str, Any]]:
        if self._hard_level_by_key is None:
            self._hard_level_by_key = {
                (int(row["HardLevelGroup"]), int(row["Level"])): row
                for row in self._read_excel_json("HardLevelGroup.json")
            }
        return self._hard_level_by_key

    @property
    def elite_groups(self) -> dict[int, dict[str, Any]]:
        if self._elite_by_id is None:
            self._elite_by_id = {
                int(row["EliteGroup"]): row for row in self._read_excel_json("EliteGroup.json")
            }
        return self._elite_by_id

    @property
    def infinite_elite_groups(self) -> dict[int, dict[str, Any]]:
        if self._infinite_elite_by_id is None:
            path = self.excel_root / "InfiniteEliteGroup.json"
            if path.exists():
                self._infinite_elite_by_id = {
                    int(row["EliteGroup"]): row
                    for row in self._read_excel_json("InfiniteEliteGroup.json")
                }
            else:
                self._infinite_elite_by_id = {}
        return self._infinite_elite_by_id

    @property
    def monster_skills(self) -> dict[int, dict[str, Any]]:
        if self._skill_by_id is None:
            self._skill_by_id = {
                int(row["SkillID"]): row for row in self._read_excel_json("MonsterSkillConfig.json")
            }
        return self._skill_by_id

    @property
    def battle_events(self) -> dict[int, dict[str, Any]]:
        if self._battle_event_by_id is None:
            self._battle_event_by_id = {
                int(row["BattleEventID"]): row
                for row in self._read_excel_json("BattleEventConfig.json")
            }
        return self._battle_event_by_id

    @property
    def infinite_groups(self) -> dict[int, dict[str, Any]]:
        if self._infinite_group_by_id is None:
            path = self.excel_root / "StageInfiniteGroup.json"
            self._infinite_group_by_id = (
                {
                    int(row["WaveGroupID"]): row
                    for row in self._read_excel_json("StageInfiniteGroup.json")
                }
                if path.exists()
                else {}
            )
        return self._infinite_group_by_id

    @property
    def infinite_waves(self) -> dict[int, dict[str, Any]]:
        if self._infinite_wave_by_id is None:
            path = self.excel_root / "StageInfiniteWaveConfig.json"
            self._infinite_wave_by_id = (
                {
                    int(row["InfiniteWaveID"]): row
                    for row in self._read_excel_json("StageInfiniteWaveConfig.json")
                }
                if path.exists()
                else {}
            )
        return self._infinite_wave_by_id

    @property
    def infinite_monster_groups(self) -> dict[int, dict[str, Any]]:
        if self._infinite_monster_group_by_id is None:
            path = self.excel_root / "StageInfiniteMonsterGroup.json"
            self._infinite_monster_group_by_id = (
                {
                    int(row["InfiniteMonsterGroupID"]): row
                    for row in self._read_excel_json("StageInfiniteMonsterGroup.json")
                }
                if path.exists()
                else {}
            )
        return self._infinite_monster_group_by_id

    @property
    def textmap(self) -> dict[str, str]:
        if self._textmap is None:
            if not self._load_textmap:
                self._textmap = {}
            else:
                tm_path = self.tbgd_root / "TextMap" / "TextMapCHS.json"
                if tm_path.exists():
                    root_key = os.path.abspath(str(self.tbgd_root))
                    try:
                        st = tm_path.stat()
                        sig = (int(st.st_mtime_ns), int(st.st_size))
                    except OSError:
                        sig = None
                    if sig is not None:
                        cached = _SHARED_TEXTMAP_CACHE.get(root_key)
                        if cached is not None and cached[0] == sig:
                            self._textmap = cached[1]
                            return self._textmap
                    with tm_path.open("r", encoding="utf-8") as f:
                        self._textmap = json.load(f)
                    if sig is not None and isinstance(self._textmap, dict):
                        _SHARED_TEXTMAP_CACHE[root_key] = (sig, self._textmap)
                else:
                    self._textmap = {}
        return self._textmap

    def resolve_text(self, hash_container: Any) -> str:
        """Resolve a ``{'Hash': ...}`` dictionary against ``TextMapCHS.json``."""
        if isinstance(hash_container, Mapping) and "Hash" in hash_container:
            return self.textmap.get(str(hash_container["Hash"]), "")
        return ""

    def get_hard_level_curve(self, hard_level_group: int, level: int) -> HardLevelCurveSpec:
        """Return the ``HardLevelCurveSpec`` for ``(hard_level_group, level)``."""
        row = self.hard_level_groups.get((int(hard_level_group), int(level)))
        if row is None:
            raise KeyError(f"HardLevelGroup ({hard_level_group}, {level}) not found")
        return HardLevelCurveSpec(
            hard_level_group=int(hard_level_group),
            level=int(level),
            hp_ratio=_unwrap_value(row.get("HPRatio"), 1.0),
            atk_ratio=_unwrap_value(row.get("AttackRatio"), 1.0),
            def_ratio=_unwrap_value(row.get("DefenceRatio"), 1.0),
            speed_ratio=_unwrap_value(row.get("SpeedRatio"), 1.0),
            stance_ratio=_unwrap_value(row.get("StanceRatio"), 1.0),
            status_probability=_unwrap_value(row.get("StatusProbability"), 0.0),
            status_resistance=_unwrap_value(row.get("StatusResistance"), 0.0),
        )

    def get_elite_group(
        self, elite_group_id: Optional[int], prefer_infinite: bool = False
    ) -> EliteGroupSpec:
        """Resolve an ``EliteGroupSpec`` from ``EliteGroup.json`` or ``InfiniteEliteGroup.json``."""
        if not elite_group_id:
            return EliteGroupSpec(elite_group=0)
        eg_id = int(elite_group_id)
        if prefer_infinite and eg_id in self.infinite_elite_groups:
            row = self.infinite_elite_groups[eg_id]
            source = "InfiniteEliteGroup"
        elif eg_id in self.elite_groups:
            row = self.elite_groups[eg_id]
            source = "EliteGroup"
        elif eg_id in self.infinite_elite_groups:
            row = self.infinite_elite_groups[eg_id]
            source = "InfiniteEliteGroup"
        else:
            raise KeyError(f"EliteGroup {eg_id} not found in EliteGroup or InfiniteEliteGroup")
        return EliteGroupSpec(
            elite_group=eg_id,
            hp_ratio=_unwrap_value(row.get("HPRatio"), 1.0),
            atk_ratio=_unwrap_value(row.get("AttackRatio"), 1.0),
            def_ratio=_unwrap_value(row.get("DefenceRatio"), 1.0),
            speed_ratio=_unwrap_value(row.get("SpeedRatio"), 1.0),
            stance_ratio=_unwrap_value(row.get("StanceRatio"), 1.0),
            source_table=source,
        )

    def _load_char_config(self, rel_path: str) -> dict[str, Any]:
        if not rel_path:
            return {}
        if rel_path not in self._char_config_cache:
            full_path = self.tbgd_root / rel_path
            if full_path.exists():
                with full_path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                parent_path = str(raw.get("ParentConfigPath") or "") if isinstance(raw, Mapping) else ""
                if parent_path and parent_path != rel_path:
                    parent_cfg = self._load_char_config(parent_path)
                    merged = dict(parent_cfg)
                    merged.update(raw)
                    self._char_config_cache[rel_path] = merged
                else:
                    self._char_config_cache[rel_path] = raw
            else:
                self._char_config_cache[rel_path] = {}
        return self._char_config_cache[rel_path]

    def _inspect_monster_skill_abilities(
        self, json_config_path: str
    ) -> dict[str, tuple[int, bool, bool, bool]]:
        """从官方 Monster_*_Ability.json 通用提取每个技能的 (hit_count, ability_is_blast, has_mark_target, ability_is_aoe)。"""
        if not json_config_path:
            return {}
        cache = getattr(self, "_monster_ab_skill_meta_cache", None)
        if cache is None:
            cache = {}
            self._monster_ab_skill_meta_cache = cache
        if json_config_path in cache:
            return cache[json_config_path]

        stem = Path(json_config_path).name.replace("_Config.json", "_Ability.json")
        ab_path = self.tbgd_root / "Config" / "ConfigAbility" / "Monster" / stem
        out: dict[str, tuple[int, bool, bool, bool]] = {}
        if not ab_path.exists():
            cache[json_config_path] = out
            return out
        try:
            doc = json.loads(ab_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache[json_config_path] = out
            return out

        import re as _re

        for ab in doc.get("AbilityList", []):
            if not isinstance(ab, Mapping):
                continue
            ab_name = str(ab.get("Name") or "")
            m = _re.search(r"_(Skill\d+)(?:_Phase02)?$", ab_name)
            if not m:
                continue
            sk_key = m.group(1)
            raw_txt = json.dumps(ab, ensure_ascii=False)
            ab_is_blast = ("TargetAdjoinEntity" in raw_txt) or (f"_{sk_key}_Target" in raw_txt and sk_key == "Skill04")
            has_mark = (f"_{sk_key}_Target" in raw_txt and sk_key == "Skill04") or ("Mark" in raw_txt and sk_key == "Skill04")

            hs_fixed: list[float] = []
            hs_dyn_total: list[float] = []
            retarget_max: list[int] = []
            ab_is_aoe = False

            def _contains_damage(sub: Any) -> bool:
                if isinstance(sub, Mapping):
                    if sub.get("$type") == "RPG.GameCore.DamageByAttackProperty":
                        return True
                    return any(_contains_damage(v) for v in sub.values())
                if isinstance(sub, list):
                    return any(_contains_damage(x) for x in sub)
                return False

            def _walk(node: Any) -> None:
                nonlocal ab_is_aoe
                if isinstance(node, Mapping):
                    nt = node.get("$type", "")
                    if nt == "RPG.GameCore.DamageByAttackProperty":
                        ap = node.get("AttackProperty")
                        if isinstance(ap, Mapping):
                            hs = ap.get("HitSplitRatio")
                            if isinstance(hs, Mapping):
                                if not hs.get("IsDynamic", False):
                                    fv = (hs.get("FixedValue") or {}).get("Value")
                                    if isinstance(fv, (int, float)) and 0.0 < float(fv) < 1.0:
                                        hs_fixed.append(float(fv))
                                else:
                                    fvs = (hs.get("PostfixExpr") or {}).get("FixedValues") or []
                                    if fvs and isinstance(fvs[0], Mapping):
                                        v0 = fvs[0].get("Value")
                                        if isinstance(v0, (int, float)) and float(v0) > 1.0:
                                            hs_dyn_total.append(float(v0))
                    elif nt == "RPG.GameCore.Retarget":
                        mn = node.get("MaxNumber")
                        if isinstance(mn, Mapping):
                            mv = (mn.get("FixedValue") or {}).get("Value")
                            if isinstance(mv, (int, float)) and int(mv) > 1:
                                retarget_max.append(int(mv))
                        else:
                            tt = node.get("TargetType")
                            if (
                                isinstance(tt, Mapping)
                                and tt.get("Alias") == "AllEnemy"
                                and _contains_damage(node.get("TaskList"))
                            ):
                                ab_is_aoe = True
                    for v in node.values():
                        _walk(v)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item)

            _walk(ab)
            hit_cnt = 1
            if hs_fixed:
                hit_cnt = max(1, int(round(1.0 / hs_fixed[0])))
            elif hs_dyn_total and retarget_max:
                hit_cnt = max(1, int(round(hs_dyn_total[0] / retarget_max[0])))

            prev = out.get(sk_key)
            if prev is None or hit_cnt > prev[0] or ab_is_blast or has_mark or ab_is_aoe:
                out[sk_key] = (
                    max(hit_cnt, prev[0] if prev else 1),
                    ab_is_blast or (prev[1] if prev else False),
                    has_mark or (prev[2] if prev else False),
                    ab_is_aoe or (prev[3] if prev else False),
                )

        cache[json_config_path] = out
        return out

    def compile_battle_event(
        self,
        battle_event_id: int,
        hard_level_curve: Optional[HardLevelCurveSpec] = None,
    ) -> CompiledBattleEventSpec:
        """Compile a ``BattleEventConfig.json`` entry by ``BattleEventID``."""
        row = self.battle_events.get(int(battle_event_id))
        if row is None:
            raise KeyError(f"BattleEventID {battle_event_id} not found")
        overrides: dict[str, float] = {}
        for item in row.get("OverrideProperty", []):
            ptype = item.get("PropertyType")
            if ptype:
                overrides[str(ptype)] = _unwrap_value(item.get("Value"), 0.0)

        if "Speed" in row:
            base_speed = _unwrap_value(row.get("Speed"), 0.0)
        elif "BaseSpeed" in overrides:
            base_speed = overrides["BaseSpeed"]
        else:
            base_speed = 0.0

        hard_level_flag = bool(row.get("HardLevel", False))
        # Note: BattleEventConfig entries with an explicit top-level Speed (e.g. 30149 Speed=100)
        # or OverrideProperty BaseSpeed (e.g. 20041 BaseSpeed=100 with HardLevel=True) scale
        # BaseSpeed by HardLevelGroup.SpeedRatio when OverrideProperty defines BaseSpeed, while
        # top-level Speed is the fixed stage event speed unless BaseSpeed is overridden.
        if hard_level_flag and hard_level_curve is not None and "BaseSpeed" in overrides:
            effective_speed = base_speed * hard_level_curve.speed_ratio
        else:
            effective_speed = base_speed

        action_value = (10000.0 / effective_speed) if effective_speed > 0 else None
        params = tuple(_unwrap_value(p, 0.0) for p in row.get("ParamList", []))
        return CompiledBattleEventSpec(
            battle_event_id=int(battle_event_id),
            name=str(row.get("BattleEventName", "")),
            team=str(row.get("Team", "")),
            event_sub_type=str(row.get("EventSubType", "")),
            ability_list=tuple(str(a) for a in row.get("AbilityList", [])),
            override_properties=overrides,
            base_speed=base_speed,
            hard_level_scaling=hard_level_flag,
            effective_speed=effective_speed,
            action_value=action_value,
            param_list=params,
            description_key=str(row.get("DescrptionText", "")),
        )

    def _extract_monster_battle_events(
        self,
        char_config: Mapping[str, Any],
        hard_level_curve: HardLevelCurveSpec,
    ) -> tuple[CompiledBattleEventSpec, ...]:
        """Find any BattleEvents preloaded/created by a monster's character ability config."""
        json_path = char_config.get("JsonConfig", "")
        # Look for matching ability file in Config/ConfigAbility/Monster/
        ability_names = [
            str(a) for a in char_config.get("AbilityList", []) if isinstance(a, str)
        ]
        found_be_ids: list[int] = []
        monster_ability_dir = self.tbgd_root / "Config" / "ConfigAbility" / "Monster"
        if json_path and monster_ability_dir.exists():
            stem = Path(json_path).stem
            if stem.endswith("_Config"):
                ability_stem = stem[: -len("_Config")] + "_Ability.json"
                ability_file = monster_ability_dir / ability_stem
                if ability_file.exists():
                    try:
                        with ability_file.open("r", encoding="utf-8") as f:
                            ab_doc = json.load(f)
                    except (OSError, json.JSONDecodeError) as exc:
                        raise RuntimeError(
                            f"Failed to read/parse monster ability file '{ability_file}' "
                            f"referenced by '{json_path}': {exc}"
                        ) from exc
                    for ab in ab_doc.get("AbilityList", []):
                        if ab.get("Name") in ability_names:
                            for task in ab.get("OnStart", []) + ab.get("OnAdd", []):
                                if task.get("$type") == "RPG.GameCore.PreloadBattleEventByID":
                                    for bid in task.get("BattleEventID", []):
                                        if int(bid) not in found_be_ids:
                                            found_be_ids.append(int(bid))
                                elif task.get("$type") == "RPG.GameCore.CreateBattleEvent":
                                    ev = task.get("EventID", {})
                                    bid = _unwrap_value(ev.get("FixedValue"), 0.0)
                                    if bid > 0 and int(bid) not in found_be_ids:
                                        found_be_ids.append(int(bid))

        compiled: list[CompiledBattleEventSpec] = []
        for bid in found_be_ids:
            if bid in self.battle_events:
                compiled.append(self.compile_battle_event(bid, hard_level_curve))
        return tuple(compiled)

    def compile_monster(
        self,
        monster_id: int,
        level: int,
        stage_hard_level_group: Optional[int] = None,
        stage_elite_group: Optional[int] = None,
        prefer_infinite_elite: bool = False,
    ) -> CompiledMonsterSpec:
        """Compile a ``MonsterConfig`` + ``MonsterTemplateConfig`` at a target stage level."""
        cache_key = (
            int(monster_id),
            int(level),
            int(stage_hard_level_group) if stage_hard_level_group is not None else None,
            int(stage_elite_group) if stage_elite_group is not None else None,
            bool(prefer_infinite_elite),
        )
        cached = self._compiled_monster_cache.get(cache_key)
        if cached is not None:
            return cached

        mrow = self.monsters.get(int(monster_id))
        if mrow is None:
            raise KeyError(f"MonsterID {monster_id} not found in MonsterConfig.json")
        template_id = int(mrow["MonsterTemplateID"])
        trow = self.monster_templates.get(template_id)
        if trow is None:
            raise KeyError(
                f"MonsterTemplateID {template_id} not found in MonsterTemplateConfig.json"
            )

        hard_group_id = (
            int(stage_hard_level_group)
            if stage_hard_level_group is not None
            else int(mrow.get("HardLevelGroup", 1))
        )
        curve = self.get_hard_level_curve(hard_group_id, int(level))

        # Combine stage EliteGroup and monster-level EliteGroup if applicable
        monster_eg_id = int(mrow.get("EliteGroup", 1))
        monster_eg = self.get_elite_group(monster_eg_id, prefer_infinite=False)
        if stage_elite_group is not None and int(stage_elite_group) > 0:
            stage_eg = self.get_elite_group(
                int(stage_elite_group), prefer_infinite=prefer_infinite_elite
            )
            effective_eg_id = int(stage_elite_group)
            eg_hp_ratio = stage_eg.hp_ratio * monster_eg.hp_ratio
            eg_atk_ratio = stage_eg.atk_ratio * monster_eg.atk_ratio
            eg_def_ratio = stage_eg.def_ratio * monster_eg.def_ratio
            eg_spd_ratio = stage_eg.speed_ratio * monster_eg.speed_ratio
            eg_stance_ratio = stage_eg.stance_ratio * monster_eg.stance_ratio
        else:
            effective_eg_id = monster_eg_id
            eg_hp_ratio = monster_eg.hp_ratio
            eg_atk_ratio = monster_eg.atk_ratio
            eg_def_ratio = monster_eg.def_ratio
            eg_spd_ratio = monster_eg.speed_ratio
            eg_stance_ratio = monster_eg.stance_ratio

        hp_base = _unwrap_value(trow.get("HPBase"), 0.0)
        atk_base = _unwrap_value(trow.get("AttackBase"), 0.0)
        def_base = _unwrap_value(trow.get("DefenceBase"), 0.0)
        speed_base = _unwrap_value(trow.get("SpeedBase"), 0.0)
        stance_base = _unwrap_value(trow.get("StanceBase"), 0.0)
        crit_damage_base = _unwrap_value(trow.get("CriticalDamageBase"), 0.2)
        status_res_base = _unwrap_value(trow.get("StatusResistanceBase"), 0.0)
        # 官方 Protobuf 导出规范：值为 1.0 的怪物显式写出 {"Value": 1}，省略该字段代表初始行动延迟为 0.0（开局立即行动，如「灯塔」）
        initial_delay_ratio = _unwrap_value(trow.get("InitialDelayRatio"), 0.0)
        initial_distance = 10000.0 * initial_delay_ratio

        hp_mod = _unwrap_value(mrow.get("HPModifyRatio"), 1.0)
        atk_mod = _unwrap_value(mrow.get("AttackModifyRatio"), 1.0)
        def_mod = _unwrap_value(mrow.get("DefenceModifyRatio"), 1.0)
        speed_mod = _unwrap_value(mrow.get("SpeedModifyRatio"), 1.0)
        stance_mod = _unwrap_value(mrow.get("StanceModifyRatio"), 1.0)
        speed_mod_val = _unwrap_value(mrow.get("SpeedModifyValue"), 0.0)
        stance_mod_val = _unwrap_value(mrow.get("StanceModifyValue"), 0.0)

        effective_hp_base = _snap_rational_base(hp_base, hp_mod)
        raw_hp = hp_base * hp_mod * curve.hp_ratio * eg_hp_ratio
        hp = effective_hp_base * curve.hp_ratio * eg_hp_ratio
        atk = atk_base * atk_mod * curve.atk_ratio * eg_atk_ratio
        def_ = def_base * def_mod * curve.def_ratio * eg_def_ratio
        speed = speed_base * speed_mod * curve.speed_ratio * eg_spd_ratio + speed_mod_val
        toughness = stance_base * stance_mod * curve.stance_ratio * eg_stance_ratio + stance_mod_val
        ui_toughness = toughness / 3.0

        status_probability = curve.status_probability
        status_resistance = status_res_base + curve.status_resistance

        weaknesses = tuple(str(w) for w in mrow.get("StanceWeakList", []))
        damage_res: dict[str, float] = {elem: 0.0 for elem in ALL_DAMAGE_TYPES}
        for item in mrow.get("DamageTypeResistance", []):
            dtype = item.get("DamageType")
            if dtype:
                damage_res[str(dtype)] = _unwrap_value(item.get("Value"), 0.0)

        debuff_resist: dict[str, float] = {}
        for item in mrow.get("DebuffResist", []):
            key = item.get("Key")
            if key:
                debuff_resist[str(key)] = _unwrap_value(item.get("Value"), 0.0)

        # Compile skills and apply OverrideSkillParams
        override_map: dict[int, list[float]] = {}
        for ov in mrow.get("OverrideSkillParams", []):
            sid = ov.get("BOKJJKFCFME") or ov.get("SkillID")
            plist = ov.get("PBLPLDJKPEI") or ov.get("ParamList") or []
            if sid is not None:
                override_map[int(sid)] = [_unwrap_value(p, -1.0) for p in plist]

        skills: dict[int, CompiledMonsterSkillSpec] = {}
        # Inspect Character Config JSON for SkillList (TargetInfo), PhaseList and AbilityList
        json_config_path = str(trow.get("JsonConfig", ""))
        char_cfg = self._load_char_config(json_config_path)
        char_cfg_with_path = dict(char_cfg)
        char_cfg_with_path["JsonConfig"] = json_config_path

        blast_trigger_keys: set[str] = set()
        aoe_trigger_keys: set[str] = set()
        for sk_cfg in char_cfg.get("SkillList", []):
            if not isinstance(sk_cfg, Mapping):
                continue
            sk_name = str(sk_cfg.get("Name", ""))
            t_info = sk_cfg.get("TargetInfo")
            if isinstance(t_info, Mapping):
                if t_info.get("SubTargetType") == "TargetAdjoinEntity":
                    blast_trigger_keys.add(sk_name)
                if t_info.get("TargetType") == "AllEnemy":
                    aoe_trigger_keys.add(sk_name)

        ab_skill_meta = self._inspect_monster_skill_abilities(json_config_path)

        skills_by_key: dict[str, CompiledMonsterSkillSpec] = {}
        for sid_raw in mrow.get("SkillList", []):
            sid = int(sid_raw)
            srow = self.monster_skills.get(sid)
            if srow is None:
                continue
            base_params = tuple(_unwrap_value(p, 0.0) for p in srow.get("ParamList", []))
            if sid in override_map:
                ov_vals = override_map[sid]
                eff_list = list(base_params)
                for idx, val in enumerate(ov_vals):
                    if idx < len(eff_list) and val != -1.0:
                        eff_list[idx] = val
                effective_params = tuple(eff_list)
            else:
                effective_params = base_params

            tkey = str(srow.get("SkillTriggerKey", ""))
            ab_hits, ab_blast, ab_mark, ab_aoe = ab_skill_meta.get(tkey, (1, False, False, False))
            is_aoe_sk = (tkey in aoe_trigger_keys) or ab_aoe
            spec = CompiledMonsterSkillSpec(
                skill_id=sid,
                name=self.resolve_text(srow.get("SkillName")),
                trigger_key=tkey,
                skill_type_desc=self.resolve_text(srow.get("SkillTypeDesc")),
                damage_type=srow.get("DamageType"),
                attack_type=srow.get("AttackType"),
                sp_hit_base=_unwrap_value(srow.get("SPHitBase"), 0.0),
                base_params=base_params,
                effective_params=effective_params,
                is_passive=bool(tkey.startswith("Passive")),
                is_blast=(not is_aoe_sk) and ((tkey in blast_trigger_keys) or ab_blast),
                is_aoe=is_aoe_sk,
                hit_count=(ab_hits if not is_aoe_sk else 1),
                has_mark_target=(not is_aoe_sk) and ab_mark,
                delay_ratio=_unwrap_value(srow.get("DelayRatio"), 1.0),
            )
            skills[sid] = spec
            if tkey:
                skills_by_key[tkey] = spec

        dyn_floats: Mapping[str, Any] = (
            char_cfg.get("DynamicValues", {}).get("Floats", {})
            if isinstance(char_cfg.get("DynamicValues"), Mapping)
            else {}
        )
        from simulator.vm.expr import eval_dynamic_float

        def _dyn_resolver(h: int) -> float:
            read_info = dyn_floats.get(str(h), {}).get("ReadInfo", {})
            if read_info.get("Type") == "SkillParam":
                trig_key = str(read_info.get("TriggerKey", ""))
                param_idx = int(read_info.get("Index", 0))
                if trig_key in skills_by_key:
                    return float(skills_by_key[trig_key].param(param_idx, 1.0))
            return 0.0

        def _resolve_phase_ratio(ratio_cfg: Any) -> float:
            if not isinstance(ratio_cfg, Mapping):
                return 1.0
            if not ratio_cfg.get("IsDynamic", False):
                val = _unwrap_value(ratio_cfg.get("FixedValue"), 1.0)
                return float(val) if val > 0.0 else 1.0
            # Note: Phase ratios read dynamic skill parameters via PostfixExpr (base param if override is -1)
            val = eval_dynamic_float(ratio_cfg, _dyn_resolver, 1.0)
            return float(val) if val > 0.0 else 1.0

        phase_list_raw = char_cfg.get("PhaseList", [])
        phases: list[CompiledMonsterPhaseSpec] = []
        if phase_list_raw:
            for p_entry in phase_list_raw:
                pnum = int(p_entry.get("PhaseNum", len(phases) + 1))
                ratio_mult = _resolve_phase_ratio(p_entry.get("PhaseMaxHPRatio"))
                stance_mult = _resolve_phase_ratio(p_entry.get("PhaseStanceRatio"))
                phases.append(
                    CompiledMonsterPhaseSpec(
                        phase_num=pnum,
                        max_hp_multiplier=ratio_mult,
                        max_hp=hp * ratio_mult,
                        raw_max_hp=raw_hp * ratio_mult,
                        stance_multiplier=stance_mult,
                        max_toughness=toughness * stance_mult,
                    )
                )
        else:
            phases.append(
                CompiledMonsterPhaseSpec(
                    phase_num=1,
                    max_hp_multiplier=1.0,
                    max_hp=hp,
                    raw_max_hp=raw_hp,
                    stance_multiplier=1.0,
                    max_toughness=toughness,
                )
            )

        # Summon IDs and initial DynamicValues from MonsterConfig
        custom_values: dict[str, Any] = {}
        for cv in mrow.get("CustomValues", []):
            k = cv.get("BFLIFKBEOPJ")
            v = cv.get("MNDFOPKBHKP")
            if k is not None:
                custom_values[str(k)] = v
        for dv in mrow.get("DynamicValues", []):
            k = dv.get("BFLIFKBEOPJ")
            v = dv.get("MNDFOPKBHKP")
            if k is not None:
                custom_values.setdefault(str(k), _unwrap_value(v, 0.0))

        summon_ids_list: list[int] = []
        for s_id in mrow.get("SummonIDList", []):
            if int(s_id) not in summon_ids_list:
                summon_ids_list.append(int(s_id))
        for k, v in custom_values.items():
            if "SummonID" in k and isinstance(v, int) and v not in summon_ids_list:
                summon_ids_list.append(v)

        ability_list = tuple(
            str(a)
            for a in (
                list(mrow.get("AbilityNameList", []))
                + list(char_cfg.get("AbilityList", []))
            )
            if a
        )
        custom_value_tags = tuple(
            str(t)
            for t in mrow.get("CustomValueTags", [])
            if isinstance(t, str) and t
        )
        monster_bes = self._extract_monster_battle_events(char_cfg_with_path, curve)

        name = self.resolve_text(mrow.get("MonsterName")) or self.resolve_text(
            trow.get("MonsterName")
        )

        spec = CompiledMonsterSpec(
            monster_id=int(monster_id),
            monster_template_id=template_id,
            name=name,
            rank=str(trow.get("Rank", "")),
            level=int(level),
            hard_level_group=hard_group_id,
            elite_group=effective_eg_id,
            hp_base=hp_base,
            atk_base=atk_base,
            def_base=def_base,
            speed_base=speed_base,
            stance_base=stance_base,
            crit_damage_base=crit_damage_base,
            status_resistance_base=status_res_base,
            initial_delay_ratio=initial_delay_ratio,
            initial_distance=initial_distance,
            stance_count=int(trow.get("StanceCount", 1)),
            stance_type=trow.get("StanceType"),
            hp_modify_ratio=hp_mod,
            atk_modify_ratio=atk_mod,
            def_modify_ratio=def_mod,
            speed_modify_ratio=speed_mod,
            stance_modify_ratio=stance_mod,
            hp=hp,
            raw_hp=raw_hp,
            atk=atk,
            def_=def_,
            speed=speed,
            toughness=toughness,
            ui_toughness=ui_toughness,
            status_probability=status_probability,
            status_resistance=status_resistance,
            weaknesses=weaknesses,
            damage_res=damage_res,
            debuff_resist=debuff_resist,
            max_phase=len(phases),
            phases=tuple(phases),
            skills=skills,
            skills_by_key=skills_by_key,
            summon_ids=tuple(summon_ids_list),
            custom_values=custom_values,
            json_config_path=json_config_path,
            ai_path=str(mrow.get("OverrideAIPath") or trow.get("AIPath", "")),
            ability_list=ability_list,
            battle_events=monster_bes,
            custom_value_tags=custom_value_tags,
        )
        self._compiled_monster_cache[cache_key] = spec
        return spec

    def load_stage(self, stage_id: int) -> CompiledStageSpec:
        """Load and compile a complete ``CompiledStageSpec`` by ``StageID``."""
        srow = self.stages.get(int(stage_id))
        if srow is None:
            raise KeyError(f"StageID {stage_id} not found in StageConfig.json")

        level = int(srow.get("Level", 1))
        hard_level_group = int(srow.get("HardLevelGroup", 1))
        default_elite_group = int(srow.get("EliteGroup", 0))
        curve = self.get_hard_level_curve(hard_level_group, level)

        stage_config_data: dict[str, str] = {}
        battle_event_ids: list[int] = []
        stage_infinite_group_id: Optional[int] = None
        for entry in srow.get("StageConfigData", []):
            key = entry.get("BFLIFKBEOPJ")
            val = entry.get("MNDFOPKBHKP", "")
            if key:
                stage_config_data[str(key)] = str(val)
                if key == "_CreateBattleEvent" and val:
                    for part in str(val).split(","):
                        part = part.strip()
                        if part.isdigit():
                            battle_event_ids.append(int(part))
                elif key == "_StageInfiniteGroup" and str(val).strip().isdigit():
                    stage_infinite_group_id = int(str(val).strip())

        is_elite_battle = stage_config_data.get("_IsEliteBattle") == "1"

        waves: list[CompiledWaveSpec] = []
        summon_monsters: dict[int, CompiledMonsterSpec] = {}

        if stage_infinite_group_id is not None and stage_infinite_group_id in self.infinite_groups:
            inf_group = self.infinite_groups[stage_infinite_group_id]
            wave_id_list = [int(wid) for wid in inf_group.get("WaveIDList", [])]
            for w_idx, inf_wave_id in enumerate(wave_id_list):
                inf_wave = self.infinite_waves[inf_wave_id]
                mg_ids = tuple(int(mg) for mg in inf_wave.get("MonsterGroupIDList", []))
                all_m_ids: list[int] = []
                all_compiled: list[CompiledMonsterSpec] = []
                wave_summons: dict[int, CompiledMonsterSpec] = {}
                wave_eg_id = default_elite_group

                for idx_mg, mg_id in enumerate(mg_ids):
                    mg_row = self.infinite_monster_groups[mg_id]
                    mg_eg_id = int(mg_row.get("EliteGroup", default_elite_group))
                    if idx_mg == 0:
                        wave_eg_id = mg_eg_id
                    mg_m_ids = [int(mid) for mid in mg_row.get("MonsterList", [])]
                    all_m_ids.extend(mg_m_ids)
                    mg_compiled = [
                        self.compile_monster(
                            mid,
                            level=level,
                            stage_hard_level_group=hard_level_group,
                            stage_elite_group=mg_eg_id,
                            prefer_infinite_elite=True,
                        )
                        for mid in mg_m_ids
                    ]
                    all_compiled.extend(mg_compiled)
                    for cm in mg_compiled:
                        self._collect_summons(
                            cm,
                            level=level,
                            hard_level_group=hard_level_group,
                            elite_group=mg_eg_id,
                            prefer_infinite_elite=True,
                            registry=wave_summons,
                        )

                for sid, sm in wave_summons.items():
                    if sid not in summon_monsters:
                        summon_monsters[sid] = sm

                wave_ab = str(inf_wave.get("Ability") or "").strip() or None
                wave_ab_params = tuple(
                    _unwrap_value(p, 0.0) for p in (inf_wave.get("ParamList") or ())
                )
                clear_prev_ab = bool(inf_wave.get("ClearPreviousAbility", False))

                waves.append(
                    CompiledWaveSpec(
                        wave_index=w_idx,
                        monster_ids=tuple(all_m_ids),
                        monsters=tuple(all_compiled),
                        elite_group=wave_eg_id,
                        infinite_wave_id=inf_wave_id,
                        infinite_monster_group_id=mg_ids[0] if mg_ids else None,
                        infinite_monster_group_ids=mg_ids,
                        max_monster_count=int(inf_wave.get("MaxMonsterCount", 0)) or None,
                        max_teammate_count=int(inf_wave.get("MaxTeammateCount", 0)) or None,
                        wave_ability=wave_ab,
                        wave_ability_params=wave_ab_params,
                        clear_previous_ability=clear_prev_ab,
                        summon_monsters=wave_summons,
                    )
                )
        else:
            for w_idx, w_dict in enumerate(srow.get("MonsterList", [])):
                sorted_keys = sorted(
                    (k for k in w_dict.keys() if k.startswith("Monster")),
                    key=lambda k: int(k[len("Monster") :]) if k[len("Monster") :].isdigit() else 999,
                )
                m_ids = tuple(int(w_dict[k]) for k in sorted_keys)
                compiled_monsters = tuple(
                    self.compile_monster(
                        mid,
                        level=level,
                        stage_hard_level_group=hard_level_group,
                        stage_elite_group=default_elite_group,
                        prefer_infinite_elite=False,
                    )
                    for mid in m_ids
                )
                wave_summons = {}
                for cm in compiled_monsters:
                    self._collect_summons(
                        cm,
                        level=level,
                        hard_level_group=hard_level_group,
                        elite_group=default_elite_group,
                        prefer_infinite_elite=False,
                        registry=wave_summons,
                    )
                for sid, sm in wave_summons.items():
                    if sid not in summon_monsters:
                        summon_monsters[sid] = sm

                waves.append(
                    CompiledWaveSpec(
                        wave_index=w_idx,
                        monster_ids=m_ids,
                        monsters=compiled_monsters,
                        elite_group=default_elite_group,
                        summon_monsters=wave_summons,
                    )
                )

        # Collect stage-level and monster-level BattleEvents
        compiled_bes: list[CompiledBattleEventSpec] = []
        seen_be_ids: set[int] = set()
        for bid in battle_event_ids:
            if bid in self.battle_events and bid not in seen_be_ids:
                compiled_bes.append(self.compile_battle_event(bid, curve))
                seen_be_ids.add(bid)
        for w in waves:
            for m in w.monsters:
                for be in m.battle_events:
                    if be.battle_event_id not in seen_be_ids:
                        compiled_bes.append(be)
                        seen_be_ids.add(be.battle_event_id)

        stage_affix_abilities = self._load_stage_affix_abilities(int(stage_id))
        challenge_mode = self._detect_challenge_mode(int(stage_id))
        has_cycle_aha_extra_turn = self._detect_cycle_aha_extra_turn(compiled_bes)

        return CompiledStageSpec(
            stage_id=int(stage_id),
            stage_name=self.resolve_text(srow.get("StageName")),
            stage_type=str(srow.get("StageType", "")),
            level=level,
            hard_level_group=hard_level_group,
            default_elite_group=default_elite_group,
            hard_level_curve=curve,
            is_elite_battle=is_elite_battle,
            stage_infinite_group_id=stage_infinite_group_id,
            stage_config_data=stage_config_data,
            waves=tuple(waves),
            battle_events=tuple(compiled_bes),
            summon_monsters=summon_monsters,
            stage_affix_abilities=stage_affix_abilities,
            challenge_mode=challenge_mode,
            has_cycle_aha_extra_turn=has_cycle_aha_extra_turn,
        )

    def _detect_challenge_mode(self, stage_id: int) -> str:
        """根据官方四大深渊配置表精确识别玩法模式：MoC / PF / AS / Peak / Other。"""
        table_specs = (
            ("ChallengeMazeConfig.json", ("EventIDList1", "EventIDList2"), "MoC"),
            ("ChallengeStoryMazeConfig.json", ("EventIDList1", "EventIDList2"), "PF"),
            ("ChallengeStoryMazeTierce.json", ("HFIAAGAKFMD",), "PF"),
            ("ChallengeBossMazeConfig.json", ("EventIDList1", "EventIDList2"), "AS"),
            ("ChallengeBossMazeTierce.json", ("HFIAAGAKFMD",), "AS"),
            ("ChallengePeakConfig.json", ("EventIDList",), "Peak"),
            ("ChallengePeakBossConfig.json", ("EventIDList", "HardEventIDList"), "Peak"),
        )
        for fn, ev_keys, mode in table_specs:
            rows = self._try_read_excel_json(fn)
            if not rows:
                continue
            for row in rows:
                for ek in ev_keys:
                    if stage_id in (row.get(ek) or ()):
                        return mode
        return "Other"

    def _detect_cycle_aha_extra_turn(
        self, battle_events: Sequence[CompiledBattleEventSpec]
    ) -> bool:
        """检查关卡挂载的 BattleEvent 能力配置是否包含欢愉阿哈周期额外回合（Elation_StartElationTime）。"""
        ab_names: set[str] = set()
        for be in battle_events:
            for ab_name in be.ability_list:
                if ab_name:
                    ab_names.add(str(ab_name))
        if not ab_names:
            return False
        ca_dir = self.tbgd_root / "Config" / "ConfigAbility"
        if not ca_dir.exists():
            return False
        for fp in sorted(ca_dir.glob("BattleEventAbility*.json"), key=lambda p: p.as_posix()):
            if fp.name.endswith(".layout.json"):
                continue
            try:
                txt = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "Elation_StartElationTime" not in txt:
                continue
            if not any(ab in txt for ab in ab_names):
                continue
            try:
                data = json.loads(txt)
            except Exception:
                continue
            for ab in data.get("AbilityList") or ():
                if str(ab.get("Name") or "") in ab_names:
                    if "Elation_StartElationTime" in json.dumps(ab, ensure_ascii=False):
                        return True
        return False

    def _load_stage_affix_abilities(
        self, stage_id: int
    ) -> tuple[tuple[str, tuple[float, ...]], ...]:
        """从官方 ChallengePeakConfig / ChallengePeakBossConfig / ChallengeStoryMazeConfig + MazeBuff.json 解析关卡环境词条。"""
        tag_ids: list[int] = []
        for fn, ev_key, tag_key in (
            ("ChallengePeakConfig.json", "EventIDList", "TagList"),
            ("ChallengePeakBossConfig.json", "HardEventIDList", "HardTagList"),
        ):
            for row in self._try_read_excel_json(fn):
                if stage_id in (row.get(ev_key) or ()):
                    for tid in row.get(tag_key) or ():
                        if int(tid) not in tag_ids:
                            tag_ids.append(int(tid))

        for row in self._try_read_excel_json("ChallengeStoryMazeConfig.json"):
            if stage_id in (row.get("EventIDList1") or ()) or stage_id in (row.get("EventIDList2") or ()):
                mb_id = int(row.get("MazeBuffID") or 0)
                if mb_id > 0 and mb_id not in tag_ids:
                    tag_ids.append(mb_id)

        t_rows = self._try_read_excel_json("ChallengeStoryMazeTierce.json")
        g_rows = self._try_read_excel_json("ChallengeStoryGroupConfig.json") if t_rows else []
        if t_rows and g_rows:
            for row in t_rows:
                if stage_id in (row.get("HFIAAGAKFMD") or ()):
                    tierce_id = int(row.get("PHFMCACHFIJ") or 0)
                    if tierce_id > 0:
                        for grow in g_rows:
                            if int(grow.get("TierceID") or 0) == tierce_id:
                                mb_id = int(grow.get("MazeBuffID") or 0)
                                if mb_id > 0 and mb_id not in tag_ids:
                                    tag_ids.append(mb_id)

        boss_rows = self._try_read_excel_json("ChallengeBossMazeConfig.json")
        if boss_rows:
            for row in boss_rows:
                if stage_id in (row.get("EventIDList1") or ()) or stage_id in (row.get("EventIDList2") or ()):
                    mb_id = int(row.get("MazeBuffID") or 0)
                    if mb_id > 0 and mb_id not in tag_ids:
                        tag_ids.append(mb_id)
            bt_rows = self._try_read_excel_json("ChallengeBossMazeTierce.json")
            if bt_rows:
                boss_by_id = {int(r.get("ID") or 0): r for r in boss_rows if r.get("ID")}
                for brow in bt_rows:
                    if stage_id in (brow.get("HFIAAGAKFMD") or ()):
                        parent_id = int(brow.get("DLCKKJFMJOB") or 0)
                        prow = boss_by_id.get(parent_id)
                        if prow is not None:
                            mb_id = int(prow.get("MazeBuffID") or 0)
                            if mb_id > 0 and mb_id not in tag_ids:
                                tag_ids.append(mb_id)

        srow = self.stages.get(int(stage_id))
        if isinstance(srow, Mapping):
            for entry in srow.get("StageConfigData", ()):
                if isinstance(entry, Mapping) and entry.get("BFLIFKBEOPJ") == "_BindingMazeBuff":
                    raw_bm = str(entry.get("MNDFOPKBHKP", "")).strip()
                    if raw_bm.isdigit():
                        bm_id = int(raw_bm)
                        if bm_id > 0 and bm_id not in tag_ids:
                            tag_ids.append(bm_id)

        if not tag_ids:
            return ()
        return self.resolve_maze_buff_abilities(tag_ids)

    def resolve_maze_buff_abilities(
        self, buff_ids: Sequence[int]
    ) -> tuple[tuple[str, tuple[float, ...]], ...]:
        """将任意 MazeBuff ID 列表解析为 (InBattleBindingKey, ParamList) 列表。"""
        if not buff_ids:
            return ()
        mb_rows = self._try_read_excel_json("MazeBuff.json")
        if not mb_rows:
            return ()
        mb_by_id = {int(r.get("ID") or 0): r for r in mb_rows}
        out: list[tuple[str, tuple[float, ...]]] = []
        for tid in buff_ids:
            row = mb_by_id.get(int(tid))
            if not row:
                continue
            ab_key = str(row.get("InBattleBindingKey") or "")
            if not ab_key:
                continue
            params = tuple(
                float(p.get("Value", 0.0)) if isinstance(p, Mapping) else float(p)
                for p in (row.get("ParamList") or ())
            )
            out.append((ab_key, params))
        return tuple(out)

    def resolve_stage_invasion(self, stage_id: int) -> dict[str, Any] | None:
        """从官方 StageInvasionConfig / StageInvasionBuff / StageMonsterInvasionParam 读取关卡贪饕侵蚀配置。"""
        cfg_rows = self._try_read_excel_json("StageInvasionConfig.json")
        if not cfg_rows:
            return None
        matched = None
        for row in cfg_rows:
            if int(row.get("StageID") or 0) == int(stage_id):
                matched = row
                break
        if matched is None:
            return None
        inv_id = int(matched.get("InvasionID") or 0)
        maze_buff_id = 0
        for brow in self._try_read_excel_json("StageInvasionBuff.json"):
            if int(brow.get("InvasionID") or 0) == inv_id:
                maze_buff_id = int(brow.get("MazeBuffID") or 0)
                break
        monster_params: tuple[float, ...] = ()
        for prow in self._try_read_excel_json("StageMonsterInvasionParam.json"):
            if int(prow.get("InvasionID") or 0) == inv_id:
                monster_params = tuple(
                    float(p.get("Value", 0.0)) if isinstance(p, Mapping) else float(p)
                    for p in (prow.get("ParamList") or ())
                )
                break
        monster_rules: dict[int, tuple[int, ...]] = {}
        for item in matched.get("MonsterInvasionList") or ():
            mid = int(item.get("DBLDCKODNEN") or 0)
            pat = tuple(int(x) for x in (item.get("LMEBOHHDIAG") or ()))
            if mid:
                monster_rules[mid] = pat
        return {
            "invasion_id": inv_id,
            "maze_buff_id": maze_buff_id,
            "monster_params": monster_params,
            "monster_rules": monster_rules,
        }

    def _collect_summons(
        self,
        monster: CompiledMonsterSpec,
        level: int,
        hard_level_group: int,
        elite_group: int,
        prefer_infinite_elite: bool,
        registry: dict[int, CompiledMonsterSpec],
    ) -> None:
        cand_sids: list[int] = list(monster.summon_ids)
        for v in monster.custom_values.values():
            if isinstance(v, int) and not isinstance(v, bool) and v in self.monsters and v not in cand_sids:
                cand_sids.append(v)
        for sid in cand_sids:
            if sid not in registry and sid in self.monsters:
                sm = self.compile_monster(
                    sid,
                    level=level,
                    stage_hard_level_group=hard_level_group,
                    stage_elite_group=elite_group,
                    prefer_infinite_elite=prefer_infinite_elite,
                )
                registry[sid] = sm
                self._collect_summons(
                    sm,
                    level=level,
                    hard_level_group=hard_level_group,
                    elite_group=elite_group,
                    prefer_infinite_elite=prefer_infinite_elite,
                    registry=registry,
                )


def load_stage_spec(
    stage_id: int, tbgd_root: Path | str = DEFAULT_TBGD_ROOT
) -> CompiledStageSpec:
    """Convenience function to load a ``CompiledStageSpec`` for ``stage_id``."""
    return StageDataLoader(tbgd_root=tbgd_root).load_stage(stage_id)
