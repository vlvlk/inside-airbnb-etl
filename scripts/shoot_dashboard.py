"""Capture the dashboard as portfolio-ready screenshots.

The script drives a headless Chromium against a *running* Streamlit server and
writes two artefacts per page and theme:

``<theme>/<page>.png``
    A **hero** frame: exactly one viewport (1600x1000 CSS px at 2x, so
    3200x2000). This is what the README embeds, because a full-page shot of a
    dense dashboard is unreadable once GitHub scales it down to ~880 px wide.

``<theme>/full/<page>.png``
    The whole page, top to bottom. Kept for the archive and linked from the
    README, where a reader can click through when they want the detail.

Streamlit is started separately, so the dashboard can be served by either
engine (PostgreSQL or the Parquet demo layer) without this script caring::

    streamlit run src/dashboard/app.py --server.port 8501 --server.headless true
    python scripts/shoot_dashboard.py

Install the browser driver once::

    pip install playwright
    playwright install chromium

Three details make the output deterministic, and each one is load-bearing:

* **The theme lives in ``localStorage``, not in a URL.** Streamlit 1.6x caches
  the user's choice under ``stActiveTheme-<pathname>-v2`` and stores the label
  (``"Light"`` / ``"Dark"``), not the slug. The key is per-pathname, so the init
  script rebuilds it from ``window.location.pathname`` on every navigation. The
  browser context's ``color_scheme`` is set as well, so a page that renders
  before the init script lands still picks the right "System" theme.
* **The scroll container is ``[data-testid="stMain"]``, not the document.**
  ``document.body.scrollHeight`` is 0 in this layout, which is why a naive
  ``full_page=True`` silently returns a viewport-sized image. :data:`UNFOLD_CSS`
  un-fixes the app shell so the document grows to the real content height.
* **Lazy charts need to be scrolled into view.** Vega mounts each chart when it
  approaches the viewport, so :func:`mount_charts` walks the page down and back
  up before the shot.

The script verifies the rendered background against the requested theme and
fails loudly on a mismatch, so a silent "both themes are light" regression
cannot slip into the README.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys
from dataclasses import dataclass
from typing import Literal, TypedDict

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page as BrowserPage
from playwright.sync_api import sync_playwright

#: The two themes the dashboard supports, matching Playwright's ``color_scheme``.
ThemeSlug = Literal["light", "dark"]


class ViewportSize(TypedDict):
    """Structural stand-in for Playwright's ``ViewportSize``."""

    width: int
    height: int

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "screenshots"


@dataclass(frozen=True)
class DashboardPage:
    """One ``st.Page``: the file-name slug and its path on the server."""

    slug: str
    path: str


PAGES: tuple[DashboardPage, ...] = (
    DashboardPage("insights", "/"),
    DashboardPage("overview", "/overview"),
    DashboardPage("occupancy", "/occupancy"),
    DashboardPage("revenue", "/revenue"),
    DashboardPage("data-quality", "/data_quality"),
    DashboardPage("sql-explorer", "/explorer"),
)

#: Theme slug -> the label Streamlit writes to ``localStorage``.
THEMES: dict[ThemeSlug, str] = {"light": "Light", "dark": "Dark"}

VIEWPORT: ViewportSize = {"width": 1600, "height": 1000}
DEVICE_SCALE_FACTOR = 2

#: Chrome that belongs to the Streamlit shell, not to the dashboard. The sidebar
#: is deliberately *not* hidden: it carries the "Demo data" badge and the
#: filters, which are part of what the screenshot is meant to show.
#:
#: ``stScreencast`` is absent on purpose. It looks like chrome by name, but it
#: is the wrapper around the whole app: hiding it collapses the sidebar to 0x0
#: and takes the nav links with it.
HIDE_CSS = """
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
[data-testid="stMainMenu"],
[data-testid="stElementToolbar"],
[data-testid="stSkipToContent"],
[data-testid="stAppIframeResizerAnchor"] {
    display: none !important;
}
"""

