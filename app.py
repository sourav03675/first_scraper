import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

session = requests.Session()

# Stage 1: links to look for on the MAIN page
EPISODE_PREFIX = (
    "https://episodes.modpro.blog/",
    "https://links.modpro.blog/",
    "https://leechpro.blog/",          # NEW
)

# Stage 2: links to look for on each episode page
DOWNLOAD_PREFIX = (
    "https://en.thenaukriadda.in/",
    "https://cloud.unblockedgames.world/",   # NEW
)

BATCH_KEYWORD = "batch/zip file"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def fetch_soup(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=20, headers=REQUEST_HEADERS)
            if resp.status_code == 200 and "<html" in resp.text.lower():
                return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            print(f"[fetch_soup] attempt {attempt} failed for {url}: {e}")
        time.sleep(1)  # small delay between retries
    return None


def starts_with_prefix(href, prefixes):
    href_lower = href.strip().lower().rstrip("/")
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
            tx = prev.get_text(" ", strip=True)
            if tx and len(tx) > 3:
                return tx
        if isinstance(prev, str):
            tx = prev.strip()
            if len(tx) > 3:
                return tx
        prev = prev.previous_sibling
    return None


def is_batch_tag(tag):
    parent_text = tag.parent.get_text(" ", strip=True) if tag.parent else ""
    combined = (tag.get_text(" ", strip=True) + " " + parent_text).lower()
    return BATCH_KEYWORD in combined


def scrape_secondary_links(url):
    """Open an episode/leechpro page and collect thenaukriadda + unblockedgames links."""
    soup = fetch_soup(url)
    if soup is None:
        return []
    results = []
    seen = set()
    for a in soup.find_all("a"):
        href = a.get("href")
        if href and starts_with_prefix(href, DOWNLOAD_PREFIX) and href not in seen:
            seen.add(href)
            results.append({
                "url": href,
                "text": a.get_text(" ", strip=True),
            })
    return results


def scrape_main_page(url):
    soup = fetch_soup(url)
    if soup is None:
        return {"regular": [], "batch": [],
                "error": "Unable to load main page (protection/timeout)."}

    regular, batch = [], []
    seen_links = set()

    for tag in soup.find_all("a"):
        href = tag.get("href")
        if not href or not starts_with_prefix(href, EPISODE_PREFIX):
            continue

        heading = find_heading_before(tag)
        episode_text = tag.get_text(" ", strip=True)

        # skip exact duplicates (same link + same heading)
        key = (href, heading)
        if key in seen_links:
            continue
        seen_links.add(key)

        entry = {
            "heading": heading,
            "episode_link": href,
            "episode_text": episode_text,
            "download_links": [],
        }
        if is_batch_tag(tag):
            batch.append(entry)
        else:
            regular.append(entry)

    all_items = regular + batch

    # fetch each unique episode link only once
    unique_urls = list({i["episode_link"] for i in all_items})
    cache = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {u: ex.submit(scrape_secondary_links, u) for u in unique_urls}
        for u, f in futures.items():
            try:
                cache[u] = f.result()
            except Exception as e:
                print(f"[scrape_secondary_links] error for {u}: {e}")
                cache[u] = []

    for item in all_items:
        item["download_links"] = cache.get(item["episode_link"], [])

    return {"regular": regular, "batch": batch}


@app.route("/scrape", methods=["GET"])
def scrape_api():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "Missing ?url="}), 400
    return jsonify(scrape_main_page(url))


@app.route("/ping")
def ping():
    return "pong", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
