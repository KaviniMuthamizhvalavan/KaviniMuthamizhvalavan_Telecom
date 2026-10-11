"""Render the Markdown sources of the deliverable documents to PDF (local, no API).

Run from the repo root:  python -m scripts.build_docs [name ...]
Markdown -> HTML (markdown-it-py) -> PDF with Playwright on the installed Microsoft Edge (channel "msedge"), so no
browser download is needed. Images are resolved relative to each source file.
"""
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

from src.utils.config import PROJECT_ROOT

DOCS = {
    "api": (PROJECT_ROOT / "docs" / "source" / "API_Documentation.md", PROJECT_ROOT / "docs" / "API_Documentation.pdf"),
    "dataset": (PROJECT_ROOT / "docs" / "source" / "Dataset_Details.md", PROJECT_ROOT / "docs" / "Dataset_Details.pdf"),
    "evaluation": (PROJECT_ROOT / "docs" / "source" / "Evaluation_Report.md",
                   PROJECT_ROOT / "docs" / "Evaluation_Report.pdf"),
    "design": (PROJECT_ROOT / "design" / "Design_Document.md", PROJECT_ROOT / "design" / "Design_Document.pdf"),
}
CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1d2329; }
h1 { font-size: 20pt; margin: 0 0 4pt; color: #0b3d5c; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; color: #0b3d5c; border-bottom: 1px solid #c9d3db; padding-bottom: 2pt;
     page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; color: #164f73; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.8pt; page-break-inside: auto; }
th, td { border: 1px solid #c9d3db; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #e8eef3; }
tr { page-break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.6pt; background: #f1f4f6; padding: 0 2pt; border-radius: 2pt; }
pre { background: #f1f4f6; padding: 6pt 8pt; border-radius: 3pt; font-size: 8pt; line-height: 1.35;
      white-space: pre-wrap; word-break: break-word; page-break-inside: auto; }
pre code { background: none; padding: 0; }
img { max-width: 100%; }
blockquote { border-left: 3px solid #9fb3c2; margin: 6pt 0; padding: 2pt 10pt; color: #3c4a55; }
.footer { font-size: 7.5pt; color: #6b7883; }
"""


def render(md_path: Path, pdf_path: Path, browser) -> None:
    html_body = MarkdownIt("commonmark", {"html": True}).enable("table").render(md_path.read_text(encoding="utf-8"))
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html_body}</body></html>"
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=md_path.parent, delete=False, encoding="utf-8") as fh:
        fh.write(html)
        tmp = Path(fh.name)
    try:
        page = browser.new_page()
        page.goto(tmp.as_uri())
        page.wait_for_load_state("networkidle")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=str(pdf_path), format="A4", print_background=True, display_header_footer=True,
                 header_template="<span></span>",
                 footer_template="<div style='font-size:7pt;width:100%;text-align:center;color:#6b7883'>"
                                 "<span class='pageNumber'></span> / <span class='totalPages'></span></div>",
                 margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
        page.close()
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{md_path.relative_to(PROJECT_ROOT)} -> {pdf_path.relative_to(PROJECT_ROOT)}")


def main() -> None:
    from playwright.sync_api import sync_playwright
    names = sys.argv[1:] or list(DOCS)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        for name in names:
            src, out = DOCS[name]
            if src.exists():
                render(src, out, browser)
            else:
                print(f"skipped {name}: {src.relative_to(PROJECT_ROOT)} does not exist")
        browser.close()


if __name__ == "__main__":
    main()
