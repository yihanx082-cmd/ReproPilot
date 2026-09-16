# ruff: noqa: E501 - Chinese portfolio copy is kept as intact strings for review.

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "ReproPilot-AI-Product-Portfolio.pdf"
ASSETS = ROOT / "docs" / "product" / "assets"

INK = colors.HexColor("#14213D")
MUTED = colors.HexColor("#5E6B7A")
TEAL = colors.HexColor("#00A6A6")
BLUE = colors.HexColor("#2D6CDF")
PALE = colors.HexColor("#EEF4FA")
PALE_TEAL = colors.HexColor("#E8F7F5")
WHITE = colors.white
LIGHT_LINE = colors.HexColor("#D9E2EC")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("CN", r"C:\Windows\Fonts\Deng.ttf"))
    pdfmetrics.registerFont(TTFont("CN-Bold", r"C:\Windows\Fonts\Dengb.ttf"))


register_fonts()


class AccentRule(Flowable):
    def __init__(self, width: float, color=TEAL, thickness: float = 3):
        super().__init__()
        self.width = width
        self.height = thickness
        self.color = color
        self.thickness = thickness

    def draw(self) -> None:
        self.canv.setFillColor(self.color)
        self.canv.roundRect(0, 0, self.width, self.thickness, 1.5, fill=1, stroke=0)


class MetricBar(Flowable):
    def __init__(self, values: list[tuple[str, float, str]], width: float, height: float = 52):
        super().__init__()
        self.values = values
        self.width = width
        self.height = height

    def draw(self) -> None:
        c = self.canv
        max_value = max(value for _, value, _ in self.values)
        bar_h = 8
        gap = 17
        y = self.height - 10
        for label, value, display in self.values:
            c.setFont("CN", 8.5)
            c.setFillColor(MUTED)
            c.drawString(0, y, label)
            c.setFillColor(PALE)
            c.roundRect(72, y - 1, self.width - 112, bar_h, 4, fill=1, stroke=0)
            c.setFillColor(TEAL)
            c.roundRect(
                72, y - 1, (self.width - 112) * value / max_value, bar_h, 4, fill=1, stroke=0
            )
            c.setFont("CN-Bold", 9)
            c.setFillColor(INK)
            c.drawRightString(self.width, y, display)
            y -= gap


def styles():
    base = getSampleStyleSheet()
    return {
        "kicker": ParagraphStyle(
            "kicker",
            parent=base["Normal"],
            fontName="CN-Bold",
            fontSize=9,
            leading=12,
            textColor=TEAL,
            spaceAfter=5,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="CN-Bold",
            fontSize=25,
            leading=32,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=7,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="CN-Bold",
            fontSize=20,
            leading=26,
            textColor=INK,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="CN-Bold",
            fontSize=12,
            leading=16,
            textColor=BLUE,
            spaceBefore=5,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="CN",
            fontSize=9.5,
            leading=15,
            textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName="CN",
            fontSize=7.4,
            leading=10.5,
            textColor=MUTED,
        ),
        "quote": ParagraphStyle(
            "quote",
            parent=base["BodyText"],
            fontName="CN",
            fontSize=11,
            leading=17,
            textColor=INK,
            leftIndent=12,
            rightIndent=8,
            spaceBefore=5,
            spaceAfter=8,
        ),
        "number": ParagraphStyle(
            "number",
            parent=base["Normal"],
            fontName="CN-Bold",
            fontSize=24,
            leading=27,
            textColor=TEAL,
            alignment=TA_CENTER,
        ),
        "label": ParagraphStyle(
            "label",
            parent=base["Normal"],
            fontName="CN",
            fontSize=8,
            leading=11,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="CN-Bold",
            fontSize=34,
            leading=41,
            textColor=WHITE,
            alignment=TA_LEFT,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            parent=base["Normal"],
            fontName="CN",
            fontSize=14,
            leading=21,
            textColor=colors.HexColor("#DDE8F5"),
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            parent=base["Normal"],
            fontName="CN",
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#B9C7D9"),
        ),
    }


