# coding: utf-8
"""Lv.95 关卡 30126122 敌方基准数值常量（仅供 VM stage 单元测试校验数据驱动加载精度）。"""

from typing import List

STAGE_ID: int = 30126122
MAX_WAVES: int = 2
ENEMY_LV95_BASE_ATK: float = 625.5117

EAGLE_HP: float = 680857.7125462855
EAGLE_SPEED: float = 132.0
EAGLE_TOUGHNESS: float = 90.0
EAGLE_WEAKNESSES: List[str] = ["Wind", "Quantum", "Imaginary"]

PEGASUS_HP: float = EAGLE_HP * 16.0 / 3.0
PEGASUS_SPEED: float = 132.0
PEGASUS_TOUGHNESS: float = 480.0
PEGASUS_WEAKNESSES: List[str] = ["Fire", "Quantum", "Imaginary"]

GRIFFIN_HP: float = EAGLE_HP * 6.0
GRIFFIN_SPEED: float = 158.4
GRIFFIN_INITIAL_DISTANCE: float = 5000.0
GRIFFIN_TOUGHNESS: float = 480.0
GRIFFIN_WEAKNESSES: List[str] = ["Physical", "Quantum", "Imaginary"]

APOLI_PHASE1_HP: float = 5106432.844098277
APOLI_PHASE2_HP: float = 10212865.688196555
APOLI_PHASE1_BARRIER_RATIO: float = 0.65
APOLI_PHASE2_BARRIER_RATIO: float = 0.65
APOLI_BASE_SPEED: float = 237.60000005364418
APOLI_TOUGHNESS: float = 1080.0
APOLI_WEAKNESSES: List[str] = ["Ice", "Quantum", "Imaginary"]

SPROUT_HP: float = EAGLE_HP * 2.0
SPROUT_SPEED: float = 186.24000003933907
SPROUT_TOUGHNESS: float = 120.0
SPROUT_WEAKNESSES: List[str] = ["Fire", "Wind", "Imaginary"]
SPROUT_INTERVAL_SPEED: float = 132.0
