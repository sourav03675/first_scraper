from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})
executor = ThreadPoolExecutor(max_workers=20)

EPISODE_PREFIX = (
    "https://episodes.modpro.blog/",
    "https://links.modpro.blog/"
)

DOWNLOAD_PREFIX = "https://tech.unblockedgames.world/"
BATCH_KEYWORD = "batch/zip file"

def fetch_soup(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(
                url,
                timeout=20,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.google.com/",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
            )
            if resp.status_code == 200 and "<html" in resp.text.lower():
                return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"[Fetch Error Attempt {attempt}] {url} -> {e}")
    print(f"[FAILED] Could not fetch: {url}")
    return None

def starts_with_prefix(href, prefixes):
    href_lower = href.lower().rstrip("/")
    return any(href_lower.startswith(p.lower().rstrip("/")) for p in prefixes)

def find_heading_before(link_tag):
    wrapper = link_tag
    while wrapper.parent and wrapper.parent.name in ("a", "span", "strong", "em"):
        wrapper = wrapper.parent
    wrapper = wrapper.parent
    if wrapper is None:
        return None
    prev = wrapper.previous_sibling
    while prev:
        if hasattr(prev, "get_text"):
            text = prev.get_text(" ", strip=True)
            if text and len(text) > 3:
                return text
        if isinstance(prev, str):
            text = prev.strip()
            if len(text) > 3:
                return text
        prev = prev.previous_sibling
    parent = wrapper.parent
    if parent:
        prev_parent = parent.previous_sibling
        while prev_parent:
            if hasattr(prev_parent, "get_text"):
                text = prev_parent.get_text(" ", strip=True)
                if text and len(text) > 3:
                    return text
            if isinstance(prev_parent, str):
                text = prev_parent.strip()
                if len(text) > 3:
                    return text
            prev_parent = prev_parent.previous_sibling
    return None

def is_batch_tag(tag):
    combined = (tag.get_text(" ", strip=True) + " " +
                tag.parent.get_text(" ", strip=True)).lower()
    return BATCH_KEYWORD in combined

def scrape_secondary_links(url):
    soup = fetch_soup(url)
    if soup is None:
        return []
    results = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if href and href.startswith(DOWNLOAD_PREFIX):
            text_value = a.get_text(" ", strip=True) or a.parent.get_text(" ", strip=True)
            results.append({"url": href, "text": text_value})
    return results

def scrape_main_page(url):
    soup = fetch_soup(url)
    if soup is None:
        return {
            "regular": [],
            "batch": [],
            "error": "Unable to load main page (protection/timeout)."
        }
    regular = []
    batch = []
    for tag in soup.find_all("a"):
        href = tag.get("href")
        if href and starts_with_prefix(href, EPISODE_PREFIX):
            heading_text = find_heading_before(tag)
            episode_text = tag.get_text(" ", strip=True) or tag.parent.get_text(" ", strip=True)
            entry = {
                "heading": heading_text,
                "episode_link": href,
                "episode_text": episode_text,
                "download_links": []
            }
            if is_batch_tag(tag):
                batch.append(entry)
            else:
                regular.append(entry)
    all_items = regular + batch
    futures = {
        executor.submit(scrape_secondary_links, item["episode_link"]): item
        for item in all_items
    }
    for future in futures:
        item = futures[future]
        try:
            item["download_links"] = future.result()
        except Exception:
            item["download_links"] = []
    if len(regular) == 0 and len(batch) == 0:
        return {
            "regular": [],
            "batch": [],
            "error": "No episode links found — page may be protected or changed."
        }
    return {"regular": regular, "batch": batch}

@app.route("/scrape", methods=["GET"])
def scrape_api():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "Missing ?url="}), 400
    result = scrape_main_page(url)
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