S = styles()


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def section_header(number: str, title: str, subtitle: str | None = None):
    items = [P(f"CASE STUDY / {number}", "kicker"), P(title, "h1"), AccentRule(48 * mm)]
    if subtitle:
        items.extend([Spacer(1, 3 * mm), P(subtitle, "body")])
    items.append(Spacer(1, 3 * mm))
    return items


def bullet(text: str) -> Paragraph:
    return Paragraph(f"<font color='#00A6A6'>●</font>&nbsp;&nbsp;{text}", S["body"])


def stat_cards(values: list[tuple[str, str]], widths=None) -> Table:
    cells = []
    for value, label in values:
        cells.append([P(value, "number"), P(label, "label")])
    t = Table([cells], colWidths=widths)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_TEAL),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#B8E5E0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#B8E5E0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def evidence_table(rows, widths):
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "CN-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "CN"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
                ("GRID", (0, 0), (-1, -1), 0.45, LIGHT_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def page_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#F8FAFC"))
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setFillColor(INK)
    canvas.setFont("CN-Bold", 7)
    canvas.drawString(18 * mm, 10 * mm, "REPROPILOT / AI PRODUCT CASE")
    canvas.setFillColor(MUTED)
    canvas.setFont("CN", 7)
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page:02d}")
    canvas.restoreState()


def cover_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.circle(A4[0] - 16 * mm, A4[1] - 22 * mm, 44 * mm, fill=1, stroke=0)
    canvas.setFillColor(BLUE)
    canvas.circle(A4[0] - 4 * mm, 28 * mm, 26 * mm, fill=1, stroke=0)
    canvas.restoreState()


