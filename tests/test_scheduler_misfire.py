"""调度器 misfire 显式测试（BE-5/RG-6，P2-4.1）：MISFIRE_GRACE_S 常量 +
全部 add_job 显式 misfire_grace_time——错过 ≤5 分钟补跑、超过跳过（coalesce
已并），替代 APScheduler 隐式默认 1 秒的不可预期形态。

姊妹测试同构形态（未 start 的 scheduler 上 add_job 仅登记不触发执行；
finally remove_all_jobs 收尾——照 test_scheduler_job_registration/
test_score_schedule/test_notify_hub 判例）。
设计依据见 docs/design-index.md「RG-6」（BE-5 增补）。
"""
import app.scheduler as sched

# 任务书钉死：常量 300 秒（条款钉死措辞→精确断言档）
EXPECTED_GRACE = 300

# 全部 add_job 的 job id 清单（app/scheduler.py _register_jobs；任务书 A6 锚点
# 列名六项——「七个」为计数笔误，以 ls/grep 实查为准：六处 add_job 调用）
EXPECTED_JOBS = {
    "fetch_score_round", "score_round_tick", "hot_round",
    "daily_backup", "write_consume", "notify_flush",
}


def test_misfire_grace_constant_pinned():
    assert sched.MISFIRE_GRACE_S == EXPECTED_GRACE


def test_all_jobs_explicit_misfire_grace():
    """七个（实为六个，见模块 docstring 注记）add_job 全部显式
    misfire_grace_time=MISFIRE_GRACE_S——无一遗漏、无一隐式默认。"""
    sched._register_jobs()
    try:
        jobs = {j.id: j for j in sched.scheduler.get_jobs()}
        assert set(jobs) == EXPECTED_JOBS
        for job_id, job in jobs.items():
            assert job.misfire_grace_time == sched.MISFIRE_GRACE_S, job_id
    finally:
        sched.scheduler.remove_all_jobs()
