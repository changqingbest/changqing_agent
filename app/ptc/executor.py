from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from app.tools import ToolRegistry


class PTCError(ValueError):
    """PTC 程序不合法或执行失败。"""


@dataclass(slots=True)
class _ExecutionState:
    variables: dict[str, Any] = field(default_factory=dict)
    emitted: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    statements: int = 0


class PTCExecutor:
    """解释受限 Python AST，让模型用代码编排已注册工具。

    这不是通用 Python 沙箱：只支持赋值、表达式、if、for、基础运算、
    容器和注册工具调用；显式拒绝 import、属性访问、函数/类定义等语法。
    """

    TOOL_NAME = "execute_ptc"

    def __init__(self, registry: ToolRegistry, *, max_statements: int = 100) -> None:
        self.registry = registry
        self.max_statements = max_statements
        self.safe_functions = {
            "len": len,
            "sum": sum,
            "min": min,
            "max": max,
            "sorted": sorted,
            "str": str,
            "int": int,
            "float": float,
            "round": round,
            "range": range,
        }

    def definition(self) -> dict[str, Any]:
        names = ", ".join(sorted(self.registry.names()))
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "用一段受限 Python 程序编排多个工具调用。"
                    f"可直接调用：{names}。用 emit(value) 输出最终结果；禁止 import 和属性访问。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "受限 Python 代码，例如 result = get_current_time(); emit(result)",
                        }
                    },
                    "required": ["code"],
                    "additionalProperties": False,
                },
            },
        }

    def execute(self, code: str) -> dict[str, Any]:
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise PTCError(f"PTC 语法错误：{exc.msg}") from exc

        state = _ExecutionState()
        for statement in tree.body:
            self._statement(statement, state)
        return {"output": state.emitted, "tool_calls": state.calls}

    def _tick(self, state: _ExecutionState) -> None:
        state.statements += 1
        if state.statements > self.max_statements:
            raise PTCError(f"PTC 超过最大执行语句数：{self.max_statements}")

    def _statement(self, node: ast.stmt, state: _ExecutionState) -> None:
        self._tick(state)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            state.variables[node.targets[0].id] = self._expression(node.value, state)
            return
        if isinstance(node, ast.Expr):
            self._expression(node.value, state)
            return
        if isinstance(node, ast.If):
            branch = node.body if self._expression(node.test, state) else node.orelse
            for child in branch:
                self._statement(child, state)
            return
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            values = self._expression(node.iter, state)
            for value in values:
                state.variables[node.target.id] = value
                for child in node.body:
                    self._statement(child, state)
            return
        raise PTCError(f"PTC 不允许语句：{type(node).__name__}")

    def _expression(self, node: ast.expr, state: _ExecutionState) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self._expression(item, state)) for item in node.values)
        if isinstance(node, ast.FormattedValue):
            if node.format_spec is not None:
                raise PTCError("PTC f-string 暂不支持格式说明符")
            return self._expression(node.value, state)
        if isinstance(node, ast.Name):
            if node.id in state.variables:
                return state.variables[node.id]
            raise PTCError(f"未知变量：{node.id}")
        if isinstance(node, ast.List):
            return [self._expression(item, state) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._expression(item, state) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {
                self._expression(key, state): self._expression(value, state)
                for key, value in zip(node.keys, node.values, strict=True)
            }
        if isinstance(node, ast.Subscript):
            return self._expression(node.value, state)[self._expression(node.slice, state)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            value = self._expression(node.operand, state)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
            return not value
        if isinstance(node, ast.BinOp):
            left, right = self._expression(node.left, state), self._expression(node.right, state)
            operations = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                          ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
                          ast.Mod: lambda: left % right}
            operation = operations.get(type(node.op))
            if operation:
                return operation()
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = self._expression(node.left, state)
            right = self._expression(node.comparators[0], state)
            comparisons = {ast.Eq: left == right, ast.NotEq: left != right, ast.Lt: left < right,
                           ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right}
            if type(node.ops[0]) in comparisons:
                return comparisons[type(node.ops[0])]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self._call(node, state)
        if isinstance(node, ast.Attribute) or (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ):
            raise PTCError("PTC 不允许 Attribute 属性访问")
        raise PTCError(f"PTC 不允许表达式：{type(node).__name__}")

    def _call(self, node: ast.Call, state: _ExecutionState) -> Any:
        name = node.func.id
        args = [self._expression(item, state) for item in node.args]
        kwargs = {item.arg: self._expression(item.value, state) for item in node.keywords if item.arg}

        if name == "emit":
            if len(args) != 1 or kwargs:
                raise PTCError("emit 只接受一个位置参数")
            state.emitted.append(args[0])
            return args[0]
        if name in self.safe_functions:
            return self.safe_functions[name](*args, **kwargs)
        if name in self.registry.names():
            if args:
                raise PTCError("注册工具只能使用命名参数调用")
            result = self.registry.call(name, kwargs)
            state.calls.append({"name": name, "arguments": kwargs, "result": result})
            return result
        raise PTCError(f"PTC 不允许调用：{name}")