#: Streamlit animates the initial skeleton in; freezing animations keeps the
#: screenshots deterministic instead of catching a half-faded element.
FREEZE_CSS = """
*, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
}
"""

#: Undo the fixed-height app shell so the document grows to the real content
#: height and ``full_page=True`` captures everything. Without this the scroll
#: container clips the page at one viewport.
UNFOLD_CSS = """
html, body {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
}
[data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    position: static !important;
}
[data-testid="stSidebar"] {
    height: auto !important;
    min-height: 100vh !important;
    position: static !important;
}
"""

#: The theme key Streamlit reads back, e.g. ``stActiveTheme-/overview-v2``.
#: ``CACHED_THEME_VERSION`` is 2 in Streamlit 1.66; the init script re-derives
#: the key per navigation because it embeds the pathname.
THEME_INIT_SCRIPT = """
(() => {
    const label = %s;
    const key = `stActiveTheme-${window.location.pathname}-v2`;
    window.localStorage.setItem(key, JSON.stringify(label));
})();
"""


def settle(page: BrowserPage, *, timeout_ms: int = 60_000) -> None:
    """Wait until the page has finished its Streamlit rerun.

    The nav links only exist once the app shell has booted. Streamlit emits
    absolute hrefs, so match on the suffix rather than the bare path.
    """
    page.wait_for_selector("a[href$='/overview']", timeout=timeout_ms)
    page.wait_for_selector("[data-testid='stMainBlockContainer']", timeout=timeout_ms)
    # The status widget is the "Running…" pill. It is absent on a settled page,
    # so wait for it to be gone rather than for it to appear.
    page.wait_for_selector(
        "[data-testid='stStatusWidget']", state="detached", timeout=timeout_ms
    )
    # Charts are the slow part of a rerun. Pages without any chart (the SQL
    # explorer on a cold cache) are fine, so a timeout here is not fatal.
    try:
        page.wait_for_selector("[data-testid='stVegaLiteChart']", timeout=15_000)
    except PlaywrightError:
        pass
    page.wait_for_load_state("networkidle")
    # Let Vega finish its final paint after the last DOM mutation.
    page.wait_for_timeout(2_000)


def mount_charts(page: BrowserPage) -> None:
    """Scroll to the bottom in steps so every chart mounts, then return to top.

    The scroll container is ``stMain``; scrolling ``window`` does nothing here.
    """
    handle = page.query_selector("[data-testid='stMain']")
    if handle is None:
        return
    height = handle.evaluate("el => el.scrollHeight")
    step = 700
    y = 0
    while y < height:
        handle.evaluate("(el, y) => { el.scrollTop = y; }", y)
        page.wait_for_timeout(250)
        y += step
        height = handle.evaluate("el => el.scrollHeight")
    page.wait_for_timeout(1_200)
    handle.evaluate("el => { el.scrollTop = 0; }")
    page.wait_for_timeout(800)


