---
name: golden-log-to-stage
description: >-
  Generate clean, decoupled Enemy Kits, Stage definitions, Log-specific RNG Plugins,
  and Alignment Tests (< 0.2% total damage error) directly from an official HSR
  battle_logs/battle_*.jsonl log in one workflow.
---

# Golden Log to Stage, Enemy Kits & Log Plugin

Use this skill whenever onboarding a new official battle log (`battle_logs/battle_*.jsonl`) into `simulator/` so that **Enemy Kits**, **Stage**, **Generic Replay Framework (`golden_diff.py`)**, and **Log-Specific RNG Plugins (`simulator/plugins/`)** stay strictly separated.

---

## Architecture Boundaries (Mandatory)

1. **Enemy Kits (`simulator/kits/enemies/*.py`)**
   - Model **only** deterministic enemy mechanics: opening action delay, turn phase rotation, summons, marks/debuffs, and attack parameters (`multiplier`, `hits`, `element`, `hit_energy`, `blast`).
   - Query targets solely through `self.port.get_living_allies()`.
   - **Forbidden**: Any ally character names, player UIDs, log-specific AVs, or hardcoded hit outcomes.

2. **Stage File (`simulator/stage_<stage_id>.py`)**
   - Define **only** stage-level facts: enemy roster, base HP/ATK/DEF/SPD/Toughness/RES, `sim.enemy_uid_map` (for Wave 1 starting enemies that do not emit `OnInitializeEnemy`), summon formation ordering & old-summon cleanup, stage buffs/rules (e.g. Elation laugh-point gain, cycle Aha extra-turn rule), and generic adapter hooks (`sim.blast_target_provider`, `sim.aha_special_handler`, `sim.enemy_windwalk_provider`, `sim.enemy_attack_skip_provider`, `apply_aha_hp_damage`, `apply_aha_ally_chip_hit`, `flush_ally_talent_heals`).
   - Resolve `blast=True` generically via `sim.blast_target_provider` or `port.is_own_memosprite` / living formation adjacency.
   - **Forbidden**: Any ally character names or battle-specific random hit lists/values.

3. **Generic Replay Framework (`simulator/golden_diff.py`)**
   - Provides generic JSONL parsing, dynamic `KNOWN_AVATAR_NAMES` (loaded from `data/character_db_export.json`), dynamic `_sim_player_actors(sim)`, `sim.enemy_uid_map` target-UID resolution, boss-pre-turn ready-ult priority, `attach_exact_crit_oracle(sim, log_path=..., non_crits=...)`, and `run_trajectory_replay(...)`.
   - **Forbidden**: Hardcoding `PLAYER_ACTORS`, stage-specific enemy UIDs (`is_<stage_id>`), per-log `NON_CRITS` tables, or `if "<log_id>" in str(log_path)` branches.

4. **Log-Specific RNG Plugin (`simulator/plugins/log_<tag>.py` + `simulator/plugins/non_crit_ledgers.py`)**
   - Encapsulates **all** RNG outcomes of a single battle log:
     - Random non-crit `(act_idx, hit_idx)` tuples in `simulator/plugins/non_crit_ledgers.py`;
     - Random bounce / Aha hit target sequences & special turn events (`attach_log_<tag>_plugin(sim)` setting `sim.aha_special_handler`, `sim.target_provider`, `sim.blast_target_provider`, `sim.enemy_windwalk_provider`, `sim.enemy_attack_skip_provider`).

---

## One-Step Generation Workflow

### Step 1: Extract Ground-Truth Facts from JSONL
Inspect `battle_logs/battle_<tag>.jsonl`:
- **Roster & Stats**: `OnInitializeEnemy` / initial `OnStatChange` for enemy `uid`, `MaxHP`, `Speed`, `ActionDelay`, elemental `Resistance`.
- **Enemy Skill Behavior**: Pair each `OnTurnBegin` (`turn_owner.team == "Enemy"`) with player `CurrentHP` drops (`damage`, `hits`, single vs blast vs AoE, energy gained on `CurrentSP`) and mark/summon events.
  - Derive enemy skill multipliers directly from `observed_damage / base_1x_damage_on_target` (verified against `DEF` and `RES`), never guess.
- **Stage / Environmental Events**: Check `OnTurnBegin` with `turn_owner: null` or non-player/non-enemy `OnDamage` (e.g. Aha turns, cycle rules, Break events `"type": "Break"`).
- **RNG Ledger**: Extract non-crit `(act_idx, hit_idx)` pairs (where observed damage is `~1/(1 + CRIT_DMG)` of crit damage) and exact random bounce targets.

