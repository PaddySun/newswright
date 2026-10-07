"""调度器 job 注册面测试：hot/每日备份/write 兜底三 job 的形态契约。

覆盖口径（AC-20.1 无人值守节奏 + 每日备份 job + write 每分钟兜底 tick，设计
依据见 docs/design-index.md「AC-20.1」）：
- hot 轮 job：执行体接线 _tick_hot、触发间隔 = SCHED_HOT_MINUTES；
- 每日备份 job：执行体接线 _tick_backup、触发间隔 = 24 小时（「每日」语义）；
- write 兜底消费 job：执行体接线 _tick_write_consume、触发间隔 = 1 分钟
  （每分钟兜底消化遗留 PENDING write 任务——F2 异步写作链的恢复入口）。
与 test_score_schedule 的 fetch/score 注册面断言同构（未 start 的 scheduler
上 add_job 仅登记不触发执行）。
"""
from datetime import timedelta

import app.config as cfg
import app.scheduler as sched


def test_register_jobs_hot_backup_write_consume_shape():
    sched._register_jobs()
    try:
        jobs = {j.id: j for j in sched.scheduler.get_jobs()}
        # hot 轮：接线 + 间隔
        hot = jobs["hot_round"]
        assert hot.args[0] is sched._tick_hot
        assert hot.trigger.interval == timedelta(minutes=cfg.SCHED_HOT_MINUTES)
        # 每日备份：接线 + 24 小时间隔
        backup = jobs["daily_backup"]
        assert backup.args[0] is sched._tick_backup
        assert backup.trigger.interval == timedelta(hours=24)
        # write 兜底消费：接线 + 每分钟
        consume = jobs["write_consume"]
        assert consume.args[0] is sched._tick_write_consume
        assert consume.trigger.interval == timedelta(minutes=1)
    finally:
        sched.scheduler.remove_all_jobs()
