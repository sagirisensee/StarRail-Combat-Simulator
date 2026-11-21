"""官方 ConfigAbility PostfixExpr 逆波兰表达式求值器与 .NET 32-bit 字符串哈希器。

实证对齐 DimbreathBot/TurnBasedGameData 全量战斗配置：
1. `dotnet_hash(s)` 使用 C#/.NET Core 经典双路 5381 交错哈希算法 (`int32` 有符号返回值)；
2. 支持现代 (`OpCodes[-1] == 17`) 与早期 (`OpCodes[-1] == 10`) 两套字节码：
   - 现代: `0=PushFixed`, `1=PushDynamicHash`, `2=Add`, `3=Sub`, `4=Mul`, `5=Div`,
           `6=Mod`, `7=Eq`, `9=Gt`, `10=Ge`, `11=Lt`, `12=Le`,
           `13=Ternary(cond,t,f)`, `14=Neg`, `16=Call(argc)`, `17=Return`
   - 早期: `0=PushFixed`, `1=PushDynamicHash`, `2=Add`, `3=Sub`, `4=Mul`, `5=Div`,
           `7=Neg`, `9=Call(argc)`, `10=Return`
3. 全部 11 个 `Call` 内置数学函数 (`min, max, clamp, clamp01, floor, ceil, round, abs, pow, int, mod`)
   经 `dotnet_hash` 精确映射，绝无哈希碰撞。
"""
from __future__ import annotations

import base64
from functools import lru_cache
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union


@lru_cache(maxsize=4096)
def dotnet_hash(s: str) -> int:
    """计算官方 DynamicKey / TriggerKey 所用的 32 位有符号 .NET 字符串哈希。"""
    h1 = 5381
    h2 = 5381
    n = len(s)
    i = 0
    while i < n:
        h1 = (((h1 << 5) + h1) ^ ord(s[i])) & 0xFFFFFFFF
        if i + 1 < n:
            h2 = (((h2 << 5) + h2) ^ ord(s[i + 1])) & 0xFFFFFFFF
        i += 2
    val = (h1 + (h2 * 1566083941)) & 0xFFFFFFFF
    return val - 0x100000000 if val >= 0x80000000 else val


def _fn_min(a: float, b: float) -> float:
    return min(a, b)


def _fn_max(a: float, b: float) -> float:
    return max(a, b)


def _fn_clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _fn_clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _fn_floor(x: float) -> float:
    return float(math.floor(x))


def _fn_ceil(x: float) -> float:
    return float(math.ceil(x))


def _fn_round(x: float) -> float:
    return float(round(x))


def _fn_abs(x: float) -> float:
    return abs(x)


def _fn_pow(a: float, b: float) -> float:
    return math.pow(a, b)


def _fn_int(x: float) -> float:
    return float(int(x))


def _fn_mod(a: float, b: float) -> float:
    return (a % b) if b != 0 else 0.0


BUILTIN_FUNCS: Dict[str, Tuple[int, Callable[..., float]]] = {
    "min": (2, _fn_min),
    "max": (2, _fn_max),
    "clamp": (3, _fn_clamp),
    "clamp01": (1, _fn_clamp01),
    "floor": (1, _fn_floor),
    "ceil": (1, _fn_ceil),
    "round": (1, _fn_round),
    "abs": (1, _fn_abs),
    "pow": (2, _fn_pow),
    "int": (1, _fn_int),
    "mod": (2, _fn_mod),
}

BUILTIN_FUNC_HASHES: Dict[int, Tuple[str, int, Callable[..., float]]] = {
    dotnet_hash(name): (name, argc, fn) for name, (argc, fn) in BUILTIN_FUNCS.items()
}


@dataclass(frozen=True)
class _HashRef:
    hash_val: int


@dataclass(frozen=True)
class CompiledPostfixExpr:
    """预解码的 PostfixExpr 字节码对象。"""
    ops: Tuple[int, ...]
    fixed_values: Tuple[float, ...]
    dynamic_hashes: Tuple[int, ...]
    is_legacy: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompiledPostfixExpr":
        raw_b64 = data.get("OpCodes", "")
        ops = tuple(base64.b64decode(raw_b64)) if raw_b64 else ()
        fixed = tuple(
            float(item.get("Value", 0.0)) if isinstance(item, Mapping) else float(item)
            for item in data.get("FixedValues", ())
        )
        hashes = tuple(int(h) for h in data.get("DynamicHashes", ()))
        is_legacy = bool(ops and ops[-1] == 10)
        return cls(ops=ops, fixed_values=fixed, dynamic_hashes=hashes, is_legacy=is_legacy)


HashResolver = Union[Mapping[int, float], Callable[[int], float]]


def _resolve_num(val: Union[float, _HashRef], resolver: HashResolver) -> float:
    if isinstance(val, _HashRef):
        if callable(resolver):
            return float(resolver(val.hash_val))
        return float(resolver.get(val.hash_val, 0.0))
    return float(val)