### Step 2: Implement / Reuse Enemy Kits (`simulator/kits/enemies/`)
- Create or update `simulator/kits/enemies/<enemy>.py` subclassing `EnemyKit`.
- Wire `on_battle_start`, `execute_turn`, and `on_event` (e.g. clearing marks when summons die).
- Export in `simulator/kits/enemies/__init__.py`.

### Step 3: Implement Stage Builder (`simulator/stage_<stage_id>.py`)
- Build enemies with exact stage HP/SPD/Toughness/RES/ATK and attach their `EnemyKit` via `BaseEnemyCombatPort` / stage port.
- Implement `Stage<id>Director` with stage-wide buffs/rules and generic `aha_special_handler` hook delegation in `_on_turn_begin` and `after_step`.

### Step 4: Implement Log Plugin (`simulator/plugins/log_<tag>.py`)
- Add `attach_log_<tag>_plugin(sim)` in `simulator/plugins/log_<tag>.py` for **all** log-specific RNG hit sequences:
  - `sim.aha_special_handler`: Aha / environmental random bounce damage & ally chip hits;
    - **Distribute `apply_aha_ally_chip_hit` across actual distinct allies** (e.g. `风堇`, `知更鸟•晴歌`, `晴空乐手`) rather than dumping all hits onto one character. Dumping all chip hits onto one target causes `IkaKit._resolve_talent_heal()` to batch them into a single heal instead of healing each damaged ally, drifting `acc_heal` / `Servant` damage.
  - `sim.target_provider(attacker, living, hit_idx)` & `sim.blast_target_provider(attacker, primary, living)`: exact enemy single-target / bounce / blast targets observed in the log's `OnStatChange` (`CurrentHP`) drops (crucial for healers/tanks like Hyacine whose damage scales with ally healing pools).
  - **Do not omit memosprites/summons in AoE or mark detonations**: Official logs (`OnStatChange`) only emit `CurrentHP` for character UIDs, not memosprites/summons (`小伊卡`, `晴空乐手`). When scripting enemy AoE or `trigger_oronyx_detonation`, still include living memosprites/summons per the enemy kit, and temporarily set `sim.target_provider = None` around explicit detonation calls so `target_provider` does not redirect them to a character.
  - **Never call `sim.resolver.resolve_all()` inside a `TurnBeginEvent` plugin listener**: `attach_log_<tag>_plugin(sim)` is attached *before* `run_trajectory_replay(...)`, so plugin `TurnBeginEvent` listeners run *before* `ReplayRecorder._on_turn_begin`. Calling `resolve_all()` there emits `DamageAppliedEvent` before `ReplayRecorder` opens the new `TurnRecord`, bucketing enemy-turn DoTs into the *previous* turn. Only call `sim.resolver.enqueue(...)`; `core.py`'s `run_stage_turn_begin` calls `resolve_all()` immediately after `TurnBeginEvent` finishes publishing.
- Add `OFFICIAL_<tag>_NON_CRITS` in `simulator/plugins/non_crit_ledgers.py` (or `set()` if 100% crit).

### Step 5: Create Alignment Test (`simulator/test_<stage_id>_alignment.py`) & Verify
1. Build team from `CharacterDB`, call `build_stage_<stage_id>(...)`.
   - If a character's relics changed between logs, store historical snapshots in `data/character_db_export.json` (e.g. `缇宝_旧` placed before `缇宝`) so older logs load their exact historical build while the default name always points to the latest build.
2. Attach:
   - `attach_exact_crit_oracle(sim, log_path=log_path, non_crits=...)`
   - `attach_log_<tag>_plugin(sim)` (if applicable)
   - `run_trajectory_replay(sim, director, extract_timeline(log_path), av_budget=g.final_av, log_path=log_path)`
   - Note: if the battle log ends right after a final `OnUseSkill` with 0 `OnDamage` before `OnBattleEnd`, exclude that truncated final `TimelineItem` so the replay matches the logged damage boundary.
3. Assert:
   - `turn_matched == turn_total`, `ult_matched == ult_total`
   - `sp_granted == 0`, `memoria_granted == 0.0`, `presence_grants == 0`
   - `err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"] < 0.002` (`< 0.2%`)
   - **Per-turn `< 0.2%` assertion**: Compare `g.turns` vs `traj.replay.sequence.turns` grouped by `round(t.av, 2)` for every player/ally turn (`< 0.002`), ensuring no hidden turn-level error cancellation.
4. Run targeted pytest (avoid bare `pytest` so `scratch/` is not collected):
   ```powershell
   pytest simulator/test_<stage_id>_alignment.py simulator/test_stage_<stage_id>_enemies.py -q
   ```
5. Also inspect per-turn and per-hit errors; report any remaining > 0.2% sub-type hits transparently without hardcoding workarounds.
