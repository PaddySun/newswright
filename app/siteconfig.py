"""site_config 读写助手（G1/W1）：键带代码内默认值，缺失行不落库（读时回退）。

本里程碑仅两键（技术书 §4.1 site_config 预留全部未来键空间，公开 API 属 US-19 后续）：
- session_duration_days：会话保持期限（天），默认 7（AC-01.4）
- client_ip_header：真实客户端 IP 提取头名（ADR-5⑤），空 = 直连 request.client.host
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import SiteConfig

DEFAULTS: dict[str, object] = {
    "session_duration_days": 7,
    "client_ip_header": "",
    # 新源首导打分窗口（天）：site_config 可调；source_config.first_ingest_days 逐源覆盖
    "first_ingest_days": 7,
    # 语义近重复判定阈值：0.92 为示例值（qwen06 标定结果），按金标分模型标定；
    # 换嵌入模型（model_version 变更）时必须重新标定
    "semantic_dedup_threshold": 0.92,
    # 方向路由每轮命中桶容量：检索相似度 top-K 优先打分的条目数
    "retrieval_top_k": 5,
    # 探索层全局开关与参数（默认关；以下数值全部为示例值，正式值实测后定）：
    # quality_floor=质量分地板；distance_percentile=与方向相似度的最低分位（P5）；
    # quota_per_page=B 流每页探索条目配额上限
    "explore_enabled": False,
    "explore_quality_floor": 50,
    "explore_distance_percentile": 5,
    "explore_quota_per_page": 3,
    # Token 日预算闸（默认 0 = 不设限）：当日 usage_log token 汇总达预算即按
    # "低优先级先停"秩序降级（探索→嵌入→打分慢速→写作确认）；采集与呈现不降级
    "daily_token_budget": 0,
    # 预算触发后的打分慢速轮上限（继续低速、绝不整轮停摆）
    "score_slow_round_max_items": 20,
    # 健康自省 503 阈值：抓取停滞分钟数（部署后 60 分钟冷启动宽限内不触发）与
    # 待处理任务堆积数
    "healthz_fetch_stale_minutes": 90,
    "healthz_pending_stale_count": 500,
    # 备份目录（本地目录备份插件产物位置；轮转保留 ≥7 份）
    "backup_dir": "backups",
    # 通知触发开关（US-19：GET /api/settings/notify 回显；未配置 SMTP 时事件仅落日志）
    "notify_on_source_failure": True,
    "notify_on_token_budget": True,
    "notify_on_collective": True,
    "notify_on_disk": True,
    # 磁盘用量告警阈值（百分比）
    "disk_usage_warn_percent": 80,
}


def get_config(db: Session, key: str):
    """读配置：无行回退代码内默认值；键未知返回 None。"""
    row = db.get(SiteConfig, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key)


def set_config(db: Session, key: str, value) -> None:
    """写配置（upsert）。"""
    row = db.get(SiteConfig, key)
    if row is None:
        row = SiteConfig(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
