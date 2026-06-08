from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .schemas import RunConfig


class BrowserSession:
    def __init__(self, config: RunConfig, trace_path: str | Path) -> None:
        self.config = config
        self.trace_path = Path(trace_path)
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "BrowserSession":
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=not self.config.headed,
            slow_mo=self.config.slow_mo_ms,
        )
        self.context = self.browser.new_context()
        self.context.set_default_timeout(self.config.page_timeout_ms)
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.config.page_timeout_ms)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.context is not None:
            try:
                self.context.tracing.stop(path=str(self.trace_path))
            except Exception:
                pass
            self.context.close()
        if self.browser is not None:
            self.browser.close()
        if self.playwright is not None:
            self.playwright.stop()
