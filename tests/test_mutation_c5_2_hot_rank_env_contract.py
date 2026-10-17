"""热榜候选排序过滤三键契约（config.hot_rank_* 读取函数）。

背景（热榜治理批）：三 env 读取自 hot 模块原位上提归口 config——读取面
等价（调用时读取、时机不变）是平移的硬契约：开关真值集合（1/true/yes/on）、
键名 HOT_RANK_MIN_SCORE / HOT_RANK_PROVIDER、缺省值（40 / bocha_jev）
都与平移前逐字一致（git 历史可核）。本文件按技术书 §6.13 新增配置键表
逐键对照断言——设了要生效、缺省值不漂移。
设计依据见 docs/design-index.md「HR-4」与《技术设计书-正式-TDD》§6.13
配置键表（HOT_RANK_FILTER / HOT_RANK_PROVIDER / HOT_RANK_MIN_SCORE）。
"""
import pytest

from app.config import (
    hot_rank_filter_enabled,
    hot_rank_min_score,
    hot_rank_provider_name,
)


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_hot_rank_filter_enabled_accepts_all_on_forms(monkeypatch, value):
    """HOT_RANK_FILTER 开关真值域：1/true/yes/on 四形态全部识别为开
    （平移前真值集合逐字一致——缺一即「设了却不生效」）。"""
    monkeypatch.setenv("HOT_RANK_FILTER", value)
    assert hot_rank_filter_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_hot_rank_filter_enabled_rejects_off_forms(monkeypatch, value):
    """关闭/非法值不开启（默认关）。"""
    monkeypatch.setenv("HOT_RANK_FILTER", value)
    assert hot_rank_filter_enabled() is False


def test_hot_rank_min_score_reads_env_when_set(monkeypatch):
    """HOT_RANK_MIN_SCORE 显式配置生效（键名精确——排序最低保留分
    按配置读取，不得恒回落缺省）。
    以大小写敏感的纯 dict 整体替换 os.environ：Windows 环境块键大小写
    不敏感，键名大小写变异在真实 os.environ 下不可观测（目标平台
    Ubuntu 可观测——测试须与目标平台语义对齐）。"""
    import os
    monkeypatch.setattr(os, "environ", {"HOT_RANK_MIN_SCORE": "75"})
    assert hot_rank_min_score() == 75


def test_hot_rank_min_score_default_is_40(monkeypatch):
    """缺省 40：未配置时最低保留分为 40（配置键表钉死的缺省值）。"""
    monkeypatch.delenv("HOT_RANK_MIN_SCORE", raising=False)
    assert hot_rank_min_score() == 40


def test_hot_rank_provider_name_default_is_bocha_jev(monkeypatch):
    """HOT_RANK_PROVIDER 缺省 bocha_jev：未配置时排序提供方名为
    bocha_jev（配置键表钉死的缺省值，逐字一致）。"""
    monkeypatch.delenv("HOT_RANK_PROVIDER", raising=False)
    assert hot_rank_provider_name() == "bocha_jev"
