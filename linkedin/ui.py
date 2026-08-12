from __future__ import annotations

import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from playwright.sync_api import TimeoutError as PWTimeout

from linkedin.score import Post
from linkedin.settings import SEL, Settings


def pause(a: float = 0.4, b: float = 1.0) -> None:
    time.sleep(random.uniform(a, b))


def _in_docker() -> bool:
    return os.getenv("IN_DOCKER", "").strip().lower() in {"1", "true", "yes"}


def _focus_browser() -> None:
    if sys.platform != "darwin" or _in_docker():
        return
    script = (
        'tell application "System Events" to set frontmost of '
        'first process whose name contains "Chrome for Testing" to true'
    )
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


class LinkedIn:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def launch(self, playwright: Playwright) -> tuple[Browser, BrowserContext]:
        headless = self.settings.headless
        use_storage_context = _in_docker() or headless
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]

        if use_storage_context:
            browser = playwright.chromium.launch(
                headless=headless,
                slow_mo=20,
                args=args,
            )
            kwargs: dict = {
                "viewport": {"width": 1280, "height": 900},
                "locale": "en-US",
                "user_agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            }
            if self.settings.storage_state.exists():
                kwargs["storage_state"] = str(self.settings.storage_state)
                print(f"[boot] storage_state ← {self.settings.storage_state}", flush=True)
            else:
                print("[boot] no storage_state — login required", flush=True)
            context = browser.new_context(**kwargs)
            context.set_default_timeout(60_000)
            return browser, context

        profile = Path(".linkedin_profile").resolve()
        profile.mkdir(parents=True, exist_ok=True)
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            slow_mo=40,
            locale="en-US",
            no_viewport=True,
            args=args + ["--start-maximized"],
        )
        context.set_default_timeout(60_000)
        browser = context.browser
        assert browser is not None
        return browser, context

    def save_session(self, context: BrowserContext) -> Path:
        path = self.settings.storage_state
        context.storage_state(path=str(path))
        return path

    def ensure_login(self, page: Page) -> None:
        print("[auth] opening feed…", flush=True)
        page.goto(self.settings.feed_url, wait_until="domcontentloaded")
        if not self.settings.headless:
            try:
                page.bring_to_front()
            except Exception:
                pass
            _focus_browser()
        pause(1.5, 2.5)
        if self._logged_in(page):
            print("[auth] already logged in", flush=True)
            return

        if _in_docker() or self.settings.headless:
            try:
                page.screenshot(path="feed_debug_auth.png")
            except Exception:
                pass
            raise RuntimeError(
                "Not logged in inside container. Run once on the host (headed) to refresh "
                ".linkedin_storage.json, then re-run: docker compose up --build agent"
            )

        print("[auth] >>> Log in inside Google Chrome for Testing", flush=True)
        page.goto(self.settings.login_url, wait_until="domcontentloaded")
        page.bring_to_front()
        _focus_browser()
        self._wait_until_feed(page)

    def _logged_in(self, page: Page) -> bool:
        url = page.url.lower()
        if any(p in url for p in ("/login", "authwall", "/checkpoint/", "/challenge")):
            return False
        if "/feed" in url:
            return True
        try:
            if page.locator(SEL["nav"]).count() > 0:
                return True
        except Exception:
            pass
        try:
            if page.locator('[data-testid="mainFeed"]').count() > 0:
                return True
        except Exception:
            pass
        try:
            if "linkedin.com" in url and any(
                c.get("name") == "li_at" for c in page.context.cookies()
            ):
                return True
        except Exception:
            pass
        return self._is_feed(page)

    def _is_challenge(self, page: Page) -> bool:
        url = page.url.lower()
        return any(p in url for p in ("/checkpoint/", "/challenge", "login-submit"))

    def _wait_until_feed(self, page: Page) -> None:
        timeout_s = 20 * 60
        interval_s = 3.0
        rounds = int(timeout_s / interval_s)
        print(
            f"[auth] waiting up to {timeout_s // 60} min for /feed/ "
            "in Google Chrome for Testing (not regular Chrome)…",
            flush=True,
        )
        for i in range(rounds):
            try:
                for p in list(page.context.pages):
                    if self._logged_in(p):
                        if "/feed" not in p.url.lower():
                            try:
                                p.goto(self.settings.feed_url, wait_until="domcontentloaded")
                            except Exception:
                                pass
                        print(f"[auth] logged in → {p.url}", flush=True)
                        return
            except Exception as exc:
                print(f"[auth] check failed: {exc}", flush=True)
                pause(interval_s, interval_s)
                continue

            if i % 20 == 0:
                try:
                    urls = " | ".join(p.url for p in page.context.pages)
                except Exception:
                    urls = "(browser closed?)"
                print(f"[auth] still waiting… ({i * interval_s:.0f}s) tabs={urls}", flush=True)
            pause(interval_s, interval_s)

        raise RuntimeError(
            "Timed out waiting for feed — finish login/2FA in Google Chrome for Testing"
        )

    def read_feed(self, page: Page, limit: int = 35) -> list[Post]:
        print("[feed] loading home feed…", flush=True)
        page.goto(self.settings.feed_url, wait_until="domcontentloaded")
        try:
            page.bring_to_front()
        except Exception:
            pass
        pause(2.0, 2.8)
        print(f"[feed] url={page.url}", flush=True)
        try:
            page.locator(
                '[data-view-name="feed-full-update"], '
                '[data-testid="mainFeed"] [role="listitem"], '
                'button[aria-label*="Reaction button state"]'
            ).first.wait_for(state="attached", timeout=30_000)
        except PWTimeout:
            print("[feed] no posts appeared after wait", flush=True)

        posts: list[Post] = []
        seen: set[str] = set()
        stagnant = 0
        target = max(limit, self.settings.like_target * 2, 12)
        max_scrolls = 4

        for scroll in range(max_scrolls):
            before = len(posts)
            batch = self._scrape_posts(page)
            for item in batch:
                urn = item.get("urn") or ""
                text = (item.get("text") or "").strip()
                if not urn or not text or urn in seen:
                    continue
                seen.add(urn)
                posts.append(
                    Post(
                        urn=urn,
                        author=(item.get("author") or "Unknown").strip(),
                        author_url=item.get("author_url") or "",
                        text=text,
                    )
                )
                if len(posts) >= target:
                    print(f"[feed] parsed {len(posts)} posts (target reached)", flush=True)
                    return posts

            gained = len(posts) - before
            print(
                f"[feed] pass {scroll + 1}/{max_scrolls} — {len(posts)} posts "
                f"(+{gained} new, batch={len(batch)})",
                flush=True,
            )
            if gained == 0:
                stagnant += 1
                if stagnant >= 2:
                    print("[feed] no new posts — stop scrolling", flush=True)
                    break
            else:
                stagnant = 0
            if scroll + 1 < max_scrolls:
                page.mouse.wheel(0, random.randint(700, 1100))
                pause(0.6, 1.0)

        print(f"[feed] parsed {len(posts)} posts", flush=True)
        return posts

    def _scrape_posts(self, page: Page) -> list[dict]:
        for scraper in (self._scrape_by_view_name, self._scrape_listitems, self._scrape_legacy):
            batch = scraper(page)
            if batch:
                return batch
        return []

    def _scrape_by_view_name(self, page: Page) -> list[dict]:
        out: list[dict] = []
        cards = page.locator('[data-view-name="feed-full-update"]')
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                raw = (card.inner_text(timeout=1_500) or "").strip()
                text = self._join_texts(card, '[data-view-name="feed-commentary"]')
                if not text:
                    text = self._body_from_text(raw)
                if not text:
                    continue
                author, author_url = self._resolve_author(card, raw)
                urn = self._card_id(card) or f"{author}|{text[:60]}"
                out.append(
                    {
                        "urn": urn,
                        "author": author,
                        "author_url": author_url,
                        "text": text,
                    }
                )
            except Exception:
                continue
        return out

    def _scrape_listitems(self, page: Page) -> list[dict]:
        main = page.locator('[data-testid="mainFeed"]')
        if main.count() == 0:
            main = page.locator("main")
        if main.count() == 0:
            return []

        out: list[dict] = []
        cards = main.first.locator('[role="listitem"]')
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                react = card.locator(
                    'button[aria-label*="Reaction button state"], button[aria-label*="Like"]'
                )
                if react.count() == 0:
                    continue
                raw = (card.inner_text(timeout=1_500) or "").strip()
                if not re.match(r"(?i)^Feed post", raw) or len(raw) < 80:
                    continue
                author, author_url = self._resolve_author(card, raw)
                text = self._body_from_text(raw, author=author)
                if not text:
                    continue
                urn = self._card_id(card) or f"{author}|{text[:60]}"
                out.append(
                    {
                        "urn": urn,
                        "author": author,
                        "author_url": author_url,
                        "text": text,
                    }
                )
            except Exception:
                continue
        return out

    def _scrape_legacy(self, page: Page) -> list[dict]:
        out: list[dict] = []
        cards = page.locator("div.feed-shared-update-v2[data-urn], article[data-urn]")
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                urn = card.get_attribute("data-urn") or ""
                raw = (card.inner_text(timeout=1_500) or "").strip()
                text = self._text(card, SEL["text"]) or self._body_from_text(raw)
                author, author_url = self._resolve_author(card, raw)
                if not urn or not text:
                    continue
                out.append(
                    {
                        "urn": urn,
                        "author": author,
                        "author_url": author_url,
                        "text": text,
                    }
                )
            except Exception:
                continue
        return out

    @staticmethod
    def _clean_author(raw: str) -> str:
        line = (raw or "").strip().split("\n")[0]
        line = re.sub(
            r"(?i)^view\s+company:\s*",
            "",
            line,
        )
        line = re.sub(
            r"(?i)^(?:view|open|go to|visit)\s+"
            r"(?:the\s+)?(?:profile|page|company)\s+"
            r"(?:of\s+|for\s+)?",
            "",
            line,
        )
        line = re.sub(
            r"(?i)^view\s+(.+?)(?:['’]s)?\s+profile(?:[, ].*)?$",
            r"\1",
            line,
        )
        line = re.sub(r"(?i)\s*,\s*hiring\s*$", "", line)
        line = re.sub(r"\s*[•·].*$", "", line)
        line = re.sub(r"\s*\|.*$", "", line)
        line = re.sub(r"\s{2,}", " ", line).strip(" -\t")
        if re.match(
            r"(?i)^(feed post|follow|connect|promoted|like|comment|repost|send|"
            r"recommended for you|popular on linkedin|new comment)$",
            line,
        ):
            return ""
        return line

    @staticmethod
    def _social_skip_names(raw: str) -> set[str]:
        names: set[str] = set()
        for m in re.finditer(
            r"^(.{2,80}?) ("
            r"likes this|loves this|celebrates this|supports this|"
            r"finds this insightful|reposted this|follows this(?: page)?|"
            r"commented on this"
            r")\s*$",
            raw,
            re.I | re.M,
        ):
            names.add(m.group(1).strip().lower())
        return names

    @staticmethod
    def _slug_to_name(href: str) -> str:
        m = re.search(r"/(?:in|company)/([^/?#]+)", href or "")
        if not m:
            return ""
        slug = m.group(1).replace("%20", " ").strip("-_")
        slug = slug.split("/")[0]
        # Drop LinkedIn trailing member ids: name-name-a1b2c3d4
        slug = re.sub(r"-[a-z0-9]{5,}$", "", slug, flags=re.I)
        slug = re.sub(r"[-_]+", " ", slug)
        slug = re.sub(r"\b\d+\b", " ", slug)
        slug = re.sub(r"\s+", " ", slug).strip()
        if len(slug) < 2:
            return ""
        return slug.title()

    def _link_label(self, el) -> str:
        try:
            text = self._clean_author(el.inner_text(timeout=500) or "")
        except Exception:
            text = ""
        if text:
            return text
        for sel in ("span[aria-hidden='true']", "img[alt]"):
            loc = el.locator(sel)
            for i in range(min(loc.count(), 3)):
                try:
                    if sel.startswith("img"):
                        cand = self._clean_author(loc.nth(i).get_attribute("alt") or "")
                    else:
                        cand = self._clean_author(loc.nth(i).inner_text(timeout=300) or "")
                except Exception:
                    continue
                if cand:
                    return cand
        return self._clean_author(el.get_attribute("aria-label") or "")

    @staticmethod
    def _norm_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (name or "").lower())

    @classmethod
    def _is_skipped(cls, name: str, skip: set[str]) -> bool:
        n = (name or "").strip().lower()
        if not n:
            return True
        if n in skip:
            return True
        compact = cls._norm_name(n)
        if not compact:
            return True
        for s in skip:
            sc = cls._norm_name(s)
            if sc and (compact == sc or compact in sc or sc in compact):
                return True
        return False

    def _author_from_raw_lines(self, raw: str, skip: set[str]) -> str:
        for line in raw.split("\n")[:14]:
            line = line.strip()
            if not line or re.match(r"(?i)^feed post$", line):
                continue
            if re.search(
                r"likes this|loves this|celebrates this|reposted this|"
                r"follows this|commented on this",
                line,
                re.I,
            ):
                continue
            if re.search(
                r"(?i)\bfollowers\b|\bpromoted\b|\bconnect\b|"
                r"^(follow|view my website|visit my website)\b",
                line,
            ):
                continue
            if re.match(r"^\d+[hdwmy]\b", line, re.I) or line.startswith("•"):
                continue
            if re.match(r"(?i)^recommended for you$|^popular on linkedin$", line):
                continue
            name = self._clean_author(line)
            if 2 <= len(name) <= 80 and not self._is_skipped(name, skip):
                # Avoid long headlines / post openers.
                if len(name) > 60 and (" " in name and name.count(" ") >= 6):
                    continue
                return name
        return ""

    def _resolve_author(self, card, raw: str) -> tuple[str, str]:
        skip = self._social_skip_names(raw)
        prefer_company = bool(
            re.search(r"(?i)follows this(?: page)?\s*$", raw, re.M)
        )

        typed = self._clean_author(self._text(card, SEL["author"]))
        if typed and not self._is_skipped(typed, skip):
            return typed, self._author_href(card, typed, prefer_company=prefer_company)

        raw_name = self._author_from_raw_lines(raw, skip)

        people: list[tuple[str, str]] = []
        companies: list[tuple[str, str]] = []
        links = card.locator(SEL["author_link"])
        seen_key: set[str] = set()
        pending_slug: dict[str, tuple[str, str, str]] = {}

        def entity_key(href: str) -> str:
            m = re.search(r"/(in|company)/([^/?#]+)", href or "")
            if not m:
                return href.rstrip("/")
            return f"{m.group(1)}:{m.group(2).lower()}"

        for i in range(min(links.count(), 12)):
            el = links.nth(i)
            href = (el.get_attribute("href") or "").split("?")[0]
            if not href:
                continue
            if href.startswith("/"):
                href = self.settings.base_url.rstrip("/") + href
            key = entity_key(href)
            if key in seen_key:
                continue
            label = self._link_label(el)
            if label and not self._is_skipped(label, skip):
                seen_key.add(key)
                if "/company/" in href:
                    companies.append((label, href))
                elif "/in/" in href:
                    people.append((label, href))
                continue
            if key not in pending_slug and key not in seen_key:
                slug = self._slug_to_name(href)
                if slug and not self._is_skipped(slug, skip):
                    pending_slug[key] = (
                        "company" if "/company/" in href else "person",
                        slug,
                        href,
                    )

        for key, (kind, slug, href) in pending_slug.items():
            if key in seen_key:
                continue
            seen_key.add(key)
            if kind == "company":
                companies.append((slug, href))
            else:
                people.append((slug, href))

        def pick_person() -> tuple[str, str] | None:
            if not people:
                return None
            if raw_name:
                raw_n = self._norm_name(raw_name)
                for label, href in people:
                    ln = self._norm_name(label)
                    if ln and raw_n and (ln == raw_n or raw_n in ln or ln in raw_n):
                        return label, href
                # Prefer the raw feed line when links are noisy (slugs / social actors).
                return raw_name, self._author_href(
                    card, raw_name, prefer_company=prefer_company
                )
            # After social-proof actors, the post author is usually the last person.
            return people[-1] if len(people) > 1 else people[0]

        if prefer_company and companies:
            if raw_name:
                raw_n = self._norm_name(raw_name)
                for label, href in companies:
                    ln = self._norm_name(label)
                    if ln and raw_n and (ln == raw_n or raw_n in ln or ln in raw_n):
                        return label, href
            return companies[0]

        person = pick_person()
        if person:
            return person
        if companies:
            return companies[0]
        if raw_name:
            return raw_name, self._author_href(
                card, raw_name, prefer_company=prefer_company
            )

        return "Unknown", ""

    @staticmethod
    def _body_from_text(raw: str, author: str = "") -> str:
        skip = re.compile(
            r"^(feed post|follow|connect|join|promoted|like|comment|repost|send|"
            r"show translation|view job|actively reviewing|visit my website|"
            r"view my website|\d+\s*reactions?|\d+\s*comments?)$",
            re.I,
        )
        author_l = (author or "").strip().lower()
        out: list[str] = []
        started = False
        for line in (l.strip() for l in raw.split("\n") if l.strip()):
            if re.match(r"(?i)^feed post$", line):
                continue
            if author_l and line.lower() == author_l:
                continue
            if re.search(
                r"likes this$|loves this$|celebrates this$|reacted$|"
                r"followers$|reposted this|follows this",
                line,
                re.I,
            ):
                continue
            if re.match(r"^\d+[hdwmy]\b", line, re.I) or line.startswith("•"):
                continue
            if skip.match(line):
                continue
            # Skip actor headline / degree row before the post body starts.
            if not started and (
                re.match(r"(?i)^•\s*\d", line)
                or (len(line) < 120 and "|" in line and not line.endswith("."))
            ):
                continue
            if not started and len(line) < 40 and not out:
                continue
            started = True
            out.append(line)
            if len("\n".join(out)) > 1200:
                break
        return "\n".join(out).strip()

    def _author_href(
        self,
        card,
        author: str,
        prefer_company: bool = False,
    ) -> str:
        author_l = (author or "").lower()
        links = card.locator(SEL["author_link"])
        person = ""
        company = ""
        for i in range(min(links.count(), 12)):
            href = (links.nth(i).get_attribute("href") or "").split("?")[0]
            if not href:
                continue
            if href.startswith("/"):
                href = self.settings.base_url.rstrip("/") + href
            try:
                text = self._link_label(links.nth(i)).lower()
            except Exception:
                text = ""
            if not text:
                text = self._slug_to_name(href).lower()
            matched = bool(author_l and author_l in text)
            if "/company/" in href:
                if matched:
                    return href
                if not company:
                    company = href
            elif "/in/" in href:
                if matched:
                    return href
                if not person:
                    person = href
        if prefer_company:
            return company or person
        return person or company

    def _join_texts(self, root, selector: str) -> str:
        loc = root.locator(selector)
        parts: list[str] = []
        for i in range(min(loc.count(), 6)):
            try:
                t = loc.nth(i).inner_text(timeout=1_000).strip()
            except Exception:
                continue
            if t:
                parts.append(t)
        return "\n\n".join(parts)

    def like(self, page: Page, post: Post) -> str:
        last = "failed:timeout"
        for attempt in range(4):
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            pause(0.2, 0.4)

            card = self._locate_post_card(page, post)
            if card is None:
                last = "failed:not_found"
                # Feed is virtualized — hunt by scrolling both ways.
                self._hunt_post(page, post)
                continue

            try:
                outcome = self._like_on_card(card)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                if outcome.startswith("failed"):
                    last = outcome
                    pause(0.4, 0.7)
                    continue
                return outcome
            except PWTimeout:
                last = "failed:timeout"
            except Exception as exc:
                last = f"failed:{exc!s}"[:80]
            pause(0.5, 0.9)
        return last

    def _like_on_card(self, card) -> str:
        try:
            card.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        pause(0.35, 0.6)

        btn = self._reaction_button(card)
        if btn is None:
            return "failed:no_button"

        label = (btn.get_attribute("aria-label", timeout=3_000) or "").lower()
        pressed = (btn.get_attribute("aria-pressed", timeout=1_000) or "").lower()
        if pressed == "true":
            return "already_liked"
        if "state:" in label and "no reaction" not in label:
            return "already_liked"

        try:
            btn.click(timeout=6_000)
        except PWTimeout:
            # Overlay / animation — force usually still toggles the reaction.
            btn.click(timeout=4_000, force=True)
        pause(0.45, 0.8)
        return "liked"

    def _reaction_button(self, card):
        selectors = [
            'button[aria-label*="Reaction button state"]',
            '[data-view-name="reaction-button"]',
            'button[aria-label*="Like"]',
            'button[aria-label*="Реакц"]',
            'button[aria-label*="Подобається"]',
        ]
        for sel in selectors:
            loc = card.locator(sel)
            for i in range(min(loc.count(), 4)):
                cand = loc.nth(i)
                try:
                    if cand.is_visible(timeout=800):
                        return cand
                except Exception:
                    continue
        # Last resort: role/name, but only if something is already attached.
        role = card.get_by_role("button", name=re.compile(r"reaction|like|реакц|подоба", re.I))
        try:
            if role.count() > 0 and role.first.is_visible(timeout=800):
                return role.first
        except Exception:
            pass
        return None

    def _hunt_post(self, page: Page, post: Post) -> None:
        snippet = (post.preview or "")[:36]
        if not snippet:
            return
        # Go up, then down — virtualized rows unmount off-screen.
        for delta in (-900, -900, 1100, 1100, 1100, 1100):
            if self._locate_post_card(page, post) is not None:
                return
            page.mouse.wheel(0, delta)
            pause(0.35, 0.55)

    def _locate_post_card(self, page: Page, post: Post):
        card = self._find_card(page, post)
        if card is not None:
            return card
        snippet = (post.preview or "")[:36]
        if not snippet:
            return None
        # Text match is more reliable than urn once LinkedIn recycles listitems.
        try:
            hit = page.get_by_text(snippet, exact=False)
            if hit.count() == 0:
                return None
            node = hit.first.locator(
                'xpath=ancestor::*[@role="listitem" or @data-view-name="feed-full-update" '
                'or contains(@class,"feed-shared-update") or @data-urn][1]'
            )
            if node.count() > 0:
                return node.first
        except Exception:
            return None
        return None

    def _card_id(self, card) -> str:
        urn = card.get_attribute("data-urn") or ""
        if urn:
            return urn
        key = card.get_attribute("componentkey") or ""
        if key:
            return key
        parent = card.locator("xpath=ancestor-or-self::*[@componentkey][1]")
        if parent.count():
            key = parent.first.get_attribute("componentkey") or ""
            if key:
                return key
        try:
            return (card.inner_text(timeout=800) or "")[:80]
        except Exception:
            return ""

    def _find_card(self, page: Page, post: Post):
        selectors = [
            '[data-testid="mainFeed"] [role="listitem"]',
            '[data-view-name="feed-full-update"]',
            "div.feed-shared-update-v2[data-urn], article[data-urn]",
        ]
        snippet = (post.preview or "")[:40]
        for sel in selectors:
            cards = page.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    if post.urn and self._card_id(card) == post.urn:
                        return card
                except Exception:
                    continue
        if not snippet:
            return None
        for sel in selectors:
            cards = page.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    text = card.inner_text(timeout=800) or ""
                except Exception:
                    continue
                if snippet in text and self._reaction_button(card) is not None:
                    return card
        for sel in selectors:
            cards = page.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    if snippet in (card.inner_text(timeout=500) or ""):
                        return card
                except Exception:
                    continue
        loc = page.locator(f'[componentkey="{post.urn}"]')
        if loc.count() > 0:
            return loc.first
        return None

    def profile_bits(self, page: Page, post: Post) -> dict[str, str]:
        info = {"headline": "", "about": "", "friction": ""}
        if not post.author_url:
            info["friction"] = "no author url"
            return info

        try:
            page.goto(post.author_url, wait_until="domcontentloaded")
            pause(1.0, 1.8)
        except Exception as exc:
            info["friction"] = f"nav failed: {exc!s}"[:100]
            return info

        if "login" in page.url or "authwall" in page.url:
            info["friction"] = "authwall"
            return info

        info["headline"] = self._page_text(page, SEL["headline"])
        info["about"] = self._page_text(page, SEL["about"], limit=400)
        missing = []
        if not info["headline"]:
            missing.append("headline")
        if not info["about"]:
            missing.append("about")
        if missing:
            info["friction"] = "missing: " + ", ".join(missing)
        return info

    def _is_feed(self, page: Page) -> bool:
        if "/feed" not in page.url.lower():
            return False
        try:
            page.locator(SEL["nav"]).first.wait_for(timeout=4_000)
            return True
        except PWTimeout:
            return "/feed" in page.url

    def _text(self, root, selector: str) -> str:
        loc = root.locator(selector)
        best = ""
        for i in range(min(loc.count(), 3)):
            try:
                t = loc.nth(i).inner_text(timeout=1_200).strip()
            except Exception:
                continue
            if len(t) > len(best):
                best = t
        return best

    def _page_text(self, page: Page, selector: str, limit: int = 240) -> str:
        loc = page.locator(selector)
        if loc.count() == 0:
            return ""
        try:
            return " ".join(loc.first.inner_text(timeout=2_000).split())[:limit]
        except Exception:
            return ""

    def _href(self, root, selector: str) -> str:
        loc = root.locator(selector)
        if loc.count() == 0:
            return ""
        href = (loc.first.get_attribute("href") or "").split("?")[0]
        if href.startswith("/"):
            return self.settings.base_url.rstrip("/") + href
        return href