def eval_compiled_expr(expr: CompiledPostfixExpr, resolver: HashResolver) -> float:
    """执行预编译的 PostfixExpr 字节码。"""
    ops = expr.ops
    if not ops:
        return 0.0

    fixed = expr.fixed_values
    hashes = expr.dynamic_hashes
    legacy = expr.is_legacy
    stack: list[Union[float, _HashRef]] = []
    n = len(ops)
    i = 0

    while i < n:
        op = ops[i]
        if op == 0:
            idx = ops[i + 1]
            stack.append(fixed[idx] if idx < len(fixed) else 0.0)
            i += 2
        elif op == 1:
            idx = ops[i + 1]
            stack.append(_HashRef(hashes[idx]) if idx < len(hashes) else 0.0)
            i += 2
        elif op == 2:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(a + b)
            i += 1
        elif op == 3:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(a - b)
            i += 1
        elif op == 4:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(a * b)
            i += 1
        elif op == 5:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(a / b if b != 0.0 else 0.0)
            i += 1
        elif legacy and op == 7:
            a = _resolve_num(stack.pop(), resolver)
            stack.append(-a)
            i += 1
        elif legacy and op == 9:
            argc = ops[i + 1]
            args = [_resolve_num(stack.pop(), resolver) for _ in range(argc)][::-1]
            fn_ref = stack.pop()
            if not isinstance(fn_ref, _HashRef) or fn_ref.hash_val not in BUILTIN_FUNC_HASHES:
                raise KeyError(f"未知 PostfixExpr 内置函数哈希: {fn_ref}")
            _, expected_argc, fn = BUILTIN_FUNC_HASHES[fn_ref.hash_val]
            if len(args) != expected_argc:
                raise ValueError(f"PostfixExpr 函数参数数量不匹配: got {len(args)}, expected {expected_argc}")
            stack.append(float(fn(*args)))
            i += 2
        elif legacy and op == 10:
            break
        elif not legacy and op == 6:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append((a % b) if b != 0.0 else 0.0)
            i += 1
        elif not legacy and op == 7:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(1.0 if abs(a - b) < 1e-9 else 0.0)
            i += 1
        elif not legacy and op == 9:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(1.0 if a > b else 0.0)
            i += 1
        elif not legacy and op == 10:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(1.0 if a >= b else 0.0)
            i += 1
        elif not legacy and op == 11:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(1.0 if a < b else 0.0)
            i += 1
        elif not legacy and op == 12:
            b = _resolve_num(stack.pop(), resolver)
            a = _resolve_num(stack.pop(), resolver)
            stack.append(1.0 if a <= b else 0.0)
            i += 1
        elif not legacy and op == 13:
            false_val = _resolve_num(stack.pop(), resolver)
            true_val = _resolve_num(stack.pop(), resolver)
            cond_val = _resolve_num(stack.pop(), resolver)
            stack.append(true_val if abs(cond_val) > 1e-9 else false_val)
            i += 1
        elif not legacy and op == 14:
            a = _resolve_num(stack.pop(), resolver)
            stack.append(-a)
            i += 1
        elif not legacy and op == 16:
            argc = ops[i + 1]
            args = [_resolve_num(stack.pop(), resolver) for _ in range(argc)][::-1]
            fn_ref = stack.pop()
            if not isinstance(fn_ref, _HashRef) or fn_ref.hash_val not in BUILTIN_FUNC_HASHES:
                raise KeyError(f"未知 PostfixExpr 内置函数哈希: {fn_ref}")
            _, expected_argc, fn = BUILTIN_FUNC_HASHES[fn_ref.hash_val]
            if len(args) != expected_argc:
                raise ValueError(f"PostfixExpr 函数参数数量不匹配: got {len(args)}, expected {expected_argc}")
            stack.append(float(fn(*args)))
            i += 2
        elif not legacy and op == 17:
            break
        else:
            raise ValueError(f"不支持的 PostfixExpr OpCode: {op} (legacy={legacy}, ops={ops})")

    if not stack:
        return 0.0
    return _resolve_num(stack[-1], resolver)


_POSTFIX_EXPR_CACHE: Dict[int, Tuple[Mapping[str, Any], CompiledPostfixExpr]] = {}


def eval_postfix_expr(data: Mapping[str, Any], resolver: HashResolver) -> float:
    """直接对原始 PostfixExpr 字典求值（带 O(1) 预解码字节码缓存）。"""
    key = id(data)
    cached = _POSTFIX_EXPR_CACHE.get(key)
    if cached is not None and cached[0] is data:
        compiled = cached[1]
    else:
        compiled = CompiledPostfixExpr.from_dict(data)
        if len(_POSTFIX_EXPR_CACHE) >= 4096:
            _POSTFIX_EXPR_CACHE.clear()
        _POSTFIX_EXPR_CACHE[key] = (data, compiled)
    return eval_compiled_expr(compiled, resolver)


def eval_dynamic_float(spec: Any, resolver: HashResolver, default: float = 0.0) -> float:
    """求值官方 DynamicFloat / FixedValue / PostfixExpr / 裸数值。"""
    if spec is None:
        return default
    if isinstance(spec, (int, float)):
        return float(spec)
    if not isinstance(spec, Mapping):
        return default
    if "PostfixExpr" in spec and (spec.get("IsDynamic", True) or "FixedValue" not in spec):
        return eval_postfix_expr(spec["PostfixExpr"], resolver)
    if "FixedValue" in spec:
        fv = spec["FixedValue"]
        if isinstance(fv, Mapping):
            return float(fv.get("Value", default))
        return float(fv)
    if "Value" in spec:
        return float(spec["Value"])
    return default
