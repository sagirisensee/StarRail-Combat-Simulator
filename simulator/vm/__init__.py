"""官方 ConfigAbility 数据驱动运行时虚拟机 (Official ConfigAbility VM)。"""
from .expr import (
    BUILTIN_FUNCS,
    BUILTIN_FUNC_HASHES,
    CompiledPostfixExpr,
    dotnet_hash,
    eval_compiled_expr,
    eval_dynamic_float,
    eval_postfix_expr,
)
from .loader import (
    CompiledCharacterSpec,
    DEFAULT_TBGD_ROOT,
    GameDataLoader,
    PRUNABLE_PRESENTATION_TYPES,
    prune_ability,
    prune_modifier_dict,
    prune_task_list,
)
from .modifier_engine import ModifierEngine, VMModifierInstance
from .executor import TaskExecutor
from .runtime import (
    ConfigAbilityKitAdapter,
    ConfigAbilityLightConeAdapter,
    ConfigAbilityRelicAdapter,
    VMRuntime,
    ensure_vm_runtime,
)
from .target_alias import ExecutionContext, resolve_target_alias, resolve_target_type

__all__ = [
    "BUILTIN_FUNCS",
    "BUILTIN_FUNC_HASHES",
    "CompiledCharacterSpec",
    "CompiledPostfixExpr",
    "ConfigAbilityKitAdapter",
    "ConfigAbilityLightConeAdapter",
    "ConfigAbilityRelicAdapter",
    "DEFAULT_TBGD_ROOT",
    "ExecutionContext",
    "GameDataLoader",
    "ModifierEngine",
    "PRUNABLE_PRESENTATION_TYPES",
    "TaskExecutor",
    "VMModifierInstance",
    "VMRuntime",
    "dotnet_hash",
    "ensure_vm_runtime",
    "eval_compiled_expr",
    "eval_dynamic_float",
    "eval_postfix_expr",
    "prune_ability",
    "prune_modifier_dict",
    "prune_task_list",
    "resolve_target_alias",
    "resolve_target_type",
]
