# ReproPilot Figma 交接说明

这份文档用于把已经通过浏览器验证的本地原型等价重建为 Figma 可点击原型。Figma 文件本身需要在用户账号中创建或导入；这里固定画板、视觉令牌、组件和跳转，避免二次设计时偏离已验证流程。

## 画板

统一使用 Desktop `1440 × 900`，建立以下五个顶层 Frame，名称必须保持一致：

1. **Task Creation**
2. **Scope Review**
3. **Execution Timeline**
4. **Approval**
5. **Credibility Report**

另建 `Components` 页面保存按钮、状态标签、阶段行、证据卡、表格行和评分条组件。

## 视觉令牌

| Token | 值 | 用途 |
|---|---|---|
| Ink | `#172033` | 主文字 |
| Muted | `#687386` | 次级说明 |
| Line | `#DFE4EC` | 边框与分隔线 |
| Surface | `#FFFFFF` | 卡片与面板 |
| Subtle | `#F7F9FB` | 页面底色、次级区域 |
| Blue | `#2457D6` | 主操作、当前选择 |
| Green | `#187A55` | verified / 通过 |
| Amber | `#A85B08` | warning / 等待审批 |
| Amber Surface | `#FFF7E8` | 风险提示背景 |
| Red | `#B42318` | failed / 拒绝 |

字体使用 Inter；Windows 无 Inter 时用 Segoe UI。页面标题 24/32 semibold，区块标题 16/24 semibold，正文 14/22 regular，辅助文字 12/18 regular，数字评分 40/44 semibold。

## 布局

- 页面外边距：32 px；顶部导航高 64 px；
- 内容最大宽度：1376 px；卡片圆角 12 px；边框 1 px；
- Execution Timeline 使用三列：阶段列表 `260 px`、事件详情自适应、证据面板 `360 px`；列间距 16 px；
- 1024 px 宽度下保持桌面布局，但允许中间列收缩；不制作移动端变体。

## Frame 内容

### Task Creation

展示论文、仓库、数据集、环境与运行范围输入。主按钮为 `Review scope`，字段旁用普通语言解释输入的底层作用。

### Scope Review

展示论文声明、代码事实、match/mismatch/unknown 状态、资源限制与未解决假设。主按钮为 `Start reproduction`，次按钮为 `Back`。

### Execution Timeline

左列按顺序展示环境、最小运行、诊断、补丁、验证、实验、比较与评分。中列展示当前事件的原因和影响，右列显示 argv、日志、Git diff、测试和 artifact ID。等待审批的阶段使用 Amber 状态。

### Approval

展示高风险原因、补丁 SHA-256、精确 diff、语义影响和针对性测试。提供 `Approve patch` 与 `Reject with reason`。批准前 Credibility Report 不可访问。

### Credibility Report

展示 `80/100 PARTIAL`、七个评分维度、论文值与观测值、差值、已修复问题和未解决风险。分数旁固定文案：`Credibility score — not model accuracy.`

## Prototype 跳转

| 起点 | 触发 | 终点 |
|---|---|---|
| Task Creation | 点击 `Review scope` | Scope Review |
| Scope Review | 点击 `Back` | Task Creation |
| Scope Review | 点击 `Start reproduction` | Execution Timeline |
| Execution Timeline | 点击任意阶段 | 同 Frame 的对应事件 Overlay/Variant |
| Execution Timeline | 点击 waiting approval 事件 | Approval |
| Approval | 点击 `Approve patch` | Execution Timeline（approved variant） |
| Approval | 点击 `Reject with reason` | Execution Timeline（rejected variant） |
| Execution Timeline approved variant | 点击 `Open report` | Credibility Report |
| Credibility Report | 点击 `Back to timeline` | Execution Timeline approved variant |

使用 Smart Animate，200 ms，Ease Out。审批按钮的交互结果必须绑定对应 approved/rejected variant；禁止从未审批时间线直接连到报告。

## 重建验收

- 五个 Frame 都能从 Task Creation 连续到达；
- 未批准高风险补丁时不能打开报告；
- `80/100` 附近始终出现“not model accuracy”；
- Execution Timeline 保持三栏信息结构；
- 文案、数值和状态与 `prototype/data/demo-run.json` 一致；
- 与 `assets/prototype-timeline.png`、`assets/prototype-report.png` 在 1440 × 900 下进行视觉对照。

