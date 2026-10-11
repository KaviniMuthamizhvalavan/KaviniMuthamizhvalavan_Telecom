"""Render architecture/architecture.svg to Architecture_Diagram.pdf (one landscape page) and architecture.png.

Run from the repo root:  python -m scripts.build_architecture
Uses Playwright on the installed Microsoft Edge (channel "msedge"); local, no API.
"""
from src.utils.config import PROJECT_ROOT

ARCH = PROJECT_ROOT / "architecture"
W, H = 1600, 1000


def main() -> None:
    from playwright.sync_api import sync_playwright
    svg = (ARCH / "architecture.svg").read_text(encoding="utf-8")
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>@page{size:1600px 1000px;margin:0}"
            f"html,body{{margin:0;background:#fff}}</style></head><body>{svg}</body></html>")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        page.set_content(html)
        page.screenshot(path=str(ARCH / "architecture.png"), clip={"x": 0, "y": 0, "width": W, "height": H})
        page.pdf(path=str(ARCH / "Architecture_Diagram.pdf"), width=f"{W}px", height=f"{H}px", print_background=True,
                 page_ranges="1")
        browser.close()
    print("wrote architecture/architecture.png and architecture/Architecture_Diagram.pdf")


if __name__ == "__main__":
    main()
