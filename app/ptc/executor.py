from __future__ import annotations

import ast
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.tools import ToolRegistry
from app.logging_config import log_event


logger = logging.getLogger(__name__)


# 本文件实现 PTC（Programmatic Tool Calling）最小执行层。
# 核心思想：模型提交一段“像 Python”的程序来组合多个工具，但框架不直接 exec()；
# 而是先解析成 AST，再由下面的解释器逐个处理允许的节点，从结构上阻断任意代码执行。

# PTC 专用异常。继承 ValueError 表示“模型提供的程序或参数不符合约束”，
# Agent Loop 会把错误作为工具结果返回模型，让模型有机会自行修正，而不是让服务崩溃。
class PTCError(ValueError):
    """PTC 程序不合法或执行失败。"""


# 单次 PTC 执行期间的可变状态，不会跨请求或跨会话共享。
# slots=True 限制只能使用下列字段，避免解释器代码因拼写错误悄悄创建新属性。
@dataclass(slots=True)
class _ExecutionState:
    # 模型程序中的局部变量表，例如执行 x = 1 后保存 {"x": 1}。
    variables: dict[str, Any] = field(default_factory=dict)
    # emit(value) 明确输出的结果列表；只有这里的内容被视为程序最终产物。
    emitted: list[Any] = field(default_factory=list)
    # 已执行工具的审计记录，包含名称、参数和结果，便于模型及上层观察执行过程。
    calls: list[dict[str, Any]] = field(default_factory=list)
    # 已解释语句计数，用于限制循环和程序规模，防止模型生成超长执行路径。
    statements: int = 0


