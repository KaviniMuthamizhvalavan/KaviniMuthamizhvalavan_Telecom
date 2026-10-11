"""Heading-aware chunking of KB runbooks (plan §7.3).

Split on H2 sections; a section longer than `max_tokens` is split by paragraphs with a small overlap.
Each chunk is prefixed with "Runbook: <title> > <section>" so its embedding carries context.
IDs: KB-<CATEGORY>-<section-slug>[-n].
"""
import re
from dataclasses import dataclass
from pathlib import Path

from src.utils.config import PROJECT_ROOT

KB_DIR = PROJECT_ROOT / "data" / "knowledge_base"


@dataclass
class KBDoc:
    path: Path
    category: str
    title: str
    version: str
    references: list[str]
    body: str


@dataclass
class KBChunk:
    kb_id: str
    category: str
    section: str
    title: str
    doc_version: str
    text: str


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_front_matter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
    if not m:
        raise ValueError("runbook is missing YAML front-matter")
    meta = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, m.group(2)


def load_kb(directory: Path = KB_DIR) -> list[KBDoc]:
    docs = []
    for path in sorted(directory.glob("[0-9][0-9]_*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        docs.append(KBDoc(path, meta["category"], meta["title"], str(meta.get("version", "1.0")),
                          meta.get("references", []), body))
    return docs


def _split_section(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    if approx_tokens(text) <= max_tokens:
        return [text]
    paragraphs = [p for p in re.split(r"\n\s*\n|\n(?=### )", text) if p.strip()]
    parts, current = [], ""
    for p in paragraphs:
        if current and approx_tokens(current + "\n\n" + p) > max_tokens:
            parts.append(current)
            tail = current[-overlap_tokens * 4:]
            current = tail + "\n\n" + p
        else:
            current = (current + "\n\n" + p) if current else p
    if current:
        parts.append(current)
    return parts


def chunk_kb_doc(doc: KBDoc, max_tokens: int = 400, overlap_tokens: int = 40) -> list[KBChunk]:
    sections = re.split(r"^## +(.+)$", doc.body, flags=re.MULTILINE)
    chunks = []
    for heading, content in zip(sections[1::2], sections[2::2]):
        slug = slugify(heading)
        pieces = _split_section(content.strip(), max_tokens, overlap_tokens)
        for n, piece in enumerate(pieces, start=1):
            kb_id = f"KB-{doc.category}-{slug}" + (f"-{n}" if len(pieces) > 1 else "")
            text = f"Runbook: {doc.title} > {heading.strip()}\n{piece.strip()}"
            chunks.append(KBChunk(kb_id, doc.category, slug, doc.title, doc.version, text))
    return chunks


def chunk_all(directory: Path = KB_DIR) -> list[KBChunk]:
    return [c for doc in load_kb(directory) for c in chunk_kb_doc(doc)]
