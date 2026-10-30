from pathlib import Path

from app.ingest.chunking import chunk_documents
from app.ingest.parsers import load_documents


def test_markdown_keeps_tags_inside_code_fences(tmp_path: Path) -> None:
    source = tmp_path / "component.md"
    source.write_text(
        "# 表单弹窗\n\n"
        "模板静态标签直接写 `<mu-form-dialog>`，由解析器按需导入。\n\n"
        "```vue\n"
        '<template>\n  <mu-form-dialog v-model="visible" :model="form" />\n</template>\n'
        "```\n",
        encoding="utf-8",
    )

    documents = load_documents(source)
    text = "\n".join(document.text for document in documents)

    assert "`<mu-form-dialog>`" in text
    assert '<mu-form-dialog v-model="visible" :model="form" />' in text


def test_markdown_tags_survive_chunking(tmp_path: Path) -> None:
    source = tmp_path / "component.md"
    source.write_text(
        "# 表单弹窗\n\n简介。\n\n## 完整示例\n\n"
        '```vue\n<template>\n  <mu-form-dialog v-model="visible" />\n</template>\n```\n',
        encoding="utf-8",
    )

    nodes = chunk_documents(load_documents(source))
    texts = "\n".join(node.get_content() for node in nodes)

    assert "<mu-form-dialog" in texts
    assert "<template>" in texts
