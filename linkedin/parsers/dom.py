from __future__ import annotations

import re
from typing import Any, Protocol

from linkedin.parsers.textutil import (
    author_from_raw_lines,
    clean_author,
    is_skipped,
    norm_name,
    slug_to_name,
    social_skip_names,
)


class LocatorRoot(Protocol):
    def locator(self, selector: str) -> Any: ...


def first_text(root: LocatorRoot, selector: str) -> str:
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


def join_texts(root: LocatorRoot, selector: str) -> str:
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


def card_id(card) -> str:
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


def link_label(el) -> str:
    try:
        text = clean_author(el.inner_text(timeout=500) or "")
    except Exception:
        text = ""
    if text:
        return text
    for sel in ("span[aria-hidden='true']", "img[alt]"):
        loc = el.locator(sel)
        for i in range(min(loc.count(), 3)):
            try:
                if sel.startswith("img"):
                    cand = clean_author(loc.nth(i).get_attribute("alt") or "")
                else:
                    cand = clean_author(loc.nth(i).inner_text(timeout=300) or "")
            except Exception:
                continue
            if cand:
                return cand
    return clean_author(el.get_attribute("aria-label") or "")


def author_href(
    card,
    author: str,
    base_url: str,
    author_link_selector: str,
    prefer_company: bool = False,
) -> str:
    author_l = (author or "").lower()
    links = card.locator(author_link_selector)
    person = ""
    company = ""
    for i in range(min(links.count(), 12)):
        href = (links.nth(i).get_attribute("href") or "").split("?")[0]
        if not href:
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        try:
            text = link_label(links.nth(i)).lower()
        except Exception:
            text = ""
        if not text:
            text = slug_to_name(href).lower()
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


def resolve_author(
    card,
    raw: str,
    *,
    base_url: str,
    author_selector: str,
    author_link_selector: str,
) -> tuple[str, str]:
    skip = social_skip_names(raw)
    prefer_company = bool(re.search(r"(?i)follows this(?: page)?\s*$", raw, re.M))

    typed = clean_author(first_text(card, author_selector))
    if typed and not is_skipped(typed, skip):
        return typed, author_href(
            card, typed, base_url, author_link_selector, prefer_company=prefer_company
        )

    raw_name = author_from_raw_lines(raw, skip)

    people: list[tuple[str, str]] = []
    companies: list[tuple[str, str]] = []
    links = card.locator(author_link_selector)
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
            href = base_url.rstrip("/") + href
        key = entity_key(href)
        if key in seen_key:
            continue
        label = link_label(el)
        if label and not is_skipped(label, skip):
            seen_key.add(key)
            if "/company/" in href:
                companies.append((label, href))
            elif "/in/" in href:
                people.append((label, href))
            continue
        if key not in pending_slug and key not in seen_key:
            slug = slug_to_name(href)
            if slug and not is_skipped(slug, skip):
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
            raw_n = norm_name(raw_name)
            for label, href in people:
                ln = norm_name(label)
                if ln and raw_n and (ln == raw_n or raw_n in ln or ln in raw_n):
                    return label, href
            return raw_name, author_href(
                card, raw_name, base_url, author_link_selector, prefer_company=prefer_company
            )
        return people[-1] if len(people) > 1 else people[0]

    if prefer_company and companies:
        if raw_name:
            raw_n = norm_name(raw_name)
            for label, href in companies:
                ln = norm_name(label)
                if ln and raw_n and (ln == raw_n or raw_n in ln or ln in raw_n):
                    return label, href
        return companies[0]

    person = pick_person()
    if person:
        return person
    if companies:
        return companies[0]
    if raw_name:
        return raw_name, author_href(
            card, raw_name, base_url, author_link_selector, prefer_company=prefer_company
        )

    return "Unknown", ""
