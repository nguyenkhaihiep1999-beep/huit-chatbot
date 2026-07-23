#!/usr/bin/env python3
"""
scrape_realtime_huit.py
Cào tự động dữ liệu tuyển sinh thời gian thực từ https://ts.huit.edu.vn
- 39 Ngành đào tạo đại học chính quy (/nganh-dh)
- Thông báo tuyển sinh, điểm sàn, phương thức xét tuyển, đề án tuyển sinh
- Xuất ra scraped_pages.json và urls_to_scrape.json
"""

import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPED_JSON = os.path.join(HERE, "scraped_pages.json")
URLS_JSON = os.path.join(HERE, "urls_to_scrape.json")

BASE_URL = "https://ts.huit.edu.vn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_url(url, timeout=12):
    """Fetch URL and return BeautifulSoup object."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            return BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"[WARN] Error fetching {url}: {e}")
        return None


def get_all_major_urls():
    """Discover all 39 major URLs from paginated /nganh-dh."""
    major_urls = set()
    for page in range(1, 7):
        url = f"{BASE_URL}/nganh-dh?page={page}"
        soup = fetch_url(url)
        if not soup:
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "/nganh-dh/" in href:
                full_url = href if href.startswith("http") else BASE_URL + href
                major_urls.add(full_url)
    return sorted(list(major_urls))


def get_admission_notices_urls():
    """Discover latest admission notices, cutoff scores, schemes & news."""
    categories = [
        f"{BASE_URL}/tin-tuyen-sinh",
        f"{BASE_URL}/thong-bao",
        f"{BASE_URL}/de-an",
        f"{BASE_URL}/tin-huong-nghiep",
    ]
    notice_urls = set()
    for cat_url in categories:
        soup = fetch_url(cat_url)
        if not soup:
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if any(path in href for path in ["/tin-tuyen-sinh/", "/thong-bao/", "/de-an/", "/tin-huong-nghiep/"]):
                if not href.endswith(("/tin-tuyen-sinh", "/thong-bao", "/de-an", "/tin-huong-nghiep")):
                    full_url = href if href.startswith("http") else BASE_URL + href
                    notice_urls.add(full_url)
    return sorted(list(notice_urls))


def html_to_clean_markdown(soup, url):
    """Convert HTML content to clean Markdown text, removing navigation & headers/footers."""
    # Find main article content container
    content_div = (
        soup.find("div", class_=re.compile(r"content|detail|post|article|main", re.I))
        or soup.find("article")
        or soup.find("body")
    )
    if not content_div:
        return "", ""

    # Remove unwanted tags (scripts, styles, navs, footers, headers)
    for tag in content_div.find_all(["script", "style", "nav", "footer", "header", "form", "iframe"]):
        tag.decompose()

    # Extract title
    h1 = soup.find("h1")
    title = h1.text.strip() if h1 else (soup.title.string.strip() if soup.title else "Thông tin tuyển sinh HUIT")

    lines = [f"# {title}", ""]

    # Extract text & markdown formatting
    for elem in content_div.find_all(["h1", "h2", "h3", "h4", "p", "table", "ul", "ol"]):
        if elem.name in ["h1", "h2", "h3", "h4"]:
            level = "#" * int(elem.name[1])
            text = elem.text.strip()
            if text:
                lines.append(f"\n{level} {text}\n")
        elif elem.name == "p":
            text = elem.text.strip()
            if text and not text.startswith(("Trang chủ", "HUIT - Trường Đại học", "Thống kê truy cập")):
                lines.append(text)
        elif elem.name in ["ul", "ol"]:
            for li in elem.find_all("li"):
                t = li.text.strip()
                if t:
                    lines.append(f"- {t}")
        elif elem.name == "table":
            # Simple markdown table conversion
            rows = []
            for tr in elem.find_all("tr"):
                cells = [td.text.strip().replace("\n", " ") for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
            if len(rows) > 1:
                header = rows[0]
                sep = "| " + " | ".join(["---"] * len(rows[0].split("|")[1:-1])) + " |"
                lines.extend(["", header, sep] + rows[1:] + [""])

    markdown_text = "\n".join(lines)
    # Basic clean-up of excess blank lines
    markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text)
    return title, markdown_text.strip()


def scrape_page(url):
    """Scrape a single page URL and return standard document dict."""
    soup = fetch_url(url)
    if not soup:
        return None
    title, markdown = html_to_clean_markdown(soup, url)
    if not markdown or len(markdown) < 100:
        return None
    return {
        "url": url,
        "title": f"{title} - Tuyển Sinh HUIT",
        "markdown": markdown
    }


def run_realtime_scrape():
    print("=========================================================")
    print("   HUIT ADMISSIONS REAL-TIME DATA SCRAPER")
    print("=========================================================")

    print("\n[1/4] Discovering all 39 undergraduate major URLs...")
    major_urls = get_all_major_urls()
    print(f"      Found {len(major_urls)} major URLs.")

    print("\n[2/4] Discovering latest admission notices & rules URLs...")
    notice_urls = get_admission_notices_urls()
    print(f"      Found {len(notice_urls)} admission notice URLs.")

    all_urls = sorted(list(set(major_urls + notice_urls)))
    print(f"\n[3/4] Scraping {len(all_urls)} target pages in parallel...")

    scraped_docs = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(scrape_page, url): url for url in all_urls}
        for future in as_completed(futures):
            res = future.result()
            if res:
                scraped_docs.append(res)
                print(f"  [+] Scraped: {res['title'][:60]}... ({len(res['markdown'])} chars)")

    print(f"\n[4/4] Saving {len(scraped_docs)} documents to disk...")
    # Write scraped_pages.json
    with open(SCRAPED_JSON, "w", encoding="utf-8") as f:
        json.dump(scraped_docs, f, ensure_ascii=False, indent=2)

    # Write urls_to_scrape.json
    scraped_urls = [d["url"] for d in scraped_docs]
    with open(URLS_JSON, "w", encoding="utf-8") as f:
        json.dump(scraped_urls, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] Scraped & saved {len(scraped_docs)} pages to {SCRAPED_JSON}")
    return len(scraped_docs)


if __name__ == "__main__":
    run_realtime_scrape()
