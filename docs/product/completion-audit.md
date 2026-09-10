# ReproPilot 作品集交付审计

审计快照：2026-09-10 21:15（Asia/Shanghai）

审计基线为 GitHub `main` 提交 [`5ee32a9`](https://github.com/yihanx082-cmd/ReproPilot/commit/5ee32a9)。GitHub、网站可访问性和本机 Docker 状态会随时间变化；下表明确标记这些项目为该时间点的本机观察，而不是永久证明。

## 结论

ReproPilot 的**工程 MVP、公开可点击原型、真实用户研究第一轮、产品文档和求职表达材料已经形成完整闭环**。代码已同步到 GitHub `main`，公开网页可访问，本地网页可连接真实状态机，核心结论均保留证据边界。

尚未完成的内容不是隐藏的代码故障，而是必须由项目所有者或新的外部证据完成：轮换曾暴露的模型密钥、录制本人讲解视频、组织第二轮真人可用性复测，以及用新凭据重跑扩展后的全部八案例模型基线。

## 已验证交付物

| 范围 | 状态 | 证据 |
|---|---|---|
| GitHub | 该时间点已完成 | 本机观察 `main...origin/main = 0 0`；[PR #7](https://github.com/yihanx082-cmd/ReproPilot/pull/7)、[PR #8](https://github.com/yihanx082-cmd/ReproPilot/pull/8) 已合并；[main CI 34481563402](https://github.com/yihanx082-cmd/ReproPilot/actions/runs/34481563402) 成功 |
| Agent 核心 | 完成 | PDF 证据、代码审计、Docker、诊断、最小补丁、审批、回滚、正式实验、评分与 HTML 报告 |
| Docker | 该时间点本机可用 | 本机观察 Client/Server `29.7.2`、`hello-world` 成功；18 项显式 Docker 测试通过 |
| Python 质量 | 完成 | 153 项测试通过，默认套件仅跳过 4 项需要显式 Docker 开关的测试；Ruff、Mypy 通过 |
| 网页 | 该时间点可访问 | [公开冻结 demo](https://repropilot-evidence-agent.yizhuliang42.chatgpt.site) 本机请求返回 HTTP 200；本地 `?live=1` 调用原状态机并读取真实 artifacts |
| 前端质量 | 完成 | 15 项交互测试、4 项 Sites Worker 测试和生产构建通过 |
| 真实复现实验 | 部分复现证据完成 | ResNet-20/CIFAR-10：Error `8.27% ± 0.00` 对论文 `8.75%`，可信度 `80/100 PARTIAL` |
| Agent 评测 | 清单完成、扩展模型重跑待外部凭据 | 5 个固定仓库、8 个故障；已有模型基线覆盖原始 3 仓库/6 案例并获得 6/6 定位与修复后探针通过 |
| 用户研究 | 第一轮完成 | P01–P05：5/5 完成流程、3/5 独立完成、2/5 初次误认分数、平均满意度 3.8/5 |
| 产品迭代 | 完成 | 永久解释可信度、补充数值与测试证据、拒绝后进入 STOPPED、本地 live 模式 |
| 求职材料 | 完成 | PRD、竞品分析、案例、指标方案、访谈记录、原型交接、SQL 练习、简历 bullet、STAR 与视频脚本 |
| 仓库卫生 | 完成 | 常见 API token、私人 Windows 路径和参与者联系方式扫描无命中；自动回归测试已加入 |

## 证据边界

- `80/100` 是复现证据可信度，不是模型准确率。
- `8.27%` 来自公开 checkpoint 的重复评估，不是三次从头训练。
- `6/6` 只属于 2026-09-03 冻结的六案例模型基线，不能写成八案例成绩或通用成功率。
- 新增两个仓库已经验证固定提交、许可证、补丁应用和语义探针，但尚无新的模型修复成绩。
- 五人研究是探索性样本，只报告观察人数和原因，不外推到所有科研用户。

## 必须由项目所有者完成

1. 在 DeepSeek 控制台停用曾发送到聊天中的旧 Key，并创建新 Key；新 Key 只放入本机环境变量。
2. 根据 `demo-video-script.md` 用自己的声音和屏幕录制 3–5 分钟演示，并把公开视频链接加入 README。
3. 邀请真实参与者复测第二版；记录完成时间、提示次数和理解结果，不能由 AI 伪造。
4. 用新模型凭据运行当前 5 仓库/8 案例清单，再根据真实结果更新基线，不能沿用旧 `6/6` 推算。
5. 按 `sql-practice.md` 亲自完成练习；材料齐全不等于已经掌握面试能力。

这些步骤需要账号控制权、真人行为或个人表达，因此不能由自动化代码诚实替代。

## 快照复验命令

```powershell
git rev-list --left-right --count main...origin/main
gh run list --limit 6
docker version
docker run --rm hello-world
pytest -q
$env:REPROPILOT_DOCKER_TESTS="1"
pytest tests/test_sandbox.py tests/test_orchestrator.py -q
```
