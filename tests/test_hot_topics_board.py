"""热榜最新一轮平台榜测试（UI2 W0c / P9 热点页数据面）。

契约：GET /api/hot/topics?limit=20 = 最新一轮（hot 写入侧每轮逐条显式填
batch_id，一轮=一个 batch——取 MAX(batch_id) 轮全体；同轮 fetched_at 逐条
独立落库互有微差，不可作同轮判据）的平台分组榜：平台内 rank 升序、截 limit
（默认 20 上限 50）；heat 从 extra 的 info/hover 键归一（键形核实=app/hot/
service.py 关键词输入构造是 extra 的唯二消费点），取不到 null；extra 原样
透出；空表 200 空态。
"""
from datetime import datetime, timedelta, timezone

from app.models import HotBatch, HotTopic


def _mk_round(db, *, date: str, fetched_base: datetime,
              platforms: dict[str, list[dict]]) -> int:
    """造一轮热榜：每平台若干条（extra/keyword_contrib 可指定），返回 batch_id。"""
    batch = HotBatch(date=date, keywords=[], summary="",
                     source_platforms=list(platforms), model="")
    db.add(batch)
    db.flush()
    for platform, topics in platforms.items():
        for i, spec in enumerate(topics, start=1):
            db.add(HotTopic(
                platform=platform, rank=i,
                title=spec.get("title", f"{platform}话题{i}"),
                url=spec.get("url"), extra=spec.get("extra"),
                keyword_contrib=spec.get("keyword_contrib", False),
                fetched_at=fetched_base + timedelta(milliseconds=i * 10),
                batch_id=batch.id))
    db.commit()
    return batch.id


def test_hot_topics_latest_round_grouped_ranked_limited(auth_client, db_session):
    """平台分组 + rank 升序 + limit 截断 + heat 归一 + extra 透出 + 旧轮不混入。"""
    old_base = datetime.now(timezone.utc) - timedelta(hours=2)
    new_base = datetime.now(timezone.utc) - timedelta(minutes=5)
    _old = _mk_round(db_session, date="2026-10-13", fetched_base=old_base,
                     platforms={"weibo": [{"title": "旧轮条目", "extra": {"info": "9999999"}}]})
    _new = _mk_round(db_session, date="2026-10-14", fetched_base=new_base,
                     platforms={
                         "weibo": [
                             {"title": "微博榜首", "url": "https://weibo/1",
                              "extra": {"info": "123456"}, "keyword_contrib": True},
                             {"title": "微博次席", "url": "https://weibo/2",
                              "extra": {"info": "abc", "hover": "3.5"}, "keyword_contrib": True},
                             {"title": "微博第三", "extra": {"info": "2.5万"}},  # 不可解析 → null
                         ],
                         "baidu": [
                             {"title": "百度榜首", "extra": {"hover": 88.5}},
                             {"title": "百度次席"},  # 无 extra → null
                         ],
                     })
    r = auth_client.get("/api/hot/topics", params={"limit": 2})
    assert r.status_code == 200
    body = r.json()
    # 顶层 fetched_at = 最新一轮内最大落库时间（同轮微差集合的上界）
    assert body["fetched_at"] is not None
    assert body["fetched_at"].startswith(new_base.strftime("%Y-%m-%dT"))
    platforms = {p["platform"]: p["topics"] for p in body["platforms"]}
    assert set(platforms) == {"weibo", "baidu"}  # 旧轮平台条目不混入
    # limit=2 每平台截前两名（rank 升序）
    assert [t["rank"] for t in platforms["weibo"]] == [1, 2]
    assert [t["rank"] for t in platforms["baidu"]] == [1, 2]
    assert platforms["weibo"][0]["title"] == "微博榜首"
    # heat 归一：数值字符串解析 / info 失效回落 hover / 不可解析 null
    assert platforms["weibo"][0]["heat"] == 123456.0
    assert platforms["weibo"][1]["heat"] == 3.5
    assert platforms["baidu"][0]["heat"] == 88.5  # 数值型直取（hover 键）
    # 被截断的第三条不出现（heat 不可解析形态不在此断言，见下一用例）
    assert all(t["title"] != "微博第三" for t in platforms["weibo"])
    # keyword_contrib / url / extra 原样透出
    top = platforms["weibo"][0]
    assert top["keyword_contrib"] is True and top["url"] == "https://weibo/1"
    assert top["extra"] == {"info": "123456"}


def test_hot_topics_unparsable_heat_null(auth_client, db_session):
    """heat 取不到（无 extra / 值不可数值解析）→ null，不误报 0。"""
    base = datetime.now(timezone.utc)
    _mk_round(db_session, date="2026-10-14", fetched_base=base,
              platforms={"weibo": [
                  {"title": "无热度"},                       # 无 extra
                  {"title": "中文倍率", "extra": {"info": "2.5万"}},  # 非纯数字串
                  {"title": "空串", "extra": {"info": ""}},
              ]})
    topics = auth_client.get("/api/hot/topics").json()["platforms"][0]["topics"]
    assert [t["heat"] for t in topics] == [None, None, None]
    assert topics[0]["url"] is None


def test_hot_topics_limit_clamped_and_default(auth_client, db_session):
    """limit 上限 50 钳制（截断行为不变）；默认 20。"""
    base = datetime.now(timezone.utc)
    _mk_round(db_session, date="2026-10-14", fetched_base=base,
              platforms={"p": [{"title": f"条目{i}"} for i in range(1, 61)]})
    body = auth_client.get("/api/hot/topics").json()
    assert len(body["platforms"][0]["topics"]) == 20  # 默认 20
    body = auth_client.get("/api/hot/topics", params={"limit": 999}).json()
    assert len(body["platforms"][0]["topics"]) == 50  # 上限 50 钳制
    assert body["platforms"][0]["topics"][0]["rank"] == 1  # rank 升序
    assert body["platforms"][0]["topics"][-1]["rank"] == 50


def test_hot_topics_empty_state(auth_client):
    """空表 → 200 {"fetched_at": null, "platforms": []}（空态不用错误码）。"""
    r = auth_client.get("/api/hot/topics")
    assert r.status_code == 200
    assert r.json() == {"fetched_at": None, "platforms": []}
