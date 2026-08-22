from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InterpreterTemplate:
    """一类问题对应的运行时解释器提示词。"""

    id: str
    name: str
    description: str
    keywords: tuple[str, ...]
    instructions: str


INTERPRETER_TEMPLATES = (
    InterpreterTemplate(
        id="research",
        name="联网研究解释器",
        description="搜索最新信息、事实核查和来源对照",
        keywords=("最新", "搜索", "查找", "新闻", "官网", "发布", "价格", "型号", "政策", "现任", "近期"),
        instructions=(
            "优先使用 Search 获取当前资料；关键结论至少由官方或一手来源支撑。"
            "观察不足时继续搜索，不要用‘可能’替代可验证事实；最终答案附上结果中真实存在的链接和日期。"
        ),
    ),
    InterpreterTemplate(
        id="coding",
        name="编程诊断解释器",
        description="代码实现、故障定位和技术方案",
        keywords=("代码", "编程", "python", "javascript", "java", "api", "报错", "异常", "bug", "调试", "项目", "函数", "类"),
        instructions=(
            "先识别技术栈、调用链和修改边界，再提出实现或诊断。"
            "工具观察必须作为证据；缺少源码、日志或运行结果时明确说明，不要把猜测写成已确认根因。"
        ),
    ),
    InterpreterTemplate(
        id="data",
        name="数据计算解释器",
        description="计算、指标分析和结构化数据推导",
        keywords=("计算", "数据", "统计", "指标", "平均", "总计", "同比", "环比", "占比", "趋势", "表格", "分析"),
        instructions=(
            "先确认数据口径，再使用 Calculate 或 PTC 完成可复核计算。"
            "最终答案写出关键输入、计算结果和限制，不编造缺失数据。"
        ),
    ),
    InterpreterTemplate(
        id="writing",
        name="写作整理解释器",
        description="撰写、润色、总结和结构化表达",
        keywords=("写一", "撰写", "润色", "改写", "总结", "摘要", "邮件", "文案", "报告", "周报", "翻译"),
        instructions=(
            "先确认目标读者、用途和语气，保持用户给出的事实与边界。"
            "除非内容依赖当前事实，否则直接组织答案，不为展示流程而滥用工具。"
        ),
    ),
    InterpreterTemplate(
        id="operations",
        name="部署运维解释器",
        description="部署、配置、服务状态和故障恢复",
        keywords=("部署", "运维", "服务器", "端口", "进程", "日志", "容器", "docker", "配置", "启动", "服务", "网络"),
        instructions=(
            "遵循只读诊断、定位证据、最小修复、验证结果的顺序。"
            "涉及删除、覆盖、付费或外部发布时先说明目标和风险，不得把未执行操作描述成成功。"
        ),
    ),
    InterpreterTemplate(
        id="general",
        name="通用任务解释器",
        description="日常问答、解释和未命中特定领域的任务",
        keywords=(),
        instructions=(
            "优先直接、准确地解决问题；只有缺少事实或需要计算、天气、搜索时才调用工具。"
            "区分已知事实、工具观察和合理推断。"
        ),
    ),
)


class PromptManager:
    """选择解释器模板并构造 ReAct 运行时系统提示词。"""

    def __init__(self, templates: tuple[InterpreterTemplate, ...] = INTERPRETER_TEMPLATES) -> None:
        if not templates:
            raise ValueError("至少需要一个解释器模板")
        self.templates = templates
        self._by_id = {template.id: template for template in templates}
        if len(self._by_id) != len(templates):
            raise ValueError("解释器模板 id 不能重复")
        if "general" not in self._by_id:
            raise ValueError("解释器模板必须包含 general")

    def select(self, user_text: str) -> InterpreterTemplate:
        """按关键词得分选择模板；同分时沿用模板声明顺序。"""
        normalized = user_text.casefold()
        best = self._by_id["general"]
        best_score = 0
        for template in self.templates:
            if template.id == "general":
                continue
            score = sum(1 for keyword in template.keywords if keyword.casefold() in normalized)
            if score > best_score:
                best = template
                best_score = score
        return best

    def catalog(self) -> list[dict[str, str]]:
        """返回可展示的模板元数据，不暴露内部关键词匹配细节。"""
        return [
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "instructions": template.instructions,
            }
            for template in self.templates
        ]

    def build_system_prompt(
        self,
        *,
        base_prompt: str,
        template: InterpreterTemplate,
        runtime_now: str,
        runtime_weekday: str,
        tool_descriptions: str,
    ) -> str:
        """把基础身份、解释器、工具目录和 ReAct 协议合成系统上下文。"""
        return f"""{base_prompt}

当前可信运行时日期时间为 {runtime_now}（Asia/Shanghai，{runtime_weekday}）。

【当前解释器】
名称：{template.name}
用途：{template.description}
执行要求：{template.instructions}

【可执行动作】
{tool_descriptions}

【ReAct 输出协议】
你在每一步只能输出以下两种格式之一，不要使用 Markdown 代码块：

Thought: <不超过 80 个汉字的行动理由，只说明接下来要验证或执行什么，不展示详细私有推理>
Action: <动作名>[<动作输入>]

或在已有信息足以回答时：

Thought: <不超过 80 个汉字的结论依据摘要>
Action: Finish[<给用户的完整最终答案>]

规则：
1. 每一步只允许一个 Action，动作名必须来自上面的可执行动作或 Finish。
2. Search 和 Weather 可直接放自然语言输入；其他工具使用 JSON 对象参数。
3. PTC 输入使用 JSON：{{"code": "受限 Python 程序"}}，程序用 emit(value) 输出。
4. 执行动作后框架会追加 Observation；必须依据观察继续，不得伪造工具结果。
5. Observation 不充分时继续调用工具；足够时使用 Finish，不要无限搜索。
6. 联网问题必须以工具返回的标题、来源、链接和发布时间为依据，不用旧记忆替代搜索结果。
7. 用户询问当前日期、时间或星期时必须调用 Time；星期必须直接采用 Time 返回的 weekday，禁止自行心算。
8. “今天/昨天/明天”等相对日期必须以本轮可信运行时日期为基准换算，并在答案中写出绝对日期以消除歧义。
"""


prompt_manager = PromptManager()


def get_interpreter_catalog() -> dict[str, Any]:
    """API 使用的解释器模板目录。"""
    return {"templates": prompt_manager.catalog()}
