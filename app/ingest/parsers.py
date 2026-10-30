from __future__ import annotations

from pathlib import Path

from llama_index.core import Document, SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader

SUPPORTED_EXTENSIONS = [
    ".pdf",
    ".docx",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".csv",
    ".md",
    ".markdown",
    ".txt",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".yaml",
    ".yml",
    ".json",
]

DOC_TYPE_BY_SUFFIX = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".ppt": "pptx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
}


class HtmlReader(BaseReader):
    """Read HTML as plain text, stripping scripts and styles."""

    def load_data(self, file: Path, extra_info: dict | None = None, **kwargs) -> list[Document]:
        from bs4 import BeautifulSoup

        raw = Path(file).read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n")
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return [Document(text=text, metadata=extra_info or {})]


class MarkdownTextReader(BaseReader):
    """Read Markdown as raw text.

    ``llama_index``'s MarkdownReader strips every ``<...>`` run as HTML, inside
    fenced code blocks included. That removes Vue/JSX tags and TypeScript/Java
    generics from code samples, so users asking for those get chunks without
    the code. Markdown headers and fences are handled by MarkdownNodeParser
    during chunking, so the text can be kept as written.
    """

    def load_data(self, file: Path, extra_info: dict | None = None, **kwargs) -> list[Document]:
        text = Path(file).read_text(encoding="utf-8", errors="ignore")
        return [Document(text=text, metadata=extra_info or {})]


def load_documents(path: Path) -> list[Document]:
    if path.is_file():
        input_files = [path]
        input_dir = None
    else:
        input_files = None
        input_dir = path

    markdown_reader = MarkdownTextReader()
    file_extractor: dict[str, BaseReader] = {
        ".html": HtmlReader(),
        ".htm": HtmlReader(),
        ".md": markdown_reader,
        ".markdown": markdown_reader,
    }

    reader = SimpleDirectoryReader(
        input_dir=input_dir,
        input_files=input_files,
        recursive=True,
        required_exts=SUPPORTED_EXTENSIONS,
        filename_as_id=True,
        file_extractor=file_extractor,
        raise_on_error=False,
    )
    return reader.load_data()


def doc_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in DOC_TYPE_BY_SUFFIX:
        return DOC_TYPE_BY_SUFFIX[suffix]
    if suffix in {".py", ".js", ".ts", ".java", ".go", ".rs", ".sql"}:
        return "code"
    if suffix in {".yaml", ".yml", ".json"}:
        return "config"
    return "text"