# PTCExecutor 是“受限语法解释器”，不是完整 Python 运行时，也不是强隔离沙箱。
# 它只认识本类显式处理的 AST 节点；任何未列入白名单的语法都会抛 PTCError。
class PTCExecutor:
    """解释受限 Python AST，让模型用代码编排已注册工具。

    这不是通用 Python 沙箱：只支持赋值、表达式、if、for、基础运算、
    容器和注册工具调用；显式拒绝 import、属性访问、函数/类定义等语法。
    """

    # 暴露给模型的特殊工具名。Agent Loop 用它区分普通工具调用与 PTC 程序执行。
    TOOL_NAME = "execute_ptc"

    # registry：PTC 程序唯一允许访问的业务工具目录。
    # max_statements：单次执行最多解释的语句数量，循环体每执行一次也会计数。
    # 副作用：只保存引用和安全函数白名单，不执行模型代码或业务工具。
    def __init__(self, registry: ToolRegistry, *, max_statements: int = 100) -> None:
        # 与 Agent Loop 共用同一个 Registry，避免普通调用和 PTC 调用的工具集合不一致。
        self.registry = registry
        # 这是资源保护上限，不是超时；耗时工具还需要在更外层增加独立超时控制。
        self.max_statements = max_statements
        # 允许模型使用的少量纯函数。这里保存真实函数对象，但只能通过名字白名单进入。
        # 故意不提供 open、eval、exec、getattr、__import__ 等高风险能力。
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

    # 作用：生成 execute_ptc 的 OpenAI function tool 定义。
    # 返回：只包含名称、说明和 code 字段 Schema 的字典，不暴露解释器内部对象。
    # 业务意图：让模型知道可用工具名和输出约定，从而生成可被本解释器接受的程序。
    def definition(self) -> dict[str, Any]:
        # 排序让提示内容稳定，便于调试和测试；这里只列出当前注册工具。
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

    # 作用：解析并执行一段受限 PTC 代码。
    # code：模型生成的 Python 风格源代码字符串。
    # 返回：output 是 emit 收集结果，tool_calls 是本次真实工具调用审计记录。
    # 异常：语法错误或不在白名单内的节点统一抛 PTCError。
    def execute(self, code: str) -> dict[str, Any]:
        started = time.perf_counter()
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:12]
        log_event(
            logger,
            logging.INFO,
            "ptc.execution.started",
            "PTC 程序开始执行",
            code_chars=len(code),
            code_hash=code_hash,
            max_statements=self.max_statements,
        )
        try:
            # ast.parse 只把文本转换为语法树，本身不会执行代码，这是安全边界的第一步。
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            # 保留异常链，日志调试时仍可找到原始 SyntaxError 位置。
            log_event(
                logger,
                logging.WARNING,
                "ptc.execution.rejected",
                "PTC 程序语法解析失败",
                code_chars=len(code),
                code_hash=code_hash,
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise PTCError(f"PTC 语法错误：{exc.msg}") from exc

        # 每次调用创建全新状态，防止一个用户的变量或结果泄漏到另一个请求。
        state = _ExecutionState()
        # 顶层语句按模型生成的原顺序执行，行为与普通顺序程序一致。
        try:
            for statement in tree.body:
                self._statement(statement, state)
        except Exception as exc:
            expected_error = isinstance(exc, PTCError)
            log_event(
                logger,
                logging.WARNING if expected_error else logging.ERROR,
                "ptc.execution.failed",
                "PTC 程序执行失败",
                exc_info=not expected_error,
                code_hash=code_hash,
                error_type=type(exc).__name__,
                statements=state.statements,
                tool_call_count=len(state.calls),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        # 即使模型没有 emit，也返回结构完整的空 output，方便 Agent 判断和修正。
        result = {"output": state.emitted, "tool_calls": state.calls}
        log_event(
            logger,
            logging.INFO,
            "ptc.execution.completed",
            "PTC 程序执行完成",
            code_hash=code_hash,
            statements=state.statements,
            tool_call_count=len(state.calls),
            emitted_count=len(state.emitted),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return result

    # 作用：为每个实际执行的语句计数，并在超过预算时立即终止。
    # state：当前单次执行状态；返回值：无。
    # 风险边界：它能限制 for 循环体执行次数，但不能替代真实的进程级 CPU/时间隔离。
    def _tick(self, state: _ExecutionState) -> None:
        state.statements += 1
        if state.statements > self.max_statements:
            raise PTCError(f"PTC 超过最大执行语句数：{self.max_statements}")

    # 作用：解释一个“语句级”AST 节点。
    # node：赋值、表达式、if 或 for 等候选语句；state：变量和审计状态。
    # 返回值：无；赋值、emit 和工具调用通过 state 体现副作用。
    # 默认策略：只实现明确允许的类型，其余一律拒绝，而不是猜测执行。
    def _statement(self, node: ast.stmt, state: _ExecutionState) -> None:
        # 所有允许语句在执行前都消耗一次预算，包括循环体中的每次实际执行。
        self._tick(state)
        # 只允许“单一普通变量赋值”，拒绝属性赋值、下标赋值和 a=b=1 链式赋值。
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            state.variables[node.targets[0].id] = self._expression(node.value, state)
            return
        # 表达式语句主要用于 emit(...) 或不接收返回值的工具调用。
        if isinstance(node, ast.Expr):
            self._expression(node.value, state)
            return
        # if 只解释实际命中的分支；未命中的分支不消耗语句预算，也不会产生副作用。
        if isinstance(node, ast.If):
            branch = node.body if self._expression(node.test, state) else node.orelse
            for child in branch:
                self._statement(child, state)
            return
        # for 仅允许单个变量作为循环目标；迭代数据必须由白名单表达式产生。
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            values = self._expression(node.iter, state)
            # 每轮先更新循环变量，再按顺序解释循环体；_tick 会限制总执行规模。
            for value in values:
                state.variables[node.target.id] = value
                for child in node.body:
                    self._statement(child, state)
            return
        # import、while、try、with、函数/类定义、删除和增强赋值等都会落到这里。
        raise PTCError(f"PTC 不允许语句：{type(node).__name__}")

    # 作用：递归求值一个“表达式级”AST 节点，并返回普通 Python 值。
    # node：当前表达式；state：用于读取变量、记录 emit 和工具调用。
    # 安全原则：不调用 compile/exec，只针对每种允许节点手写求值规则。
    def _expression(self, node: ast.expr, state: _ExecutionState) -> Any:
        # 字符串、数字、布尔值和 None 等字面量可直接返回。
        if isinstance(node, ast.Constant):
            return node.value
        # JoinedStr 是 f-string 的整体节点；逐片段求值并拼成最终字符串。
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self._expression(item, state)) for item in node.values)
        # FormattedValue 是 f"{value}" 中花括号部分；只支持最基础的字符串转换。
        if isinstance(node, ast.FormattedValue):
            # 格式说明符可能引入额外复杂行为，基础版本明确拒绝而非不完整模拟。
            if node.format_spec is not None:
                raise PTCError("PTC f-string 暂不支持格式说明符")
            return self._expression(node.value, state)
        # 名称只能从本次执行的变量表读取，不能访问 Python 全局变量或内置命名空间。
        if isinstance(node, ast.Name):
            if node.id in state.variables:
                return state.variables[node.id]
            raise PTCError(f"未知变量：{node.id}")
        # 容器元素继续递归走同一白名单，因此容器本身不会绕过表达式限制。
        if isinstance(node, ast.List):
            return [self._expression(item, state) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._expression(item, state) for item in node.elts)
        if isinstance(node, ast.Dict):
            # strict=True 确保键和值数量异常时立即报错，而不是静默丢失数据。
            return {
                self._expression(key, state): self._expression(value, state)
                for key, value in zip(node.keys, node.values, strict=True)
            }
        # 允许 result["value"] 读取工具结果；不允许 result.get(...)，因为属性访问被禁用。
        if isinstance(node, ast.Subscript):
            return self._expression(node.value, state)[self._expression(node.slice, state)]
        # 仅开放数值正负号和逻辑 not，其余位运算等一元操作不会进入此分支。
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            value = self._expression(node.operand, state)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
            return not value
        # 二元运算先递归求左右值，再按运算符类型从白名单分发。
        if isinstance(node, ast.BinOp):
            left, right = self._expression(node.left, state), self._expression(node.right, state)
            # lambda 延迟真正运算，只有匹配到允许运算符时才执行对应表达式。
            operations = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                          ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
                          ast.Mod: lambda: left % right}
            operation = operations.get(type(node.op))
            if operation:
                return operation()
        # 基础版本只支持一次二元比较，例如 x > 3；不支持 1 < x < 10 链式比较。
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = self._expression(node.left, state)
            right = self._expression(node.comparators[0], state)
            comparisons = {ast.Eq: left == right, ast.NotEq: left != right, ast.Lt: left < right,
                           ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right}
            if type(node.ops[0]) in comparisons:
                return comparisons[type(node.ops[0])]
        # 函数调用必须是直接名称形式，例如 emit(x)；具体名称再由 _call 做白名单判断。
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self._call(node, state)
        # obj.method() 和 obj.attr 都属于 Attribute，显式给出易懂的安全错误。
        if isinstance(node, ast.Attribute) or (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ):
            raise PTCError("PTC 不允许 Attribute 属性访问")
        # 列表推导式、lambda、await、yield、集合等未实现节点默认拒绝。
        raise PTCError(f"PTC 不允许表达式：{type(node).__name__}")

    # 作用：执行已通过“直接名称调用”检查的 ast.Call。
    # node：函数名及参数语法树；state：用于输出和记录工具审计。
    # 返回：emit 的值、安全函数结果或注册工具结果。
    def _call(self, node: ast.Call, state: _ExecutionState) -> Any:
        # 到达这里时 func 已由 _expression 确认为 ast.Name，因此 id 可安全读取。
        name = node.func.id
        # 所有实参仍递归走表达式白名单，参数中不能夹带任意代码。
        args = [self._expression(item, state) for item in node.args]
        kwargs = {item.arg: self._expression(item.value, state) for item in node.keywords if item.arg}

        # emit 是 PTC 协议保留函数，不属于业务工具；它只收集一个明确的最终输出值。
        if name == "emit":
            if len(args) != 1 or kwargs:
                raise PTCError("emit 只接受一个位置参数")
            state.emitted.append(args[0])
            return args[0]
        # 安全内置函数允许位置参数和命名参数，实际类型错误会自然向上抛出。
        if name in self.safe_functions:
            return self.safe_functions[name](*args, **kwargs)
        # 注册工具是 PTC 访问外部能力的唯一通道。
        if name in self.registry.names():
            # 强制命名参数能让模型代码与工具 Schema 字段一一对应，减少位置顺序误用。
            if args:
                raise PTCError("注册工具只能使用命名参数调用")
            # Registry 负责最终名称匹配、参数形状检查和 handler 调用。
            result = self.registry.call(name, kwargs)
            # 保存完整审计记录；只有 emit 内容进入 output，但工具结果仍可供上层观察。
            state.calls.append({"name": name, "arguments": kwargs, "result": result})
            return result
        # 任何不在三类白名单中的名称都不能调用，包括潜在危险内置函数。
        raise PTCError(f"PTC 不允许调用：{name}")
