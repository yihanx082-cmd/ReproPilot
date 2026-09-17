# ReproPilot Agent 消融评测方法

## 为什么需要第二套评测

现有真实模型基线在 3 个冻结仓库、6 个单故障案例中取得定位 `6/6`、修复 `6/6`、语义探针 `6/6`。它证明 ReproPilot 可以修复这些案例，但全部案例都在第一次模型调用后成功，因此不能回答“反馈循环是否优于单轮生成”。

新的渐进评测不会替代原基线。它将同一仓库中的两个冻结故障同时注入，但每次只暴露最靠前的失败阶段。Agent 修复第一个问题后才会看到第二个问题，更接近真实项目中错误逐层暴露的过程。

## 四个实验组

| 组别 | 可见信息 | 最大模型调用数 |
|---|---|---:|
| `single_turn_raw` | 原始错误、允许修改路径 | 1 |
| `diagnosis_single_turn` | 原始错误、结构化诊断、相关文件 | 1 |
| `feedback_loop` | 结构化诊断、上一补丁、验证失败、回滚状态 | 3 |
| `episodic_memory` | 反馈循环全部信息、跨仓库验证经验 | 3 |

四组固定使用相同仓库、提交、故障、探针、模型和运行顺序。单轮组严格限制一次模型调用，因此完整任务成功率能够直接反映它能否一次处理后续尚未暴露的问题。

## 三个冻结渐进案例

1. ConvMixer：缺少依赖 → CIFAR-10 路径错误；
2. ResNet：学习率默认值错误 → Top-1 指标实现错误；
3. Lightning：CPU/CUDA 选择错误 → 验证集随机打乱。

冻结清单位于 `benchmark/real-ablation.yaml`，每个仓库使用完整 40 位提交 SHA。故障补丁和语义探针来自已经验证的真实项目评测集。

## 记忆边界

记忆使用本地 SQLite，只保存已经满足以下条件的经验：

- 补丁成功应用；
- 目标验证通过；
- 所有语义探针通过；
- 修改没有越过允许路径；
- 内容不包含常见密钥格式。

检索按故障类别和错误签名词项排序，默认最多返回两条。同一仓库和同一提交的经验会被排除，防止把目标答案直接泄漏给 Agent。当前数据规模很小，不需要引入 Redis、ChromaDB 或向量检索。

## 指标与统计口径

主指标是完整任务成功率：两个阶段全部修复且探针全部通过的案例数除以总案例数。辅助指标包括阶段解决率、安全完成率、无关修改行比例、模型调用、Token、补丁尝试次数、墙钟时间和记忆命中数。

每个百分比必须显示分子和分母，例如 `7/9 (77.8%)`。实验组与基线的差异使用百分点，例如 `77.8% - 55.6% = +22.2 个百分点`。这些指标衡量 Agent 完成代码修复任务的表现，不是图像分类模型准确率。

样本量较小时只报告观察到的差异，不使用“统计显著”等表述。

## Fixture 验证

Fixture 模式使用已知注入补丁的逆补丁，只验证评测器能否正确完成注入、分阶段暴露、补丁应用、反馈、统计和报告：

```powershell
python scripts/run_ablation.py `
  --manifest benchmark/real-ablation.yaml `
  --output artifacts/ablation-fixture `
  --fixture-mode tests/fixtures/ablation-responses.json `
  --approve-high-risk
```

Fixture 报告会永久显示 `FIXTURE MODE`，不能作为 Agent 性能证据，也不能写入简历成绩。

## 真实模型实验

真实实验需要全新的本地 API Key，且评测代码、清单和测试必须先提交：

```powershell
$env:OPENAI_API_KEY="<new-local-key>"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_MODEL="<model-name>"

python scripts/run_ablation.py `
  --manifest benchmark/real-ablation.yaml `
  --output artifacts/ablation/<timestamp>-final `
  --arms single_turn_raw,diagnosis_single_turn,feedback_loop,episodic_memory `
  --repetitions 3 `
  --approve-high-risk
```

程序拒绝覆盖已有输出目录，也会拒绝在评测器相关代码未提交时运行付费实验。失败案例不得单独重跑后替换；完整重跑必须使用新目录并单独报告。

## 证据产物

每次运行生成：

- `ablation-results.json`：逐案例、逐重复的原始结果；
- `ablation-summary.md`：四组计数、百分比和百分点差；
- `ablation-report.html`：适合展示的可视化报告。

简历和作品集只允许引用真实模式的 JSON 结果。若反馈循环或记忆没有提升，也应保留结果并分析原因。

## 已发布结果

2026-09-17 已按本协议完成真实模型三重复实验。原始单轮完整任务成功 `0/9`、阶段解决 `9/18`；反馈循环完整任务成功 `9/9`、阶段解决 `18/18`，差值为 `+100.0` 个百分点。四组均观察到 0 行无关修改。

结果解释必须同时说明：每个任务顺序暴露两个故障，单轮组只有一次调用，因此该差值衡量的是闭环继续处理后续故障的能力；记忆组有效命中为 0，不能从本轮结果声称记忆增益。可提交的聚合证据见 [`benchmark/agent-ablation-2026-09-17-summary.md`](../../benchmark/agent-ablation-2026-09-17-summary.md)。