def build_story():
    story = []

    story.extend(
        [
            Spacer(1, 42 * mm),
            P("AI 产品经理作品附件", "cover_meta"),
            Spacer(1, 4 * mm),
            P("ReproPilot", "cover_title"),
            Spacer(1, 4 * mm),
            P("面向机器学习论文复现的<br/>代码执行与修复智能体", "cover_sub"),
            Spacer(1, 13 * mm),
            AccentRule(46 * mm, TEAL, 4),
            Spacer(1, 12 * mm),
            P(
                "独立完成产品定义、Agent 状态机、工程实现、评测体系、用户研究与原型迭代",
                "cover_sub",
            ),
            Spacer(1, 42 * mm),
            P(
                "yihanx082-cmd&nbsp;&nbsp;·&nbsp;&nbsp;2026.09&nbsp;&nbsp;·&nbsp;&nbsp;作品集级 MVP",
                "cover_meta",
            ),
        ]
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "01",
            "为什么“跑起来”仍不等于“复现成功”",
            "论文复现横跨论文、代码、环境和实验协议。真正的风险不只是报错，还包括程序正常结束却比较了错误的数据、配置或指标。",
        )
    )
    story.append(
        P("“最危险的不是程序报错，而是程序正常结束，但实验协议已经和论文不一样了。”", "quote")
    )
    story.append(P("计算机视觉方向硕士生，P02", "small"))
    story.append(Spacer(1, 4 * mm))
    story.append(
        evidence_table(
            [
                ["用户任务", "常见断点", "误判风险"],
                ["搭建环境", "旧版 PyTorch、CUDA、驱动、依赖缺失", "把安装问题当作论文或模型问题"],
                [
                    "对齐实验",
                    "学习率、数据划分、增强、checkpoint 版本",
                    "代码可运行，但协议已经偏离论文",
                ],
                [
                    "比较结果",
                    "accuracy/error、macro/micro-F1、单次最好值",
                    "数字接近，却不能直接比较",
                ],
                [
                    "判断成功",
                    "日志、diff、配置和结果散落在多处",
                    "缺少可追溯证据，结论依赖主观判断",
                ],
            ],
            [34 * mm, 65 * mm, 67 * mm],
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(P("产品机会", "h2"))
    story.append(
        P(
            "把分散的复现动作组织成一条可审查的证据链：系统不仅执行，还要解释做了什么、为什么修改、证据在哪里，以及当前结论能支持到什么程度。"
        )
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "02",
            "目标用户与第一轮真实研究",
            "目标用户不是完全不会编程的人，而是有基础 Python/机器学习经验、需要减少环境和排错成本，同时必须保留科学判断权的复现者。",
        )
    )
    story.append(
        stat_cards(
            [
                ("5/5", "完成核心流程"),
                ("3/5", "无帮助独立完成"),
                ("2/5", "首次误认可信度"),
                ("3.8/5", "满意度均值"),
            ],
            [42 * mm] * 4,
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(P("研究发现", "h2"))
    for text in [
        "环境、依赖和数据版本仍是最显性的时间成本。",
        "指标口径与 checkpoint 来源会产生更隐蔽、更高风险的错误。",
        "新手容易把“代码跑通”“结果接近”和“复现可信”混成一个结论。",
        "专业用户需要精确 diff、补丁哈希、测试断言与原始日志，不能只看绿色状态。",
    ]:
        story.append(bullet(text))
    story.append(Spacer(1, 4 * mm))
    story.append(P("研究边界", "h2"))
    story.append(
        P(
            "样本为 5 人便利抽样，只用于发现问题和验证交互；第一轮未达到预设的 4/5 独立完成门槛，因此结论是“核心路径可完成，但可用性验证未通过”。没有逐任务计时和统一人工基线，所以不声称节省了多少时间或步骤。"
        )
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "03",
            "产品闭环：从 PDF 到可信度报告",
            "MVP 将通用大模型能力约束在论文抽取和补丁建议两个语义环节，其余关键控制由确定性程序完成。",
        )
    )
    flow_rows = [
        [
            P("01", "number"),
            P("论文证据解析", "h2"),
            P("抽取实验设置、指标和论文结果，并保留页码证据"),
        ],
        [
            P("02", "number"),
            P("代码配置审计", "h2"),
            P("扫描配置、README 和参数默认值，输出论文与代码的差异"),
        ],
        [
            P("03", "number"),
            P("隔离执行与修复", "h2"),
            P("Docker 构建、最小运行、诊断、最小补丁、测试与回滚"),
        ],
        [
            P("04", "number"),
            P("正式实验与对比", "h2"),
            P("记录多种子命令和日志，比较论文值与观测值"),
        ],
        [
            P("05", "number"),
            P("可信度报告", "h2"),
            P("七维评分，每个得分绑定 artifact，明确证据边界"),
        ],
    ]
    flow = Table(flow_rows, colWidths=[18 * mm, 43 * mm, 102 * mm])
    flow.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [PALE_TEAL, WHITE]),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, LIGHT_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(flow)
    story.append(Spacer(1, 7 * mm))
    story.append(P("MVP 取舍", "h2"))
    story.append(
        P(
            "选择 Python CLI + 本地 Web + 冻结公开原型：CLI 负责真实执行，Web 解释状态和审批，公开原型保证面试演示稳定。暂不做账号系统、云 GPU、多用户协作或 Kubernetes，避免作品集 MVP 失焦。"
        )
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "04",
            "关键产品机制：自动修复不能越过科学语义",
            "系统区分“低风险兼容性修复”和“会改变实验含义的高风险修改”。后者必须暂停，让使用者基于完整证据作出决定。",
        )
    )
    story.append(
        evidence_table(
            [
                ["机制", "实现", "用户价值"],
                ["最小补丁", "限制相关文件、最多 3 个文件/120 行", "减少无关修改，便于审查"],
                ["风险门", "数据、指标、模型、权重修改必须审批", "防止 Agent 静默改变实验语义"],
                [
                    "证据审批",
                    "根因、diff、数值示例、断言、退出码、日志",
                    "让批准基于证据，而非绿色按钮",
                ],
                ["SHA 绑定", "审批绑定补丁 SHA-256", "补丁变化后旧批准自动失效"],
                ["事务回滚", "验证失败后反向应用并校验恢复", "避免工作副本被失败修复污染"],
            ],
            [32 * mm, 66 * mm, 68 * mm],
        )
    )
    story.append(Spacer(1, 6 * mm))
    image_path = ASSETS / "prototype-timeline.png"
    if image_path.exists():
        img = Image(str(image_path), width=164 * mm, height=73 * mm)
        story.append(img)
        story.append(
            P("原型执行时间线：阶段、暂停原因、补丁与测试证据在同一上下文中展示。", "small")
        )
    story.append(PageBreak())

    story.extend(
        section_header(
            "05",
            "真实案例：结果接近，但仍只能判定 PARTIAL",
            "ResNet-20/CIFAR-10 案例验证了端到端闭环，也展示了产品如何拒绝夸大结论。",
        )
    )
    story.append(
        stat_cards(
            [
                ("8.75%", "论文 Error"),
                ("8.27%", "观测 Error"),
                ("-0.48pp", "与论文差值"),
                ("80/100", "证据可信度"),
            ],
            [42 * mm] * 4,
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(P("运行发生了什么", "h2"))
    for text in [
        "从论文 PDF 中定位 ResNet-20/CIFAR-10 表格结果。",
        "旧仓库在 CPU Docker 中因无条件调用 CUDA 首次失败。",
        "第一版补丁暴露 checkpoint 缺少 epoch 元数据，系统先回滚再生成完整补丁。",
        "目标测试通过后执行种子 11、22、33 的三个独立评估进程。",
    ]:
        story.append(bullet(text))
    story.append(Spacer(1, 4 * mm))
    story.append(P("为什么不是完整复现", "h2"))
    story.append(
        P(
            "三个种子评估的是同一个公开 checkpoint，没有从头训练；原始数据划分 provenance、训练增强和 checkpoint 版本证据不完整。零方差只说明评估确定性，不能证明训练过程稳定。因此最终报告为 <b>80/100 PARTIAL</b>，而不是“论文已复现”。"
        )
    )
    story.append(Spacer(1, 5 * mm))
    score_rows = [
        ["评分维度", "得分", "证据边界"],
        ["环境", "15/15", "Docker 构建证据完整"],
        ["数据", "10/20", "数据可用，原始划分来源不完整"],
        ["配置", "10/20", "只恢复了部分训练配方"],
        ["指标", "15/15", "论文与运行 Error 可直接比较"],
        ["随机种子", "10/10", "三个独立命令 artifact"],
        ["结果接近", "15/15", "差值 0.48 个百分点"],
        ["外部依赖", "5/5", "构建依赖可获得"],
    ]
    story.append(evidence_table(score_rows, [41 * mm, 24 * mm, 101 * mm]))
    story.append(PageBreak())

    story.extend(
        section_header(
            "06",
            "Agent 评测：用故障注入测定位、修复与副作用",
            "评测对象不是论文指标，而是 Agent 在固定真实仓库上面对未知单故障时，能否在受控范围内找到并修好问题。",
        )
    )
    story.append(
        stat_cards(
            [
                ("3", "模型实测仓库"),
                ("6/6", "定位与修复"),
                ("0%", "无关改动率"),
                ("54s", "Agent 墙钟"),
            ],
            [42 * mm] * 4,
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(
        MetricBar(
            [
                ("错误定位", 6, "6/6"),
                ("修复成功", 6, "6/6"),
                ("修复后探针", 6, "6/6"),
                ("安全约束", 6, "6/6"),
            ],
            164 * mm,
            64,
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("故障类型", "h2"))
    story.append(
        P(
            "缺少依赖、错误数据路径、学习率不一致、Top-1 指标错误、CUDA 回退、验证集 shuffle。每个案例固定仓库提交、允许修改文件、故障探针与修复后语义探针。"
        )
    )
    story.append(P("证据边界", "h2"))
    story.append(
        P(
            "当前清单已经扩展到 5 个仓库、8 个案例，但新增 2 个案例只完成确定性注入与探针验证，尚未进行模型修复。因此公开成绩仍是原始 3 仓库/6 案例，不能写成 8/8，更不能外推为任意论文的成功率。"
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        evidence_table(
            [
                ["运行成本", "观测值"],
                ["模型调用", "6 次"],
                ["Token", "输入 17,753 / 输出 1,093，共 18,846"],
                ["工具调用", "54 次"],
                ["平均补丁尝试", "1.0"],
                ["模型美元成本", "服务商未返回价格，保持未知"],
            ],
            [62 * mm, 104 * mm],
        )
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "07",
            "用户研究驱动的第二版，不隐藏第一次失败",
            "第一轮测试暴露的最大问题不是功能缺失，而是状态和证据表达会让经验较少的用户产生错误结论。",
        )
    )
    change_rows = [
        ["观察证据", "产品风险", "第二版修改"],
        [
            "2/5 把 80/100 当准确率",
            "把证据评分误解成模型性能",
            "永久显示“证据可信度，非模型准确率”",
        ],
        [
            "审批只看文件名、SHA 和命令",
            "用户无法判断补丁是否真的正确",
            "增加转换示例、论文引用、断言、退出码和日志",
        ],
        ["拒绝后仍显示 VERIFIED", "状态与用户决定冲突", "拒绝后进入 STOPPED，后续阶段全部停止"],
        ["初学者不懂 diff/SHA", "看见证据但无法使用证据", "增加中文解释，同时保留原始技术材料"],
    ]
    story.append(evidence_table(change_rows, [50 * mm, 52 * mm, 64 * mm]))
    story.append(Spacer(1, 6 * mm))
    image_path = ASSETS / "prototype-report.png"
    if image_path.exists():
        img = Image(str(image_path), width=164 * mm, height=72 * mm)
        story.append(img)
        story.append(
            P(
                "第二版可信度报告：分数与模型准确率长期分离，扣分原因可追溯到 evidence artifact。",
                "small",
            )
        )
    story.append(Spacer(1, 5 * mm))
    story.append(P("下一轮验证标准", "h2"))
    story.append(
        P(
            "至少 4/5 无帮助完成流程、至少 4/5 正确解释 PARTIAL、0/5 将可信度分数误认为模型准确率。第二轮必须由真实参与者完成，AI 不能代替。"
        )
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "08",
            "产品定位：不是更会聊天，而是更会管理证据",
            "ReproPilot 不替代论文发现、托管环境或通用 Coding Agent；它把三者之间缺失的论文复现判断做成一条受控工作流。",
        )
    )
    story.append(
        evidence_table(
            [
                ["方案", "擅长什么", "ReproPilot 的差异"],
                [
                    "人工工作流",
                    "灵活，能处理复杂科学判断",
                    "将重复执行与证据整理结构化，但保留人的判断权",
                ],
                [
                    "Papers with Code",
                    "发现论文、代码、数据集和榜单",
                    "继续完成环境执行、修复与一次具体运行的审计",
                ],
                [
                    "Code Ocean",
                    "封装、分享和重复运行计算环境",
                    "接手可能损坏的旧仓库，审计论文一致性并受控修复",
                ],
                [
                    "通用 Coding Agent",
                    "完成通用仓库任务与 PR",
                    "增加论文声明、实验协议、科学指标与可信度状态机",
                ],
            ],
            [38 * mm, 56 * mm, 72 * mm],
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(P("窄定位", "h2"))
    story.append(
        P(
            "面向已有论文与仓库，从配置审计开始，经过隔离执行和受控修复，最终输出论文结果对比与可追溯的复现可信度判断。"
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("为什么选择作品集级 MVP", "h2"))
    for text in [
        "先聚焦 PyTorch 图像分类与 10-20 分钟缩小实验，控制技术范围。",
        "公开网页使用冻结证据，保证面试演示稳定；本地 live 模式连接真实状态机。",
        "不承诺云端多租户、完整 GPU 调度和受限数据许可管理。",
    ]:
        story.append(bullet(text))
    story.append(PageBreak())

    story.extend(
        section_header(
            "09",
            "独立完成：从产品问题到可运行系统",
            "项目不是单一原型或概念 PRD，而是一套产品判断、工程证据和用户验证互相约束的作品。",
        )
    )
    story.append(
        evidence_table(
            [
                ["角色", "完成内容"],
                ["产品", "问题定义、用户分层、竞品分析、PRD、MVP 边界、指标方案和迭代优先级"],
                [
                    "Agent/工程",
                    "状态机、PDF 证据抽取、代码审计、Docker 沙箱、诊断、补丁策略、Git 回滚、正式实验和报告",
                ],
                [
                    "评测",
                    "真实仓库故障注入、语义探针、四组 Agent 消融、定位/修复/副作用/成本指标、证据边界",
                ],
                [
                    "设计/研究",
                    "React 可点击原型、5 位真实参与者访谈与观察、问题归纳、第二版交互修复",
                ],
                [
                    "交付",
                    "GitHub、CI、公开演示站、164 项 Python 测试（含 4 项 Docker 集成案例）、前端与 Worker 测试",
                ],
            ],
            [36 * mm, 130 * mm],
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(P("技术栈", "h2"))
    story.append(
        P(
            "Python · Pydantic · Docker · Git · pytest · React · Vite · OpenAI 兼容 API · GitHub Actions"
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(P("我学到的产品判断", "h2"))
    story.append(
        P(
            "Coding Agent 的价值不只是自动化更多步骤，而是在自动化过程中明确什么可以由系统决定、什么必须留给用户，以及每个结论需要哪些证据。对科研场景而言，正确表达不确定性本身就是产品能力。"
        )
    )
    story.append(PageBreak())

    story.extend(
        section_header(
            "10",
            "当前完成度与下一步",
            "工程 MVP、公开原型、第一轮用户研究、产品文档和求职表达已经形成闭环；剩余工作依赖新的真人或账号证据。",
        )
    )
    story.append(
        stat_cards(
            [
                ("164", "Python 测试"),
                ("4", "Docker 集成案例"),
                ("5", "真实参与者"),
                ("4", "Agent 消融组"),
            ],
            [42 * mm] * 4,
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(P("必须继续验证的四件事", "h2"))
    for text in [
        "第二轮真人复测：验证第二版是否消除可信度与状态误解。",
        "使用新模型凭据运行三重复消融实验，量化单轮、反馈循环与验证记忆的真实差异。",
        "录制本人 3-5 分钟讲解视频，补齐个人表达证据。",
        "未来加入至少一个从头训练案例，验证训练过程而非 checkpoint 评估。",
    ]:
        story.append(bullet(text))
    story.append(Spacer(1, 8 * mm))
    links = Table(
        [
            [
                P("GITHUB", "kicker"),
                P(
                    "<a href='https://github.com/yihanx082-cmd/ReproPilot' color='#2D6CDF'>github.com/yihanx082-cmd/ReproPilot</a>"
                ),
            ],
            [
                P("LIVE PROTOTYPE", "kicker"),
                P(
                    "<a href='https://repropilot-evidence-agent.yizhuliang42.chatgpt.site' color='#2D6CDF'>repropilot-evidence-agent.yizhuliang42.chatgpt.site</a>"
                ),
            ],
        ],
        colWidths=[39 * mm, 127 * mm],
    )
    links.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.6, LIGHT_LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, LIGHT_LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(links)
    story.append(Spacer(1, 10 * mm))
    story.append(P("一句话总结", "h2"))
    story.append(
        P(
            "ReproPilot 把“代码能运行”与“论文已复现”拆成两个不同问题，并用可执行状态机、补丁控制和证据评分帮助用户做出更可信的判断。"
        )
    )

    return story


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = A4
    frame = Frame(18 * mm, 17 * mm, page_w - 36 * mm, page_h - 34 * mm, id="main")
    cover = PageTemplate(id="cover", frames=[frame], onPage=cover_background)
    normal = PageTemplate(id="normal", frames=[frame], onPage=page_background)
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title="ReproPilot AI 产品经理作品附件",
        author="yihanx082-cmd",
        subject="AI Product Manager Portfolio Case Study",
    )
    doc.addPageTemplates([cover, normal])
    story = build_story()
    first_break = next(i for i, item in enumerate(story) if isinstance(item, PageBreak))
    story.insert(first_break, NextPageTemplate("normal"))
    doc.build(story)
    return OUTPUT


if __name__ == "__main__":
    print(build())
