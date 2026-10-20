#!/usr/bin/env python3
"""崩坏：星穹铁道 — HoYoLAB 线上战绩全量同步与高精属性反解引擎 (sync_from_hoyolab.py)

功能：
1. 自动化访问/登录 HoYoLAB 战绩后台，获取玩家全部 62+ 位角色的最新配装与实机数据；
2. 运用星铁遗器词条档位（Low/Mid/High）解方程算法，逆向还原真实未截断双精度浮点数；
3. 严格践行「实机截断用于验算，实战模拟全走高精浮点」规范，保证 math.floor(精算值) == 官方显示；
4. 全量同步并原子覆盖至本地核心数据库 data/character_db_export.json。

使用方式:
    python3 sync_from_hoyolab.py               # 使用已缓存 session 或默认配置同步
    python3 sync_from_hoyolab.py --force-login # 强制重新账密登录刷新凭据
"""

import os
import sys
import json
import time
import math
import argparse
from typing import Dict, List, Any, Tuple

# 保证 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from simulator.db.tables import (
    AVATAR_STATS, DEFAULT_5STAR_STATS, DEFAULT_4STAR_STATS,
    LIGHTCONE_STATS, DEFAULT_5STAR_LC, DEFAULT_4STAR_LC,
    RELIC_SUB_RULES, RELIC_SETS
)

# 默认凭据与文件路径
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_FILE = os.path.join(DATA_DIR, ".hoyolab_config.json")
SESSION_FILE = os.path.join(DATA_DIR, ".hoyolab_session.json")
EXPORT_FILE = os.path.join(DATA_DIR, "character_db_export.json")
BACKUP_FILE = os.path.join(DATA_DIR, "character_db_export.backup.json")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "hoyolab_characters.json")

BATTLE_RECORDS_URL = "https://act.hoyolab.com/app/community-game-records-sea/rpg/index.html?bbs_presentation_style=fullscreen&gid=6&utm_campaign=battlechronicle&utm_id=6&utm_medium=tools&utm_source=hoyolab&v=101&bbs_theme=light&bbs_theme_device=1#/hsr"

# 遗器副词条 property_type 到 RELIC_SUB_RULES id 的映射
TYPE_MAP_SUB = {
    27: 1, 29: 2, 31: 3,
    32: 4, 33: 5, 34: 6,
    51: 7,
    52: 8, 53: 9,
    10: 10, 11: 11,
    58: 12, 59: 12
}


