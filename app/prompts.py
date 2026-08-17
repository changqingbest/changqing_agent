from __future__ import annotations

from typing import Any


# 分类顺序就是前端展示顺序；id 是稳定协议字段，name 是中文显示名称。
PROMPT_CATEGORIES = [
    {"id": "general", "name": "通用"},
    {"id": "research", "name": "搜索调研"},
    {"id": "coding", "name": "编程开发"},
    {"id": "writing", "name": "写作总结"},
    {"id": "data", "name": "数据分析"},
    {"id": "productivity", "name": "效率办公"},
    {"id": "creative", "name": "创意多媒体"},
    {"id": "operations", "name": "部署运维"},
]


# 模板中的【占位内容】刻意保留给用户编辑。模板只会填入输入框，不会被后端自动执行。
PROMPT_TEMPLATES = [
    {"id": "explain-clearly", "category": "general", "title": "通俗解释", "description": "把复杂概念讲给初学者", "prompt": "请用适合初学者的方式解释【概念】。先给一句话结论，再用一个生活化类比说明原理，最后列出 3 个常见误区。"},
    {"id": "compare-options", "category": "general", "title": "方案对比", "description": "比较选择并给出建议", "prompt": "请比较【方案 A】和【方案 B】。从成本、效果、风险、实施难度和适用场景分析，用表格总结，并根据【我的约束】给出明确建议。"},
    {"id": "step-by-step-plan", "category": "general", "title": "行动计划", "description": "把目标拆成可执行步骤", "prompt": "我的目标是【目标】。请先识别关键约束和未知信息，再拆成按优先级排列的执行步骤。每一步写明产出、验收标准和可能风险。"},
    {"id": "web-research", "category": "research", "title": "联网调研", "description": "搜索最新资料并标注来源", "prompt": "请联网搜索【主题】的最新资料。优先使用官方和一手来源，区分已确认事实与推测，给出关键结论、来源链接、信息日期和仍待核实的问题。"},
    {"id": "fact-check", "category": "research", "title": "事实核查", "description": "验证一项说法是否可靠", "prompt": "请核查这项说法：『【待核查说法】』。搜索至少两个独立可靠来源，说明证据是否一致，给出成立、不成立或证据不足的结论，并附来源链接。"},
    {"id": "weather-plan", "category": "research", "title": "天气与出行", "description": "查询天气并制定出行建议", "prompt": "请调用天气工具查询【地点】未来【天数】天的天气，根据温度、降水概率和风速，为【活动】给出穿衣、时间安排和备选方案。"},
    {"id": "code-implementation", "category": "coding", "title": "功能实现", "description": "从需求生成可验证实现", "prompt": "请在【技术栈/项目】中实现【功能】。先确认现有调用链和边界，再给出最小改动方案、完整代码、异常处理、测试用例和运行命令。不要改动无关业务逻辑。"},
    {"id": "debug-error", "category": "coding", "title": "错误诊断", "description": "根据日志定位根因", "prompt": "请诊断以下错误。基于代码、配置和日志建立证据链，区分根因与伴随现象；先给出定位结论，再给最小修复方案和验证步骤。\n\n【错误日志】\n"},
    {"id": "code-review", "category": "coding", "title": "代码审查", "description": "检查缺陷、安全和可维护性", "prompt": "请审查【文件或代码】。重点检查真实缺陷、安全风险、并发与边界条件、兼容性和测试缺口。按严重程度排序，并为每个问题给出具体位置、触发条件和修改建议。"},
    {"id": "polish-writing", "category": "writing", "title": "内容润色", "description": "改善表达但保持原意", "prompt": "请润色下面的内容，保持事实和原意不变，使表达更清晰、自然、专业。目标读者是【读者】，语气为【语气】。输出润色稿，并简要说明主要修改。\n\n【原文】\n"},
    {"id": "structured-summary", "category": "writing", "title": "结构化总结", "description": "提炼结论、证据和待办", "prompt": "请总结以下内容。先给不超过 100 字的结论，再列出关键事实、重要数据、争议或风险、行动项和负责人/截止时间（若原文有）。不要补充原文没有的信息。\n\n【内容】\n"},
    {"id": "customer-qa", "category": "writing", "title": "客户问答", "description": "生成客户可能提出的问题与答案", "prompt": "围绕【产品/方案】整理客户最可能问的 10 个问题并给出答案。先输出客户问答，再补充每个答案的依据和能力边界；无法确认的内容明确标记为待核实。"},
    {"id": "analyze-table", "category": "data", "title": "表格分析", "description": "从数据中发现趋势和异常", "prompt": "请分析【数据表/字段说明】。先检查数据质量和口径，再计算关键指标，识别趋势、异常和可能驱动因素。结论必须对应具体数据，并说明限制和下一步验证方法。"},
    {"id": "design-metrics", "category": "data", "title": "指标设计", "description": "定义核心指标与监控方法", "prompt": "请为【业务目标】设计指标体系，包括北极星指标、驱动指标和护栏指标。逐项写明定义、公式、数据源、统计周期、目标值和常见误用。"},
    {"id": "root-cause-analysis", "category": "data", "title": "指标归因", "description": "诊断指标变化原因", "prompt": "【指标】在【时间范围】从【原值】变化到【现值】。请先核对口径与数据质量，再按用户、渠道、地区、产品和时间等维度提出归因分析，区分已验证驱动因素和待验证假设。"},
    {"id": "meeting-notes", "category": "productivity", "title": "会议纪要", "description": "整理决策、分歧和行动项", "prompt": "请把以下会议记录整理为正式纪要，包含会议目标、关键讨论、已达成决策、未决问题、行动项、负责人和截止时间。信息缺失时标记“待确认”。\n\n【会议记录】\n"},
    {"id": "email-draft", "category": "productivity", "title": "邮件草稿", "description": "撰写清晰专业的邮件", "prompt": "请撰写一封发给【收件人】的邮件，目的是【目的】，需要包含【关键信息】。语气【正式/友好/坚定】，主题明确，正文简洁，并给出清楚的下一步行动。"},
    {"id": "weekly-report", "category": "productivity", "title": "周报生成", "description": "把工作记录整理为周报", "prompt": "请将以下工作记录整理成周报：本周成果、关键数据、问题与风险、下周计划、需要协调的事项。突出实际产出，避免空泛描述。\n\n【工作记录】\n"},
    {"id": "image-prompt", "category": "creative", "title": "图片生成提示词", "description": "把创意转成完整视觉描述", "prompt": "请把【创意主题】扩写为高质量图片生成提示词。明确主体、场景、构图、镜头、光线、色彩、材质、风格和画幅，并补充应避免的元素。"},
    {"id": "video-storyboard", "category": "creative", "title": "视频分镜", "description": "生成短视频脚本和镜头表", "prompt": "为【主题】设计一段【时长】秒的视频。给出整体创意、逐镜头画面、镜头运动、旁白/字幕、音效和转场，确保人物与视觉风格前后一致。"},
    {"id": "voiceover-script", "category": "creative", "title": "配音脚本", "description": "撰写适合朗读的口播稿", "prompt": "请为【用途】撰写一段约【时长】的中文配音稿，受众是【受众】，声音风格为【风格】。句子适合自然朗读，并标注停顿、重音和情绪变化。"},
    {"id": "deployment-plan", "category": "operations", "title": "部署方案", "description": "制定可回滚的上线计划", "prompt": "请为【项目】制定部署方案。先识别运行时、依赖、端口、环境变量和外部服务，再列出部署步骤、健康检查、日志位置、回滚方法和成本/风险；执行付费或破坏性操作前先征求确认。"},
    {"id": "incident-response", "category": "operations", "title": "故障处置", "description": "建立故障诊断与恢复步骤", "prompt": "当前故障现象是【现象】。请先给出只读诊断清单，依据日志、进程、端口、资源和近期变更缩小范围；然后给出分阶段恢复方案、风险、回滚点和验证标准。"},
    {"id": "release-checklist", "category": "operations", "title": "发布检查表", "description": "上线前后逐项验收", "prompt": "请为【版本/功能】生成发布检查表，覆盖代码与测试、配置与密钥、数据库迁移、兼容性、监控告警、灰度发布、回滚和上线后验收。每项提供负责人和完成状态栏。"},
]


def get_prompt_catalog() -> dict[str, Any]:
    """返回可直接 JSON 序列化的模板目录副本，避免调用方修改模块级数据。"""
    return {
        "categories": [dict(category) for category in PROMPT_CATEGORIES],
        "templates": [dict(template) for template in PROMPT_TEMPLATES],
    }
