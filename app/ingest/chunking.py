from __future__ import annotations

from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import TextNode

from app.config import settings

TABLE_SUFFIXES = {".xlsx", ".xls", ".csv"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}


def _splitter(chunk_size: int | None = None, chunk_overlap: int | None = None):
    return SentenceSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=chunk_overlap if chunk_overlap is not None else settings.chunk_overlap,
    )


def chunk_documents(documents: list[Document]) -> list[TextNode]:
    nodes: list[TextNode] = []
    markdown_parser = MarkdownNodeParser()

    for document in documents:
        suffix = Path(document.metadata.get("file_path", "")).suffix.lower()
        text = (document.text or "").strip()
        if not text:
            continue

        if suffix in TABLE_SUFFIXES:
            # Keep each table/row document intact; splitting rows would lose the header.
            nodes.append(
                TextNode(
                    text=text,
                    metadata={**document.metadata},
                )
            )
            continue

        if suffix in MARKDOWN_SUFFIXES:
            section_nodes = markdown_parser.get_nodes_from_documents([document])
            for section in section_nodes:
                section_text = (section.get_content() or "").strip()
                if not section_text:
                    continue
                if len(section_text) <= settings.chunk_size:
                    nodes.append(
                        TextNode(
                            text=section_text,
                            metadata={**document.metadata, **section.metadata},
                        )
                    )
                else:
                    sub_nodes = _splitter().get_nodes_from_documents(
                        [
                            Document(
                                text=section_text,
                                metadata={**document.metadata, **section.metadata},
                            )
                        ]
                    )
                    nodes.extend(sub_nodes)
            continue

        nodes.extend(_splitter().get_nodes_from_documents([document]))

    return nodes
