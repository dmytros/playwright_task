from __future__ import annotations

import argparse
import sys

from playwright.sync_api import sync_playwright

from linkedin.levels import level1, level2, level3
from linkedin.settings import load_settings
from linkedin.ui import LinkedIn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LinkedIn feed agent (Playwright)")
    parser.add_argument(
        "--level",
        default=None,
        help="1=like, 2=drafts, 3=profile drafts, all=1+2+3 in one session",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    raw = (args.level if args.level is not None else str(settings.level)).strip().lower()
    if raw in {"all", "0"}:
        levels = (1, 2, 3)
        level_label = "all"
    else:
        level = int(raw)
        if level not in {1, 2, 3}:
            parser.error("--level must be 1, 2, 3, or all")
        levels = (level,)
        level_label = str(level)

    print(f"[boot] level={level_label} headless={settings.headless}", flush=True)
    print("[boot] comments are never posted", flush=True)

    li = LinkedIn(settings)
    try:
        with sync_playwright() as playwright:
            print("[boot] launching Chromium…", flush=True)
            browser, context = li.launch(playwright)
            try:
                page = next(
                    (p for p in context.pages if "linkedin.com" in p.url),
                    context.pages[0] if context.pages else context.new_page(),
                )
                li.ensure_login(page)

                liked = level1(li, page)
                if 2 in levels and 3 not in levels:
                    level2(li, page, liked)
                elif 3 in levels and 2 not in levels:
                    level3(li, page, liked)
                elif 2 in levels and 3 in levels:
                    level2(li, page, liked)
                    level3(li, page, liked)

                path = li.save_session(context)
                print(f"\n[session] saved → {path}")
            finally:
                context.close()
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\n[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
