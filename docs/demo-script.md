# ReproPilot 五分钟演示脚本

录制前运行全量测试，准备一个包含“缺失依赖”注入的本地小仓库、对应 PDF、合成数据目录，并确认 Docker Desktop 正在运行。不要在画面中展示 API key。

## 0:00–0:35：问题与输入

展示目标仓库中的注入错误和配置文件。说明输入只有论文 PDF、仓库、数据集、显式运行命令和环境约束；原仓库不会被修改。

## 0:35–1:10：启动

```powershell
repropilot run --config examples/cifar10-smoke.yaml --output-root runs
```

说明状态机依次完成论文证据解析、代码审计、Docker 构建和冒烟运行。

## 1:10–2:15：诊断与低风险修复

打开运行目录中的 `diagnosis-1.json` 与 `patch-1.json`，指出：

- 错误类别和原始日志行；
- 只修改诊断相关文件的最小 Git diff；
- 本地策略重新计算出的 `low` 风险；
- `verify-1.json` 中的定向测试结果。

再展示原仓库仍含注入错误，而 `runs/<id>/worktree` 已修复，证明输入未被改写。

## 2:15–3:05：高风险审批（预先准备暂停案例）

展示指标或患者级划分补丁进入 `WAITING_APPROVAL`。指出 patch ID 与 SHA-256 绑定：

```powershell
repropilot approve runs\<run-id> <patch-id>
repropilot resume runs\<run-id>
```

无需在正式演示中真的修改语义；重点是自动化边界。

## 3:05–4:05：HTML 证据报告

打开 `report.html`，依次展示论文—代码差异、执行命令、修复时间线、指标差值、七维评分和未解决风险。明确朗读：`PROVISIONAL_SMOKE_RUN` 不是完整论文复现。

## 4:05–4:40：六案例评测

```powershell
python scripts/run_benchmark.py --cases benchmark/cases.yaml --output artifacts/benchmark
```

打开 `benchmark-summary.md`。说明 reference 模式验证评测管线，不冒充未知项目泛化成绩；真实模型评测复用同一指标格式。

## 4:40–5:00：收尾

用一句话总结：ReproPilot 的价值不是“模型说修好了”，而是每个结论都有 PDF 页码、代码行、命令日志、Git diff、测试和确定性评分支持。

最终视频需由项目作者亲自录制，以便能解释每个设计选择；建议剪辑后控制在 5 分钟内。
