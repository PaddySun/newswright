"""作者记忆：memory_entry 读写 + 提示词占位符填充 + 反馈回流转写。

占位符约定：memory_config 形如 {"feedback_memory": 5, "topic_memory": 3}——
键即提示词模板中的 {feedback_memory} 占位符，模块名 = 键去掉 "_memory" 后缀。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Article, Author, MemoryEntry

MODULE_SEPARATOR = "_memory"
EMPTY_PLACEHOLDER_TEXT = "（暂无记录）"


def module_of_placeholder(placeholder: str) -> str:
    return placeholder[: -len(MODULE_SEPARATOR)] if placeholder.endswith(MODULE_SEPARATOR) else placeholder


def load_memory(db: Session, author: Author, module: str, limit: int) -> list[MemoryEntry]:
    return (
        db.query(MemoryEntry)
        .filter_by(author_id=author.id, module=module)
        .order_by(MemoryEntry.id.desc())
        .limit(limit)
        .all()
    )


def render_memory(entries: list[MemoryEntry]) -> str:
    if not entries:
        return EMPTY_PLACEHOLDER_TEXT
    return "\n".join(f"- [{e.created_at:%Y-%m-%d}] {e.content}" for e in entries)


def fill_placeholders(db: Session, author: Author, prompt_text: str) -> str:
    """按 memory_config 把 {占位符} 替换为记忆文本；模板里未配置的占位符原样保留。"""
    for placeholder, limit in (author.memory_config or {}).items():
        entries = load_memory(db, author, module_of_placeholder(placeholder), int(limit))
        prompt_text = prompt_text.replace("{" + placeholder + "}", render_memory(entries))
    return prompt_text


def add_memory(db: Session, author: Author, *, module: str, content: str, source_event: str) -> MemoryEntry:
    entry = MemoryEntry(author_id=author.id, module=module, content=content, source_event=source_event)
    db.add(entry)
    db.commit()
    return entry


def record_feedback(db: Session, article: Article, *, verdict: str, comment: str | None = None) -> MemoryEntry:
    """读者反馈 → 自然语言记忆条目（feedback 模块，回流不做人工筛选）。"""
    if verdict == "like":
        text = f"读者点赞了《{article.title}》，说明这类选题与写法受到认可。"
    elif verdict == "dislike":
        text = f"读者点了踩《{article.title}》，说明这类选题或写法需要改进。"
    elif verdict == "comment":
        # 文字评价（登录态提交）：正文即评语本身，回流语义由评语原文承载
        text = f"读者留言评价了《{article.title}》。"
    else:
        raise ValueError(f"verdict 非法: {verdict}")
    if comment:
        text += f"读者评语：{comment}"
    author = db.get(Author, article.author_id)
    return add_memory(db, author, module="feedback", content=text, source_event="feedback")