def background_luminance(page: BrowserPage) -> float | None:
    """Return the app background's relative luminance, or ``None`` if unreadable."""
    raw = page.evaluate(
        "() => getComputedStyle(document.querySelector("
        "'[data-testid=\"stApp\"]') || document.body).backgroundColor"
    )
    match = re.match(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", raw or "")
    if not match:
        return None
    red, green, blue = (int(part) for part in match.groups())
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def png_size(path: pathlib.Path) -> tuple[int, int] | None:
    """Read width/height straight out of the PNG IHDR chunk."""
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


def shoot(
    base_url: str,
    out_root: pathlib.Path,
    *,
    themes: tuple[ThemeSlug, ...],
    pages: tuple[DashboardPage, ...],
    modes: tuple[str, ...],
    keep_chrome: bool,
) -> int:
    """Capture ``pages`` in ``themes`` and return a process exit code."""
    failures: list[str] = []
    written: list[pathlib.Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        for theme in themes:
            label = THEMES[theme]
            for mode in modes:
                out_dir = out_root / theme if mode == "hero" else out_root / theme / "full"
                out_dir.mkdir(parents=True, exist_ok=True)

                # A fresh context per (theme, mode): ``color_scheme`` drives
                # Streamlit's "System" setting, and the context carries no
                # cached theme from a previous run.
                context = browser.new_context(
                    viewport=VIEWPORT,
                    device_scale_factor=DEVICE_SCALE_FACTOR,
                    color_scheme=theme,
                    reduced_motion="reduce",
                )
                context.add_init_script(THEME_INIT_SCRIPT % repr(label))
                page = context.new_page()
                page.set_default_timeout(60_000)
                page.emulate_media(reduced_motion="reduce")

                for entry in pages:
                    target = out_dir / f"{entry.slug}.png"
                    try:
                        page.goto(
                            f"{base_url}{entry.path}", wait_until="domcontentloaded"
                        )
                        page.add_style_tag(content=FREEZE_CSS)
                        if not keep_chrome:
                            page.add_style_tag(content=HIDE_CSS)
                        settle(page)
                        mount_charts(page)

                        luminance = background_luminance(page)
                        expected_dark = theme == "dark"
                        if luminance is not None and (luminance < 0.5) != expected_dark:
                            raise PlaywrightError(
                                f"theme mismatch: {theme} rendered at "
                                f"luminance {luminance:.2f}"
                            )

                        if mode == "full":
                            page.add_style_tag(content=UNFOLD_CSS)
                            page.wait_for_timeout(400)

                        page.screenshot(
                            path=str(target),
                            full_page=mode == "full",
                            animations="disabled",
                        )
                        written.append(target)
                        size = png_size(target)
                        dimensions = f"{size[0]}x{size[1]}" if size else "?"
                        print(
                            f"OK  {theme:5s} {mode:4s} {entry.slug:12s} "
                            f"{dimensions:>10s} {target.stat().st_size / 1024:6.0f} KB"
                            f"  {target.relative_to(REPO_ROOT)}"
                        )
                    except PlaywrightError as exc:
                        failures.append(f"{theme}/{mode}/{entry.slug}: {exc}")
                        print(
                            f"FAIL {theme:5s} {mode:4s} {entry.slug:12s} {exc}",
                            file=sys.stderr,
                        )

                context.close()

        browser.close()

    if written:
        total = sum(path.stat().st_size for path in written) / 1024
        print(f"\n{len(written)} files, {total / 1024:.1f} MB total")

    if failures:
        print("\nFailures:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:8501",
        help="Base URL of the running dashboard (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=DEFAULT_OUT,
        help="Directory for the PNGs (default: docs/screenshots)",
    )
    parser.add_argument(
        "--themes",
        default="light,dark",
        help="Comma-separated themes to capture (default: %(default)s)",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated page slugs to capture (default: all)",
    )
    parser.add_argument(
        "--mode",
        choices=("hero", "full", "both"),
        default="both",
        help="Which artefact to write (default: %(default)s)",
    )
    parser.add_argument(
        "--keep-chrome",
        action="store_true",
        help="Leave the Streamlit header/toolbar in the frame (debugging)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    requested = [t.strip() for t in args.themes.split(",") if t.strip()]
    unknown = [t for t in requested if t not in THEMES]
    if unknown:
        raise SystemExit(f"unknown theme(s): {', '.join(unknown)}")
    themes: tuple[ThemeSlug, ...] = tuple(
        t for t in requested if t in THEMES
    )  # type: ignore[assignment]

    selected = tuple(s.strip() for s in args.only.split(",") if s.strip())
    pages = PAGES
    if selected:
        pages = tuple(p for p in PAGES if p.slug in selected)
        missing = [s for s in selected if s not in {p.slug for p in PAGES}]
        if missing:
            raise SystemExit(f"unknown page(s): {', '.join(missing)}")

    modes = ("hero", "full") if args.mode == "both" else (args.mode,)

    return shoot(
        args.url.rstrip("/"),
        args.out,
        themes=themes,
        pages=pages,
        modes=modes,
        keep_chrome=args.keep_chrome,
    )


if __name__ == "__main__":
    raise SystemExit(main())
