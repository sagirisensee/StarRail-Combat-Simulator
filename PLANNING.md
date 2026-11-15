[规划] 性能瓶颈分析与 Vertex Stream Idle Timeout 修复方案

### 1. 深度分析与现象假设
“Vertex stream idle timeout” 通常出现在模拟器处理复杂的 Action Value (AV) 推演时，如果某个 Action 或状态结算逻辑陷入了过长的计算过程，导致底层的事件调度器 (Vertex Stream) 无法及时收到心跳或完成当前 Tick 的更新。

针对本次环境，初步假设：
- **死循环/高复杂度结算**：`robin_sunnysong.py` 或 `fengjin.py` 中的 Buff/Effect 结算逻辑可能在某些特殊条件下（例如触发条件嵌套）陷入了高复杂度的循环计算。
- **调度冲突**：`simulator/stage_30510021.py` 关联的 stage 机制可能与角色技能逻辑触发了频繁的状态同步，造成了结算性能瓶颈。
- **同步/异步阻塞**：`combat_port.py` 的数据处理可能存在同步等待耗时长的过程。

### 2. 实施方案 (Implementation Plan)
1. **源码审查 (Code Review)**：
   - 重点检查 `simulator/entity.py` 的状态更新逻辑。
   - 分析 `simulator/combat_port.py` 是否有长时间阻塞操作。
   - 深入 `simulator/kits/characters/robin_sunnysong.py` 和 `fengjin.py` 寻找是否存在递归触发、复杂的死循环逻辑。
2. **性能审计 (Profiling)**：
   - 通过 `tracer.py` 或自定义时间戳，审计 `stage_30510021.py` 中每个行动步骤的耗时。
   - 识别出触发超时前的最后一个 Action 类型和状态。
3. **重现与测试**：
   - 使用现有的测试脚本（如 `test_robin_sunnysong_mechanics.py`）进行压力测试。
   - 修改模拟器配置，减小模拟步长或限制最大迭代深度，观察超时是否缓解。
4. **修复与优化**：
   - 如果发现死循环，引入最大循环/递归计数限制。
   - 将复杂的 Buff 结算逻辑进行缓存优化，避免每 Tick 重复计算。
   - 优化 `combat_port.py` 的处理流程，减少不必要的状态序列化。

### 3. 风险及对策
- **风险**：核心逻辑修改可能引入逻辑错误。
- **对策**：必须配合已有的自动化测试套件（尤其是 `test_golden_diff` 和各类 mechanics 测试）进行全链路对账，确保输出结果与之前的黄金数据保持一致。