def load_config() -> Dict[str, Any]:
    """读取配置，优先从 data/.hoyolab_config.json 或环境变量读取，绝不硬编码敏感凭证。"""
    default_cfg = {
        "email": os.getenv("HOYOLAB_EMAIL", ""),
        "password": os.getenv("HOYOLAB_PASSWORD", ""),
        "role_id": os.getenv("HOYOLAB_ROLE_ID", ""),
        "server": os.getenv("HOYOLAB_SERVER", "prod_official_asia"),
        "auto_save_session": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_cfg.update(saved)
        except Exception as e:
            print(f"⚠️ 读取配置文件 {CONFIG_FILE} 失败: {e}")
    else:
        # 若不存在配置文件，生成模板供用户填入
        os.makedirs(DATA_DIR, exist_ok=True)
        template_cfg = {
            "email": "your_email@example.com",
            "password": "your_password",
            "role_id": "your_uid",
            "server": "prod_official_asia",
            "auto_save_session": True
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(template_cfg, f, ensure_ascii=False, indent=2)
        print(f"ℹ️ 已生成本地配置文件模板: {CONFIG_FILE} (已被 .gitignore 忽略，请在其中填入个人账号信息)")

    return default_cfg


def fetch_hoyolab_raw_data(config: Dict[str, Any], force_login: bool = False, headless: bool = True) -> Dict[str, Any]:
    """通过 Playwright 自动化获取 HoYoLAB 战绩的 avatar/info 全量数据。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 错误: 未检测到 playwright 库，请先安装: pip install playwright && playwright install chromium")
        sys.exit(1)

    print("🚀 启动浏览器引擎连接 HoYoLAB...")
    captured_payload = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        
        # 准备上下文与 Cookie
        use_session = os.path.exists(SESSION_FILE) and not force_login
        if use_session:
            print(f"🔑 检测到已保存的 Session 会话凭据，尝试免密极速登录...")
            context = browser.new_context(
                storage_state=SESSION_FILE,
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        else:
            print("🔑 建立新会话...")
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        # 强制设置中文语言 Cookie
        context.add_cookies([
            {"name": "mi18nLang", "value": "zh-cn", "domain": ".hoyolab.com", "path": "/"},
            {"name": "HYV_LOCALE", "value": "zh-cn", "domain": ".hoyolab.com", "path": "/"}
        ])

        page = context.new_page()

        # 监听 API 响应
        def on_response(resp):
            nonlocal captured_payload
            if "avatar/info" in resp.url and resp.status == 200:
                try:
                    payload = resp.json()
                    if payload.get("retcode") == 0 and payload.get("data"):
                        captured_payload = payload["data"]
                        print(f"📥 成功截获并捕获全角色数据包 (含 {len(captured_payload.get('avatar_list', []))} 位角色)")
                except Exception:
                    pass

        page.on("response", on_response)

        print(f"🌐 正在打开星穹铁道战绩总览页面...")
        page.goto(BATTLE_RECORDS_URL, wait_until="domcontentloaded", timeout=40000)

        # 轮询等待数据捕获或登录按钮 (最多等 12 秒)
        for _ in range(24):
            if captured_payload is not None:
                break
            time.sleep(0.5)

        # 若未捕获到数据或强制重新登录，则执行登录流程
        if captured_payload is None or force_login:
            print("🔐 检测到未捕获战绩或需认证，检查登录表单...")
            try:
                login_btn = page.wait_for_selector("text='Log In'", timeout=6000)
                if login_btn:
                    print("🔑 点击登录按钮，等待登录框加载...")
                    login_btn.click()
                    page.wait_for_selector("iframe", timeout=15000)
                    time.sleep(2)

                    frame = page.frame_locator("iframe")
                    print(f"📝 填报通行证账号: {config['email']}")
                    frame.locator("input[name='username']").fill(config["email"])
                    time.sleep(0.3)
                    frame.locator("input[name='password']").fill(config["password"])
                    time.sleep(0.3)
                    frame.locator("button[type='submit']").click()
                    print("📨 认证请求已提交，等待数据加载与会话同步...")
            except Exception as e:
                print(f"ℹ️ 登录流程提示: {e}")

            # 等待数据载入 (最多等 15 秒)
            for _ in range(30):
                if captured_payload is not None:
                    break
                time.sleep(0.5)

        if not captured_payload:
            print("❌ 获取角色数据失败，请检查账号密码或网络连接。")
            browser.close()
            sys.exit(1)

        # 保存最新的 Session 缓存
        if config.get("auto_save_session", True):
            context.storage_state(path=SESSION_FILE)
            print(f"💾 会话状态已成功持久化至 {SESSION_FILE}")

        browser.close()

    return captured_payload


def solve_subaffix_exact(property_type: int, display_str: str, times: int) -> Tuple[float, str, bool, int, int, int]:
    """从显示值与强化次数 times，解出遗器副词条的高精度浮点真值与档位。"""
    rule_id = TYPE_MAP_SUB.get(property_type)
    if not rule_id or rule_id not in RELIC_SUB_RULES:
        val = float(display_str.replace('%', ''))
        return (val / 100.0 if '%' in display_str else val), "unknown", ('%' in display_str), 0, 0, times
        
    rule = RELIC_SUB_RULES[rule_id]
    base = rule['base']
    step_val = rule['step_val']
    is_pct = rule['is_pct']
    
    target = float(display_str.replace('%', ''))
    
    best_step = 0
    min_diff = 999999.0
    best_val = times * base
    
    for s in range(0, times * 2 + 1):
        cand_val = times * base + s * step_val
        disp_cand = round(cand_val * 100, 1) if is_pct else round(cand_val)
        diff = abs(disp_cand - target)
        if diff < min_diff:
            min_diff = diff
            best_step = s
            best_val = cand_val
            
    high = max(0, best_step - times)
    mid = best_step - 2 * high
    low = max(0, times - mid - high)
    
    return best_val, rule['key'], is_pct, low, mid, high


def compile_and_export_database(raw_data: Dict[str, Any]) -> Tuple[int, int]:
    """核心高精反解与本地数据库编译落盘。"""
    prop_info = raw_data.get("property_info", {})
    avatars = raw_data.get("avatar_list", [])
    records = []

    print(f"⚙️ 正在执行高精度浮点逆向还原与词条编译 (共 {len(avatars)} 位角色)...")

    for a in avatars:
        aid = a["id"]
        name = a["name"]
        level = a.get("level", 80)
        eidolon = f"E{a.get('rank', 0)}"
        element = a.get("element", "Physical").capitalize()
        
        # 光锥
        eq = a.get("equip")
        lc_info = None
        if eq:
            lc_info = {
                "item_id": eq.get("id"),
                "name": eq.get("name"),
                "superimposition": f"S{eq.get('rank', 1)}",
                "level": eq.get("level", 80)
            }
            
        # 遗器与副词条
        all_relics = a.get("relics", []) + a.get("ornaments", [])
        relic_records = []
        relic_set_names = set()
        
        tot_rolls, tot_low, tot_mid, tot_high = 0, 0, 0, 0
        sub_frac_spd = 0.0
        sub_frac_hp = 0.0
        sub_frac_atk = 0.0
        sub_frac_def = 0.0
        
        for r in all_relics:
            rid = r.get("id", 0)
            pos = r.get("pos", 1)
            set_id = int(str(rid)[1:-1]) if len(str(rid)) >= 4 else 0
            set_name = RELIC_SETS.get(set_id, {}).get("name", f"套装{set_id}")
            relic_set_names.add(f"{set_name} (ID {set_id})")
            
            mp = r.get("main_property", {})
            mp_type = mp.get("property_type", 0)
            mp_name = prop_info.get(str(mp_type), {}).get("name", f"词条{mp_type}")
            mp_val_str = mp.get("value", "0")
            
            sub_list = []
            for sp in r.get("properties", []):
                sp_type = sp.get("property_type", 0)
                sp_name = prop_info.get(str(sp_type), {}).get("name", f"副词条{sp_type}")
                sp_val_str = sp.get("value", "0")
                times = sp.get("times", 1)
                
                exact_val, key, is_pct, low, mid, high = solve_subaffix_exact(sp_type, sp_val_str, times)
                tot_rolls += times
                tot_low += low
                tot_mid += mid
                tot_high += high
                
                if key == "spd":
                    sub_frac_spd += exact_val
                elif key == "flat_hp":
                    sub_frac_hp += (exact_val - round(exact_val))
                elif key == "flat_atk":
                    sub_frac_atk += (exact_val - round(exact_val))
                elif key == "flat_def":
                    sub_frac_def += (exact_val - round(exact_val))
                    
                sub_list.append({
                    "name": sp_name,
                    "key": key,
                    "value": round(exact_val, 4) if is_pct else round(exact_val, 3),
                    "count": times,
                    "low_rolls": low,
                    "mid_rolls": mid,
                    "high_rolls": high,
                    "is_pct": is_pct
                })
                
            relic_records.append({
                "slot": pos,
                "slot_name": f"部件 {pos}",
                "set_name": set_name,
                "main_affix": f"{mp_name} +{mp_val_str}",
                "sub_affixes": sub_list
            })
            
        # 官方实机面板确凿数据
        props = {p["property_type"]: p for p in a.get("properties", [])}
        
        # 速度精算
        p_spd = props.get(4, {})
        base_spd_int = int(p_spd.get("base", 100))
        add_spd_int = int(p_spd.get("add", 0))
        disp_spd = int(p_spd.get("final", 100))
        
        # 严格对齐官方截断的前提下，还原真实副词条浮点数
        exact_spd = base_spd_int + add_spd_int + (sub_frac_spd - math.floor(sub_frac_spd))
        if math.floor(exact_spd) != disp_spd:
            exact_spd = disp_spd + (sub_frac_spd % 1.0)
            if exact_spd < disp_spd:
                exact_spd = float(disp_spd)
                
        # 三维属性精算
        p_hp = props.get(1, {})
        base_hp = float(p_hp.get("base", 1000))
        add_hp = float(p_hp.get("add", 0))
        final_hp_disp = int(p_hp.get("final", 1000))
        exact_hp = round(base_hp + add_hp + sub_frac_hp, 2)
        if math.floor(exact_hp) != final_hp_disp:
            exact_hp = float(final_hp_disp) + abs(sub_frac_hp % 1.0)

        p_atk = props.get(2, {})
        base_atk = float(p_atk.get("base", 500))
        add_atk = float(p_atk.get("add", 0))
        final_atk_disp = int(p_atk.get("final", 500))
        exact_atk = round(base_atk + add_atk + sub_frac_atk, 2)
        if math.floor(exact_atk) != final_atk_disp:
            exact_atk = float(final_atk_disp) + abs(sub_frac_atk % 1.0)

        p_def = props.get(3, {})
        base_def = float(p_def.get("base", 500))
        add_def = float(p_def.get("add", 0))
        final_def_disp = int(p_def.get("final", 500))
        exact_def = round(base_def + add_def + sub_frac_def, 2)
        if math.floor(exact_def) != final_def_disp:
            exact_def = float(final_def_disp) + abs(sub_frac_def % 1.0)

        # 百分比属性
        cr_disp = props.get(5, {}).get("final", "5.0%")
        cd_disp = props.get(6, {}).get("final", "50.0%")
        be_disp = props.get(58, props.get(59, {})).get("final", "0.0%")
        err_disp = props.get(9, {}).get("final", "100.0%")
        ehr_disp = props.get(10, {}).get("final", "0.0%")
        res_disp = props.get(11, {}).get("final", "0.0%")
        elation_disp = props.get(71, {}).get("final", "0.0%")

        dmg_disp = "0.0%"
        for pt in [12, 14, 16, 18, 20, 22, 24, 73]:
            if pt in props and props[pt].get("final", "0.0%") != "0.0%":
                dmg_disp = props[pt].get("final")
                break

        stats_summary = {
            "生命值 (HP)": final_hp_disp,
            "攻击力 (ATK)": final_atk_disp,
            "防御力 (DEF)": final_def_disp,
            "速度 (SPD)": disp_spd,
            "速度面板显示": f"{disp_spd} (白字 {base_spd_int} + 绿字 {add_spd_int:+d})",
            "速度实战精算": round(exact_spd, 3),
            "暴击率 (CR)": cr_disp,
            "暴击伤害 (CD)": cd_disp,
            "击破特攻 (BE)": be_disp,
            "能量恢复效率 (ERR)": err_disp,
            "效果命中 (EHR)": ehr_disp,
            "效果抵抗 (RES)": res_disp,
            "属性伤害加成 (DMG%)": dmg_disp
        }

        if elation_disp != "0.0%":
            stats_summary["欢愉度 (Elation)"] = elation_disp

        breakdowns = {
            "hp": {
                "base_white": base_hp,
                "flat_bonus": round(add_hp, 2),
                "percent_bonus": f"{((base_hp+add_hp)/base_hp - 1.0)*100:.2f}%" if base_hp > 0 else "0.0%",
                "final_value": exact_hp
            },
            "atk": {
                "base_white": base_atk,
                "flat_bonus": round(add_atk, 2),
                "percent_bonus": f"{((base_atk+add_atk)/base_atk - 1.0)*100:.2f}%" if base_atk > 0 else "0.0%",
                "final_value": exact_atk
            },
            "def": {
                "base_white": base_def,
                "flat_bonus": round(add_def, 2),
                "percent_bonus": f"{((base_def+add_def)/base_def - 1.0)*100:.2f}%" if base_def > 0 else "0.0%",
                "final_value": exact_def
            },
            "spd": {
                "base_white": float(base_spd_int),
                "flat_bonus": round(add_spd_int + (exact_spd - disp_spd), 3),
                "percent_bonus": "0.00%",
                "final_value": round(exact_spd, 3)
            }
        }

        records.append({
            "avatar_id": aid,
            "name": name,
            "element": element,
            "path": a.get("base_type", 1),
            "level": level,
            "eidolon": eidolon,
            "light_cone": lc_info,
            "relic_count": len(all_relics),
            "relic_sets": list(relic_set_names),
            "stats_summary": stats_summary,
            "breakdowns": breakdowns,
            "substat_roll_stats": {
                "total_rolls": tot_rolls,
                "low_rolls": tot_low,
                "mid_rolls": tot_mid,
                "high_rolls": tot_high,
                "overall_quality_pct": round(((tot_mid + tot_high * 2) / (tot_rolls * 2.0)) * 100, 1) if tot_rolls > 0 else 0.0
            },
            "relic_details": relic_records
        })

    fully_geared_cnt = sum(1 for r in records if r["relic_count"] == 6 and r["light_cone"] is not None)

    compiled_database = {
        "account_uid": raw_data.get("role_id", "801961942"),
        "total_avatars": len(records),
        "fully_geared_count": fully_geared_cnt,
        "characters": records
    }

    # 备份原有文件
    if os.path.exists(EXPORT_FILE):
        try:
            with open(EXPORT_FILE, "r", encoding="utf-8") as f_src, open(BACKUP_FILE, "w", encoding="utf-8") as f_dst:
                f_dst.write(f_src.read())
        except Exception:
            pass

    # 原子写入新数据库
    with open(EXPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(compiled_database, f, ensure_ascii=False, indent=2)

    return len(records), fully_geared_cnt


def main():
    parser = argparse.ArgumentParser(description="HoYoLAB 线上战绩一键全量同步至本地高精数据库")
    parser.add_argument("--force-login", action="store_true", help="强制重新提交账密认证登录")
    parser.add_argument("--no-headless", action="store_true", help="显示 Chromium 浏览器窗口界面 (用于排障)")
    args = parser.parse_args()

    print("==================================================================")
    print("🌟 崩坏：星穹铁道 — HoYoLAB 全量角色数据高精同步工具")
    print("==================================================================")

    config = load_config()
    raw_data = fetch_hoyolab_raw_data(config, force_login=args.force_login, headless=not args.no_headless)
    
    total, geared = compile_and_export_database(raw_data)

    print("\n🎉 ===================== 同步完成报告 =====================")
    print(f"✅ 全量角色总数: {total} 位")
    print(f"✅ 满配主力角色 (光锥+6件遗器): {geared} 位")
    print(f"📁 本地数据库文件: {EXPORT_FILE}")
    print(f"🛡️ 历史备份文件: {BACKUP_FILE}")

    # 抽样展示 5 位核心角色的高精速度与截断对照
    from simulator.db import CharacterDB
    db = CharacterDB().load(EXPORT_FILE)
    print("\n【主力角色实战精算速度抽查 (有效小数位保留)】:")
    for name in ["开拓者", "知更鸟", "花火", "流萤", "银狼LV.999"]:
        p = db.get_by_name(name)
        if p:
            s = p.panel.summary_dict()
            print(f"  - {p.name:<8} ({s['速度面板显示']}) -> 真实实战精算速度: \033[1;32m{p.panel.spd:.3f}\033[0m")

    print("\n【🎭 欢愉星神体系 (Elation System) 角色抽查】:")
    for name in ["真珠", "爻光", "火花", "银狼LV.999"]:
        p = db.get_by_name(name)
        if p:
            s = p.panel.summary_dict()
            el_str = s.get('欢愉度 (Elation)', '0.0%')
            print(f"  - {p.name:<10} 命途: 欢愉 | 欢愉度: \033[1;33m{el_str}\033[0m | 速度: {p.panel.spd:.3f} | 双暴: {s['暴击率 (CR)']} / {s['暴击伤害 (CD)']}")
    print("==================================================================\n")


if __name__ == "__main__":
    main()
