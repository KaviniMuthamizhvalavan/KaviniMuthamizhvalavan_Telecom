"""Render architecture/architecture.html to Architecture_Diagram.pdf (one landscape page) and architecture.png.

Run from the repo root:  python -m scripts.build_architecture
Uses Playwright on the installed Microsoft Edge (channel "msedge"); local, no API. The HTML is a fixed-size page
(2000 x 1255 px) with no external resources.
"""
from src.utils.config import PROJECT_ROOT

ARCH = PROJECT_ROOT / "architecture"
W, H = 2000, 1255


def main() -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        page.goto((ARCH / "architecture.html").as_uri(), wait_until="networkidle")
        page.screenshot(path=str(ARCH / "architecture.png"), clip={"x": 0, "y": 0, "width": W, "height": H})
        page.pdf(path=str(ARCH / "Architecture_Diagram.pdf"), width=f"{W}px", height=f"{H}px", print_background=True,
                 page_ranges="1")
        browser.close()
    print("wrote architecture/architecture.png and architecture/Architecture_Diagram.pdf")


if __name__ == "__main__":
    main()
