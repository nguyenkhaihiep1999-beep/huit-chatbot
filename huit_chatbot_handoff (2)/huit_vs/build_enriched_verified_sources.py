#!/usr/bin/env python3
"""Build a rich, official-source-only HUIT admissions dataset.

Major profiles are discovered from the current HUIT undergraduate listing and
trimmed to the sections that improve semantic retrieval: overview, curriculum
strengths, and career opportunities. Admission rules are intentionally excluded
from major pages because they change by year and are maintained in CORE_PAGES.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from build_full_huit_dataset import MAJORS_DATA
from build_verified_huit_sources import CORE_PAGES
from scrape_realtime_huit import BASE_URL, fetch_url


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
LISTING_URLS = [f"{BASE_URL}/nganh-dh?page={page}" for page in range(1, 6)]
ALLOWED_CODES = {major["code"]: major for major in MAJORS_DATA}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or "").lower())
    value = "".join(
        char for char in value if unicodedata.category(char) != "Mn"
    ).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def discover_profile_urls() -> list[str]:
    urls = set()
    expected_names = {normalize(major["name"]) for major in MAJORS_DATA}
    for listing_url in LISTING_URLS:
        soup = fetch_url(listing_url)
        if not soup:
            continue
        for anchor in soup.find_all("a", href=True):
            label = normalize(anchor.get_text(" ", strip=True))
            label = re.sub(r"^nganh\s+", "", label)
            if label not in expected_names:
                continue
            url = urljoin(BASE_URL, anchor["href"]).split("#", 1)[0]
            if url.startswith(f"{BASE_URL}/"):
                urls.add(url)
    return sorted(urls)


def clean_lines(text: str) -> str:
    lines = []
    seen = set()
    for raw_line in text.replace("\xa0", " ").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" |")
        if not line or line in {"---", "Image", "iframe"}:
            continue
        fingerprint = normalize(line)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        lines.append(line)
    return "\n".join(lines)


def extract_profile(url: str) -> dict | None:
    soup = fetch_url(url, timeout=20)
    if not soup:
        return None

    title_node = soup.find("h1")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    content = (
        soup.select_one(".post-body")
        or soup.select_one(".post-content")
        or soup.select_one(".contain-content")
        or soup.find("article")
        or soup.find("main")
        or soup.find("body")
    )
    if not content:
        return None

    for tag in content.find_all(
        ["script", "style", "nav", "footer", "header", "form", "iframe"]
    ):
        tag.decompose()
    text = clean_lines(content.get_text("\n", strip=True))
    # Some HUIT templates place the code outside the selected article wrapper.
    full_text = clean_lines(soup.get_text("\n", strip=True))
    code_match = re.search(r"\b7\d{6}\b", text)
    if not code_match or code_match.group(0) not in ALLOWED_CODES:
        code_match = re.search(r"\b7\d{6}\b", full_text)
    if not code_match or code_match.group(0) not in ALLOWED_CODES:
        normalized_title = normalize(title)
        name_matches = [
            code for code, major in ALLOWED_CODES.items()
            if normalize(major["name"]) in normalized_title
        ]
        if len(name_matches) == 1:
            code_match = re.search(name_matches[0], name_matches[0])
    if not code_match:
        return None

    code = code_match.group(0)
    major = ALLOWED_CODES[code]
    start = text.find(code)
    if start < 0:
        # The title is a safer boundary than using unrelated navigation text.
        title_position = normalize(text).find(normalize(major["name"]))
        if title_position >= 0:
            start = 0
    if start >= 0:
        text = text[start:]

    # Keep stable program/career facts; yearly admission rules live elsewhere.
    stop_markers = [
        "3. ĐIỀU KIỆN TUYỂN SINH",
        "3. ĐIỀU KIỆN XÉT TUYỂN",
        "3. PHƯƠNG THỨC TUYỂN SINH",
        "Để biết thêm thông tin",
        "Để biết thêm thông tin",
    ]
    stop_positions = [
        text.find(marker) for marker in stop_markers if text.find(marker) > 0
    ]
    if stop_positions:
        text = text[: min(stop_positions)]
    text = text.strip()

    if len(text) < 300:
        return None
    return {
        "url": url,
        "title": f"Ngành {major['name']}",
        "markdown": (
            f"# Ngành {major['name']}\n\n"
            f"- Mã ngành: {code}\n"
            "- Hệ đào tạo: Đại học chính quy HUIT.\n"
            "- Nguồn nội dung: trang giới thiệu ngành chính thức của HUIT.\n\n"
            f"{text}"
        ),
        "official": True,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": "ts.huit.edu.vn",
        "content_scope": "overview_curriculum_careers",
    }


def build() -> list[dict]:
    urls = discover_profile_urls()
    print(f"[1/3] Discovered {len(urls)} current HUIT major profile URLs.")
    profiles = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(extract_profile, url): url for url in urls}
        for future in as_completed(futures):
            profile = future.result()
            if profile:
                profiles.append(profile)
                print(
                    f"  [+] {profile['title']}: "
                    f"{len(profile['markdown'])} characters"
                )

    by_code = {}
    for profile in profiles:
        code = re.search(r"\b7\d{6}\b", profile["markdown"]).group(0)
        current = by_code.get(code)
        if current is None or len(profile["markdown"]) > len(current["markdown"]):
            by_code[code] = profile

    missing = sorted(set(ALLOWED_CODES) - set(by_code))
    if missing:
        raise RuntimeError(
            f"Missing {len(missing)} official major profiles: {', '.join(missing)}"
        )
    if len(by_code) != 39:
        raise RuntimeError(f"Expected 39 unique majors, found {len(by_code)}.")

    ordered_profiles = [
        by_code[major["code"]] for major in MAJORS_DATA
    ]
    docs = ordered_profiles + CORE_PAGES
    print(f"[2/3] Validated {len(ordered_profiles)} unique official profiles.")
    return docs


def main() -> None:
    docs = build()
    (HERE / "scraped_pages.json").write_text(
        json.dumps(docs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (HERE / "urls_to_scrape.json").write_text(
        json.dumps([doc["url"] for doc in docs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[3/3] Saved {len(docs)} verified documents to scraped_pages.json."
    )


if __name__ == "__main__":
    main()
