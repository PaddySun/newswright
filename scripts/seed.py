"""灌入固定 5 个 RSS 源 + 演示方向/作者配置（任务书 §5.2）。幂等：存在即跳过。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEMO_DIRECTION_PROMPT = """【方向定义：AI 与软件工程】
站长是 AI/软件工程师，以下定义"对站长有价值"的内容标准。

感兴趣的主题（命中越多越相关）：
- AI/LLM 工程实践：RAG、Agent 系统、微调与推理优化、评测方法、提示词工程的一手经验；
- 模型与工具动态：重要新模型发布、开发框架/工具链发布或重大版本、API/基础设施变化；
- 软件工程：开发流程、架构实践、工程质量事件；
- 安全：重要软件安全事件、漏洞披露与修复（含供应链安全）。

质量要求：
- 有一手信息（原创分析、实测、发布公告、漏洞通告）优先于转载与泛泛综述；
- 营销软文、招聘广告、纯活动宣传、与主题无关的社会新闻为低质低相关。

评分口径：quality 评内容本身的信息量与可信度；relevance 评与上述方向的相关程度；两者独立。"""

PERSONA_PROMPT = """你是「墨新」，一位面向中文技术读者的 AI/软件工程评论作者。
文风：观点清晰、直接、有信息密度，不用空洞的排比和营销腔；篇幅 500-900 字。
写作纪律：所有事实性陈述必须来自阅读集，并按引用要求标注来源条目；阅读集里没有的内容不要编造。"""

GLOBAL_SYSTEM_PROMPT = """你是一个 AI 内容生产系统中的作者代理。每次触发你会收到一个阅读集（若干条已抓取并打分的内容）。
你要么写一篇有观点的文章，要么明确决定本期不写（decision=skip）——阅读集里没有值得写的素材时不要硬写。
输出严格按要求的 JSON 结构，不要输出 JSON 以外的任何内容。"""

SOURCES = [
    "https://www.oflight.co.jp/feed.en.xml",
    "https://rss.arxiv.org/rss/cs.CV",
    "https://www.paddysun.top/feed",
    "https://www.cisa.gov/cybersecurity-advisories/all.xml",
    "https://www.ithome.com/rss/",
]

AUTHOR_MODEL = "deepseek-chat"


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.models import Author, Direction, Source

    init_db()
    with SessionLocal() as db:
        direction = db.query(Direction).filter_by(name="AI 与软件工程").one_or_none()
        if direction is None:
            direction = Direction(
                name="AI 与软件工程",
                prompt=DEMO_DIRECTION_PROMPT,
                prompt_version="v1",
                threshold=60,
                enabled=True,
            )
            db.add(direction)
            db.commit()
            print(f"已创建方向 {direction.id}: AI 与软件工程")
        else:
            print(f"方向已存在 {direction.id}，跳过")

        for url in SOURCES:
            if db.query(Source).filter_by(url=url).one_or_none() is None:
                db.add(Source(direction_id=direction.id, url=url, type="rss", enabled=True))
                print(f"已添加源: {url}")
        db.commit()

        if db.query(Author).filter_by(name="墨新").one_or_none() is None:
            db.add(
                Author(
                    name="墨新",
                    model=AUTHOR_MODEL,
                    persona_prompt=PERSONA_PROMPT,
                    global_system_prompt=GLOBAL_SYSTEM_PROMPT,
                    readable_directions=[{"direction_id": direction.id, "threshold": direction.threshold}],
                    memory_config={"feedback_memory": 5, "topic_memory": 3},
                    enabled=True,
                )
            )
            db.commit()
            print("已创建作者: 墨新")
        else:
            print("作者已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
