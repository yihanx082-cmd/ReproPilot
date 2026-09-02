# ReproPilot Architecture

## 核心原则

ReproPilot 把大模型限制在两个需要语义理解的位置：从 PDF 提取结构化声明、根据已有诊断提出最小补丁。命令策略、补丁风险、Git 事务、评分和状态转换均由确定性代码控制。

```mermaid
flowchart TD
    A["RunRequest: PDF + repository + dataset + argv"] --> B["ArtifactStore"]
    B --> C["Paper extraction with page evidence"]
    B --> D["Repository scanner"]
    C --> E["Paper/code alignment"]
    D --> E
    E --> F["DockerSandbox build and smoke run"]
    F -->|"exit 0"| K["Metric comparison"]
    F -->|"failure"| G["Deterministic diagnosis"]
    G --> H["Patch proposal"]
    H --> I{"Local risk policy"}
    I -->|"low"| J["Git apply + targeted test"]
    I -->|"high"| P["SHA-bound user approval"]
    P --> J
    J -->|"pass"| F
    J -->|"fail"| R["Exact rollback"]
    R --> G
    K --> L["Deterministic 100-point score"]
    L --> M["Self-contained HTML report"]
```

## 状态与证据

`ReproPilot` 是显式状态机：`INGEST → AUDIT → BUILD → SMOKE_RUN → DIAGNOSE → APPLY_PATCH → VERIFY → COMPARE → SCORE → REPORT`。高风险补丁进入 `WAITING_APPROVAL`，审批和补丁 SHA-256 一起持久化，因此进程退出后仍可恢复。

`run.json` 保存当前状态，`events.jsonl` 追加事件；其余 JSON、日志和 HTML 都是可定位的 artifact。状态转换先记录，再执行副作用，便于中断审计。

## 安全边界

| 层 | 约束 |
|---|---|
| CLI | Pydantic 校验配置；命令使用 argv，不经过 shell |
| Docker | 非 root、无网络、只读根、能力移除、CPU/内存/PID/超时限制 |
| 文件 | 原仓库与数据集只读；补丁只进入工作副本 |
| 补丁 | Git diff 校验、允许路径、诊断文件交集、最多 3 个文件/120 行 |
| 语义 | 数据、指标、模型、权重修改必须审批 |
| 事务 | 先保存工作区哈希；测试失败反向应用补丁并校验完全恢复 |
| 结论 | 缩小实验永远不能标记 `REPRODUCED` |

## 模块映射

- `paper.py`：PDF 页面文本、结构化模型输出、逐页原文证据验证。
- `repository.py` / `alignment.py`：YAML、JSON、TOML、argparse、README 扫描与差异检测。
- `sandbox.py`：Docker CLI 隔离和日志脱敏。
- `diagnosis.py` / `policy.py` / `patching.py`：错误分类、风险门和 Git 事务。
- `orchestrator.py` / `services.py`：状态机与真实服务接线。
- `scoring.py` / `reporting.py`：可信度评分和单文件 HTML 报告。
- `benchmark.py`：故障注入评测指标与 reference harness。

## MVP 边界

本版本不包含多 Agent、Web 控制台、Kubernetes、完整 GPU 调度、自动数据许可处理或未知仓库上的公开模型基准。它优先证明一个小而完整、证据可追踪、安全边界明确的 Coding Agent 闭环。
