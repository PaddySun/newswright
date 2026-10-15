"""LLM 提供方切换冒烟（统筹亲执，2026-10-15；C4-3/W5 转正为常驻验收工具）。

目的：为外部服务治理整改批提供实测依据——
1. deepseek 官方与 moark 聚合平台经同一条传输脊（providers.base 的重试+计量壳）
   各完成一次纯文本调用与一次 strict-JSON 调用，验证「切换 = 提供方名字一处
   变化」的选源机制成立；
2. moark 的 chat 通道按 OpenAI 兼容形态（/v1/chat/completions）实测可用，
   为「moark 作为 LLM 提供方」落码提供协议依据；
3. 顺带核验 moark 另两条能力通道（向量生成 /v1/embeddings、Jev 决策
   /v1/systemone）在当前凭据下可用；
4. 全部调用经 usage_log 落账，核对 provider 字段归因正确（计量纪律不断链）。

实测记录（2026-10-15 晚窗口，统筹亲执）：
1. 排查过程中确认 moark 的 chat 端点为 /v1/chat/completions——路径前缀是
   厂商差异（deepseek 官方 base 不带 /v1，OpenAI 系与 moark 带）；误用
   /chat/completions 会被网关 302 到营销站（空 body），且当夜生产传输脊
   _post_json 只拦 429/5xx/>=400，3xx 漏网成「成功空响应」——两项均记
   入整改任务书，并已随传输脊批落地（非 2xx 一律入错）。
2. moark chat 真实存在间歇性长挂起（同参数请求交替 2.5-6s 正常返回与
   45s+ 读超时），故本脚本在传输层重试外叠加脚本级重试（尝试次数如实
   计入证据行）；该现象即「moark 宜作 chat 备源、deepseek 主源」的现实依据。

C4-3/W5 转正说明（2026-10-16）：
- 删除冒烟层的 3xx 拦截补丁与参考适配器 MoarkChatSmoke——传输脊已非 2xx
  全入错（3xx 拦截上提后脚本层冗余），moark chat 正式适配器落在
  app/providers/moark_chat.py（路径前缀 /v1、response_format 兼容阀、
  计量 model 回显皆为生产实现）；
- 选源改走真选源层 app/providers/resolve（deepseek=resolve("deepseek")、
  moark=resolve("moark")），消费方零具体厂商 import——与生产接线完全同形；
- usage_log 断言集合不变，另增「moark chat 行 model 非空」断言（计量回显
  修复的顺带验证；统筹 2026-10-15 冒烟时该列实测为空，是计量空洞的旧账面）。

运行：.venv/Scripts/python -X utf8 scripts/c4_smoke_provider_switch.py
（依赖仓库根 .env 的 DeepSeekAPIKey / MoarkAPIKey；密钥不回显不落日志。
 账目落临时 sqlite，结束即删，不碰生产库。）
架构依据见 doc/外部AI服务集成架构建议-Python通用.md §6/§9（选源层与切换判定）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config  # noqa: E402  （导入即完成 .env 容错解析与必需键校验）
from app.embedding.moark import MoarkEmbeddingProvider  # noqa: E402
from app.models import Base, UsageLog  # noqa: E402
from app.providers.moark_jev import MoarkJevProvider  # noqa: E402
from app.providers.resolve import resolve as _resolve  # noqa: E402

# moark 侧 chat 模型候选（按序探测，首个可用者胜出）：
# 首选 deepseek-v4.1-flash——与官方 deepseek 同族，跨厂商对照语义最干净
MOARK_CHAT_MODEL_CANDIDATES = [
    os.environ.get("MOARK_SMOKE_CHAT_MODEL", "deepseek-v4.1-flash"),
    "GLM-5.3-Flash",
    "qwen3.8-flash",
]
SCRIPT_TRIES = 3          # 脚本级重试（吸收平台间歇性空响应/挂起）
RETRY_DELAY_SECONDS = 2.0


def resolve_llm(name: str, db, *, moark_model: str | None = None):
    """真选源层接线：消费方只见名字，切换 = 一处字符串变化。deepseek 走
    缺省模型；moark 侧探测期按 model 出变体（与生产 variant 语义一致）。"""
    if name == "deepseek":
        return _resolve("deepseek", db)
    if name == "moark":
        return _resolve("moark", db, model=moark_model)
    raise KeyError(name)


RESULTS: list[tuple[str, str, str]] = []  # (检查项, PASS/FAIL, 证据摘要)


def check(item: str, ok: bool, evidence: str) -> bool:
    RESULTS.append((item, "PASS" if ok else "FAIL", evidence))
    print(f"  [{'PASS' if ok else 'FAIL'}] {item} — {evidence}")
    return ok


def with_script_retries(fn, *, tries: int = SCRIPT_TRIES, what: str = ""):
    """脚本级重试：传输层已重试过 httpx 类失败；这里额外吸收「空 200 体」
    （JSONDecodeError/空 content）与残余挂起——每次失败计数并短暂退避。"""
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            out = fn()
            return out, attempt
        except Exception as e:  # noqa: BLE001  冒烟脚本：一切失败形态都换尝试计数
            last = e
            if attempt < tries:
                time.sleep(RETRY_DELAY_SECONDS * attempt)
    raise RuntimeError(f"{what} 脚本级重试 {tries} 次耗尽: "
                       f"{type(last).__name__}: {str(last)[:160]}") from last


def main() -> int:
    fd, db_path = tempfile.mkstemp(suffix=".smoke.db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    print(f"== 冒烟开始 {time.strftime('%Y-%m-%d %H:%M:%S')}（账目落临时库 {Path(db_path).name}）==")

    # ---- 步骤 0：moark chat 模型探测（候选 × 脚本级重试，首个成功者定档） ----
    print("== 0. moark chat 模型探测（/v1/chat/completions，OpenAI 兼容） ==")
    moark_model, probe_tries = None, 0
    for cand in MOARK_CHAT_MODEL_CANDIDATES:
        try:
            def _probe(m=cand):
                p = resolve_llm("moark", db, moark_model=m)
                return p.chat(
                    [{"role": "user", "content": "只回复两个字：pong"}],
                    call_point="smoke_probe", temperature=0.0, max_retries=1)
            (text, echoed), tries = with_script_retries(_probe, what=f"候选 {cand}")
            print(f"  候选 {cand} → 可用（{tries} 次尝试；回显模型 {echoed}，输出 {text[:30]!r}）")
            moark_model, probe_tries = cand, tries
            break
        except Exception as e:  # noqa: BLE001  该候选放弃，换下一个
            print(f"  候选 {cand} → 不可用（{str(e)[:140]}）")
    if not check("moark chat 通道（OpenAI 兼容）", moark_model is not None,
                 f"选定 {moark_model}（探测尝试 {probe_tries} 次）"):
        _report(db)
        _cleanup(db_path)
        return 1

    # ---- 步骤 1：双提供方切换（同一任务电池：纯文本 + strict JSON） ----
    for name in ("deepseek", "moark"):
        print(f"== 1. 提供方 [{name}] 同一任务电池 ==")
        t0 = time.monotonic()

        def battery(name=name):
            provider = resolve_llm(name, db, moark_model=moark_model)
            text1, m1 = provider.chat(
                [{"role": "user", "content": "只回复两个字：pong"}],
                call_point="smoke_chat", temperature=0.0, max_retries=1)
            data, m2 = provider.chat_json(
                [{"role": "user",
                  "content": '只输出 JSON 对象 {"ok": true, "n": 4}，不要输出其他内容'}],
                call_point="smoke_json", temperature=0.0, max_tokens=200, max_retries=1)
            return text1, m1, data, m2

        try:
            (text1, m1, data, m2), tries = with_script_retries(battery, what=f"{name} 电池")
            ms = int((time.monotonic() - t0) * 1000)
            check(f"{name} 纯文本调用", "pong" in text1.lower(),
                  f"输出 {text1[:40]!r}（模型回显 {m1}）")
            check(f"{name} strict-JSON 调用",
                  isinstance(data, dict) and data.get("ok") is True and data.get("n") == 4,
                  f"解析 {str(data)[:60]}（模型回显 {m2}）")
            print(f"  （{tries} 次电池尝试，合计 {ms}ms）")
        except Exception as e:  # noqa: BLE001
            check(f"{name} 任务电池", False, str(e)[:200])

    # ---- 步骤 2：moark 另两条能力通道 ----
    print("== 2. moark 向量与 Jev 决策通道 ==")

    def _embed():
        vecs = MoarkEmbeddingProvider(db).embed(
            ["冒烟：标题\n正文一句话，验证向量通道。"],
            expected_dims=config.EMBED_DIMENSIONS, call_point="smoke_embed")
        return vecs[0]
    try:
        v, tries = with_script_retries(_embed, what="embedding")
        check("moark 向量通道",
              len(v) == config.EMBED_DIMENSIONS and any(abs(x) > 1e-9 for x in v),
              f"维度 {len(v)}（期望 {config.EMBED_DIMENSIONS}）非零（{tries} 次尝试）")
    except Exception as e:  # noqa: BLE001
        check("moark 向量通道", False, str(e)[:200])

    def _jev():
        return MoarkJevProvider(db).decide(
            state="某公司发布了新一款开源语言模型，性能提升显著。",
            questions={"q1": {"type": "choice",
                              "instructions": "判断该内容属于哪一类",
                              "criteria": {"科技": "科技与工程进展", "其他": "非科技内容"}}},
            call_point="smoke_jev", max_retries=1)
    try:
        out, tries = with_script_retries(_jev, what="jev")
        a = out["answers"]["q1"]
        check("moark Jev 决策通道", a["choice"] in ("科技", "其他"),
              f"choice={a['choice']} confidence={a['confidence']:.2f} "
              f"billing_units={out['usage']['billing_units']}（{tries} 次尝试）")
    except Exception as e:  # noqa: BLE001
        check("moark Jev 决策通道", False, str(e)[:200])

    _report(db)
    _cleanup(db_path)
    failures = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"== 冒烟结束：{len(RESULTS) - len(failures)} PASS / {len(failures)} FAIL ==")
    return 1 if failures else 0


def _report(db) -> None:
    print("== usage_log 落账核验（provider 归因） ==")
    rows = db.query(UsageLog).order_by(UsageLog.id).all()
    for r in rows:
        print(f"  #{r.id} provider={r.provider:<12} model={r.model:<28} "
              f"call_point={r.call_point:<12} ok={r.ok} "
              f"tok={r.prompt_tokens}/{r.completion_tokens} {r.latency_ms}ms")
    providers = {r.provider for r in rows}
    check("计量归因完整（四类提供方各就位）",
          {"deepseek", "moark", "moark_embed", "moark_jev"} <= providers,
          f"账面 provider 集合 = {sorted(providers)}")
    moark_chat_models = [r.model for r in rows
                         if r.provider == "moark" and r.call_point.startswith("smoke")]
    check("moark chat 计量 model 回显非空（计量空洞治理）",
          bool(moark_chat_models) and all(moark_chat_models),
          f"moark chat 行 model 列 = {moark_chat_models}（统筹 2026-10-15 冒烟时该列实测为空）")


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
