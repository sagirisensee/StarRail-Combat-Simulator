"""Veritas 战斗日志实时录制器 (Veritas Battle Flight Recorder).

连接 127.0.0.1:1305 (Veritas 服务端)，将每一场战斗的底层数据包完整落盘为 JSONL，
供模拟器进行 100% 精确的真值回放与对账 (Golden Trace & Replay Diff)。
"""

import os
import sys
import time
import json
from datetime import datetime
import socketio

import functools
print = functools.partial(print, flush=True)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VERITAS_URL = "http://127.0.0.1:1305"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "battle_logs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

sio = socketio.Client()

current_file = None
current_fp = None
event_count = 0
in_battle = False


def log_event(event_name: str, data: any):
    global current_fp, event_count, current_file, in_battle
    event_count += 1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    entry = {
        "index": event_count,
        "time": now_str,
        "event": event_name,
        "data": data
    }

    # 如果有激活的战斗日志文件，写入 JSONL
    if current_fp:
        current_fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        current_fp.flush()

    # 终端美化打印
    if event_name == "OnBattleBegin":
        print(f"\n[{now_str}] ⚔️ 【战斗开始 (OnBattleBegin)】")
    elif event_name == "OnSetBattleLineup":
        avatars = data.get("avatars", []) if isinstance(data, dict) else []
        names = [a.get("name", str(a.get("id"))) for a in avatars]
        print(f"[{now_str}] 👥 【出战阵容】: {', '.join(names)}")
    elif event_name == "OnTurnBegin":
        turn_num = data.get("turn_count", "?") if isinstance(data, dict) else "?"
        actor = data.get("character_name") or data.get("actor_name") or data.get("id") or "?"
        print(f"[{now_str}] ⏳ 【回合开始 (Turn #{turn_num})】: 行动者 -> {actor}")
    elif event_name == "OnUseSkill":
        skill_id = data.get("skill_id", "?") if isinstance(data, dict) else "?"
        caster = data.get("caster_name") or data.get("id") or "?"
        print(f"[{now_str}] 🎯 【施放技能】: {caster} 释放技能 ID {skill_id}")
    elif event_name == "OnDamage":
        attacker = data.get("attacker_name") or data.get("attacker_id") or "?"
        target = data.get("target_name") or data.get("target_id") or "?"
        dmg = data.get("damage", 0)
        is_crit = data.get("is_crit", False)
        crit_str = "💥 [暴击]" if is_crit else "  [命中]"
        print(f"[{now_str}] {crit_str} {attacker} ➔ {target}: {dmg:,.0f} 伤害 (类型: {data.get('damage_type', '-')})")
    elif event_name == "OnStatChange":
        entity = data.get("name") or data.get("id") or "?"
        stat = data.get("stat_type", "?")
        val = data.get("value", 0)
        print(f"[{now_str}] 📊 【属性变动】: {entity} {stat} -> {val}")
    elif event_name == "OnBattleEnd":
        print(f"[{now_str}] 🏁 【战斗结束 (OnBattleEnd)】\n")
    else:
        print(f"[{now_str}] ℹ️  [{event_name}]: {json.dumps(data, ensure_ascii=False)[:120]}")


@sio.event
def connect():
    print("=" * 70)
    print("🟢 成功连接至 Veritas 游戏服务端 (127.0.0.1:1305)")
    print("📡 正在实时监听星铁战斗事件总线...")
    print("=" * 70)


@sio.event
def disconnect():
    global current_fp
    print("\n🔴 与 Veritas 服务端断开连接")
    if current_fp:
        current_fp.close()
        current_fp = None


@sio.on("Connected")
def on_connected(data):
    version = data.get("version", "?") if isinstance(data, dict) else data
    print(f"📦 Veritas 握手成功，插件版本: {version}")


@sio.on("OnBattleBegin")
def on_battle_begin(data):
    global current_fp, current_file, event_count, in_battle
    in_battle = True
    event_count = 0
    filename = f"battle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    current_file = os.path.join(OUTPUT_DIR, filename)
    current_fp = open(current_file, "w", encoding="utf-8")
    print(f"\n📂 已创建战斗日志录制文件: {current_file}")
    log_event("OnBattleBegin", data)


@sio.on("OnSetBattleLineup")
def on_lineup(data):
    log_event("OnSetBattleLineup", data)


@sio.on("OnTurnBegin")
def on_turn_begin(data):
    log_event("OnTurnBegin", data)


@sio.on("OnUseSkill")
def on_use_skill(data):
    log_event("OnUseSkill", data)


@sio.on("OnDamage")
def on_damage(data):
    log_event("OnDamage", data)


@sio.on("OnStatChange")
def on_stat_change(data):
    log_event("OnStatChange", data)


@sio.on("OnUpdateWave")
def on_wave(data):
    log_event("OnUpdateWave", data)


@sio.on("OnUpdateCycle")
def on_cycle(data):
    log_event("OnUpdateCycle", data)


@sio.on("OnInitializeEnemy")
def on_enemy_init(data):
    log_event("OnInitializeEnemy", data)


@sio.on("OnEntityDefeated")
def on_entity_defeated(data):
    log_event("OnEntityDefeated", data)


@sio.on("OnBattleEnd")
def on_battle_end(data):
    global current_fp, current_file, in_battle
    log_event("OnBattleEnd", data)
    in_battle = False
    if current_fp:
        current_fp.close()
        print(f"✅ 战斗录制完成，已完整保存至: {current_file} (共 {event_count} 条事件)")
        current_fp = None


def main():
    try:
        sio.connect(VERITAS_URL, wait_timeout=5)
        print("💡 录制器已进入待命状态。请进入星铁开启任意战斗（末日、混沌、历战余响等）...")
        print("👉 按 Ctrl+C 可随时停止录制。\n")
        sio.wait()
    except KeyboardInterrupt:
        print("\n🛑 用户手动停止录制。")
    except Exception as e:
        print(f"\n❌ 连接异常: {e}")
    finally:
        if current_fp:
            current_fp.close()


if __name__ == "__main__":
    main()
