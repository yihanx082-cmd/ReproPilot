# ReproPilot 产品 SQL 面试练习

## 练习数据模型

```sql
users(user_id, signup_at, persona)
runs(run_id, user_id, created_at, completed_at, status, credibility_score)
events(event_id, run_id, occurred_at, event_name, stage, tool_cost_usd)
approvals(approval_id, run_id, decided_at, decision, rationale_is_correct)
```

说明：表名和字段是面试练习模型，不代表当前 MVP 已经采集真实线上用户数据。

## 1. 基础筛选

查询最近 30 天失败或超时的运行：

```sql
SELECT run_id, user_id, created_at, status
FROM runs
WHERE created_at >= CURRENT_DATE - INTERVAL '30 day'
  AND status IN ('FAILED', 'TIMED_OUT')
ORDER BY created_at DESC;
```

## 2. 分组指标

按用户类型计算任务成功率：

```sql
SELECT
  u.persona,
  COUNT(*) AS run_count,
  SUM(CASE WHEN r.status = 'SUCCEEDED' THEN 1 ELSE 0 END) AS succeeded_runs,
  1.0 * SUM(CASE WHEN r.status = 'SUCCEEDED' THEN 1 ELSE 0 END) / COUNT(*) AS success_rate
FROM runs r
JOIN users u ON u.user_id = r.user_id
GROUP BY u.persona;
```

口径：成功率分母是已创建的运行；如果取消任务不应进入分母，必须在题目中先说明。

## 3. 漏斗

计算创建任务、开始运行、看到报告三步漏斗：

```sql
WITH per_run AS (
  SELECT
    run_id,
    MAX(CASE WHEN event_name = 'task_created' THEN 1 ELSE 0 END) AS created,
    MAX(CASE WHEN event_name = 'run_started' THEN 1 ELSE 0 END) AS started,
    MAX(CASE WHEN event_name = 'report_viewed' THEN 1 ELSE 0 END) AS viewed_report
  FROM events
  GROUP BY run_id
)
SELECT
  SUM(created) AS created_runs,
  SUM(started) AS started_runs,
  SUM(viewed_report) AS report_viewers
FROM per_run;
```

陷阱：不要直接按事件行数计数，同一个运行可能重复触发页面事件。

## 4. 次日与七日留存

```sql
WITH activity AS (
  SELECT DISTINCT user_id, CAST(created_at AS DATE) AS activity_date
  FROM runs
), cohort AS (
  SELECT user_id, CAST(signup_at AS DATE) AS signup_date
  FROM users
)
SELECT
  c.signup_date,
  COUNT(*) AS new_users,
  COUNT(DISTINCT CASE WHEN a.activity_date = c.signup_date + INTERVAL '1 day' THEN c.user_id END) AS d1_users,
  COUNT(DISTINCT CASE WHEN a.activity_date = c.signup_date + INTERVAL '7 day' THEN c.user_id END) AS d7_users
FROM cohort c
LEFT JOIN activity a ON a.user_id = c.user_id
GROUP BY c.signup_date
ORDER BY c.signup_date;
```

## 5. ReproPilot 专属分析题

1. 比较需要人工审批和不需要审批的运行完成时长，中位数为什么比均值更合适？
2. 找出在哪个状态机阶段退出的运行最多；分母应是所有运行还是进入该阶段的运行？
3. 计算每个成功运行的平均工具成本，并同时报告 P50、P90。
4. 检查“高可信度分数但运行失败”的数据质量异常。
5. 比较原型改版前后，把可信度误认为准确率的人数；为什么 5 人样本不能做总体外推？

## 面试答题方法

先说清实体、时间窗口、分母和去重键，再写 SQL。写完主动检查 NULL、重复事件、取消任务、跨天时区和样本偏差。产品分析的重点不是背语法，而是让查询结果与业务问题使用同一口径。
