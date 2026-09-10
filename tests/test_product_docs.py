from pathlib import Path

PRODUCT_DOCS = Path(__file__).parents[1] / "docs" / "product"


def test_research_kit_has_required_sections() -> None:
    interview = (PRODUCT_DOCS / "interview-kit.md").read_text(encoding="utf-8")
    records = (PRODUCT_DOCS / "research-records" / "README.md").read_text(
        encoding="utf-8"
    )
    findings = (PRODUCT_DOCS / "research-findings.md").read_text(encoding="utf-8")
    for heading in ["Round One", "Round Two", "Consent", "Anonymization"]:
        assert heading in interview
    for participant in ["P01", "P02", "P03", "P04", "P05"]:
        assert participant in records
    assert "5/5" in findings
    assert "statistically representative" in findings


def test_real_research_records_are_traceable_and_bounded() -> None:
    records_dir = PRODUCT_DOCS / "research-records"
    for participant in ["P01", "P02", "P03", "P04", "P05"]:
        record = (records_dir / f"{participant}.md").read_text(encoding="utf-8")
        assert "同意状态：已同意" in record
        assert "可用于汇总的证据" in record
        assert f"{participant}-E" in record
    findings = (PRODUCT_DOCS / "research-findings.md").read_text(encoding="utf-8")
    assert "独立完成核心流程 | 3/5" in findings
    assert "误认为模型准确率 | 2/5" in findings
    assert "3.8/5" in findings
    assert "不做显著性检验" in findings


def test_metrics_and_usability_are_measurable() -> None:
    metrics = (PRODUCT_DOCS / "metrics-plan.md").read_text(encoding="utf-8")
    usability = (PRODUCT_DOCS / "usability-test.md").read_text(encoding="utf-8")
    for metric in [
        "Task completion rate",
        "Time to interpret",
        "Manual steps reduced",
        "Decision correctness",
        "Report comprehension",
        "Satisfaction",
    ]:
        assert metric in metrics
    assert "4 of 5" in usability
    assert "credibility score" in usability
    assert "model accuracy" in usability
    assert "未达到" in usability
    assert "3/5" in usability


def test_competitor_analysis_and_prd_are_bounded() -> None:
    competitors = (PRODUCT_DOCS / "competitor-analysis.md").read_text(encoding="utf-8")
    prd = (PRODUCT_DOCS / "prd.md").read_text(encoding="utf-8")
    assert "Primary sources" in competitors
    assert "Manual workflow" in competitors
    assert "Coding agents" in competitors
    for heading in [
        "Problem",
        "Target User",
        "Requirements",
        "Non-goals",
        "Risks",
        "Acceptance Criteria",
    ]:
        assert heading in prd
    assert "cloud GPU scheduling" in prd


def test_case_study_preserves_evidence_boundaries() -> None:
    case_study = (PRODUCT_DOCS / "case-study.md").read_text(encoding="utf-8")
    handoff = (PRODUCT_DOCS / "figma-handoff.md").read_text(encoding="utf-8")
    script = (PRODUCT_DOCS / "demo-video-script.md").read_text(encoding="utf-8")
    assert "5 位" in case_study
    assert "6/6" in case_study
    assert "80/100" in case_study
    for frame in [
        "Task Creation",
        "Scope Review",
        "Execution Timeline",
        "Approval",
        "Credibility Report",
    ]:
        assert frame in handoff
    assert "not model accuracy" in script.lower()


def test_readme_links_product_case_with_bounded_research_claims() -> None:
    readme = (PRODUCT_DOCS.parents[1] / "README.md").read_text(encoding="utf-8")
    for link in [
        "docs/product/prd.md",
        "docs/product/competitor-analysis.md",
        "docs/product/interview-kit.md",
        "docs/product/metrics-plan.md",
        "docs/product/case-study.md",
        "prototype/README.md",
    ]:
        assert link in readme
    assert "3/5 无帮助独立完成" in readme
    assert "低于预设可用性门槛" in readme


def test_job_and_sql_materials_keep_claims_bounded() -> None:
    job_kit = (PRODUCT_DOCS / "job-kit.md").read_text(encoding="utf-8")
    sql_practice = (PRODUCT_DOCS / "sql-practice.md").read_text(encoding="utf-8")
    for required in ["30 秒介绍", "3 分钟 STAR", "80/100 怎么算", "一个失败或取舍案例"]:
        assert required in job_kit
    assert "不能宣称通用自动复现" in job_kit
    for topic in ["基础筛选", "分组指标", "漏斗", "次日与七日留存"]:
        assert topic in sql_practice
    assert "不代表当前 MVP 已经采集真实线上用户数据" in sql_practice
