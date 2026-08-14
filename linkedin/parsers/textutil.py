from __future__ import annotations

import re


def clean_author(raw: str) -> str:
    line = (raw or "").strip().split("\n")[0]
    line = re.sub(r"(?i)^view\s+company:\s*", "", line)
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


def social_skip_names(raw: str) -> set[str]:
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


def slug_to_name(href: str) -> str:
    m = re.search(r"/(?:in|company)/([^/?#]+)", href or "")
    if not m:
        return ""
    slug = m.group(1).replace("%20", " ").strip("-_")
    slug = slug.split("/")[0]
    slug = re.sub(r"-[a-z0-9]{5,}$", "", slug, flags=re.I)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\b\d+\b", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    if len(slug) < 2:
        return ""
    return slug.title()


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def is_skipped(name: str, skip: set[str]) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return True
    if n in skip:
        return True
    compact = norm_name(n)
    if not compact:
        return True
    for s in skip:
        sc = norm_name(s)
        if sc and (compact == sc or compact in sc or sc in compact):
            return True
    return False


def author_from_raw_lines(raw: str, skip: set[str]) -> str:
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
        name = clean_author(line)
        if 2 <= len(name) <= 80 and not is_skipped(name, skip):
            if len(name) > 60 and (" " in name and name.count(" ") >= 6):
                continue
            return name
    return ""


def body_from_text(raw: str, author: str = "") -> str:
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
