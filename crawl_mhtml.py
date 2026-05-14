import asyncio
import zipfile
import os
import re
import argparse
import shutil
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from collections import deque
from typing import Set, List
import json

def sanitize_filename(name: str) -> str:
    """Remove invalid characters for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def normalize_url(base_url: str, link: str) -> str:
    """Convert relative link to absolute URL and remove fragments."""
    absolute = urljoin(base_url, link)
    # Remove fragment (#anything) to avoid duplicate pages
    return absolute.split('#')[0]

def is_same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs belong to the same domain."""
    domain1 = urlparse(url1).netloc
    domain2 = urlparse(url2).netloc
    return domain1 == domain2

async def scroll_page(page):
    """Gradual scroll to trigger lazy loading."""
    await page.evaluate("""
        async () => {
            const scrollStep = 500;
            const delay = 100;
            let current = 0;
            const maxScroll = document.body.scrollHeight - window.innerHeight;
            while (current < maxScroll) {
                window.scrollBy(0, scrollStep);
                current += scrollStep;
                await new Promise(r => setTimeout(r, delay));
            }
            window.scrollTo(0, 0);
        }
    """)

async def simulate_hover(page):
    """Hover over common interactive elements."""
    selectors = ['button', 'a', '[role="button"]', '.dropdown-trigger', '.nav-item', '[onmouseenter]']
    for selector in selectors:
        try:
            elements = await page.locator(selector).all()
            for elem in elements:
                if await elem.is_visible():
                    await elem.hover()
                    await asyncio.sleep(0.1)
        except:
            pass

async def extract_links(page, base_url: str, visited: Set[str]) -> List[str]:
    """Extract all <a> href links from page, filter to same domain, not visited."""
    links = await page.eval_on_selector_all('a', 'els => els.map(el => el.href)')
    new_links = []
    for link in links:
        if not link:
            continue
        normalized = normalize_url(base_url, link)
        if not normalized.startswith('http'):
            continue
        if not is_same_domain(base_url, normalized):
            continue
        if normalized not in visited:
            new_links.append(normalized)
    return list(dict.fromkeys(new_links))  # remove duplicates

async def save_mhtml_and_extract(url: str, output_file: str, visited: Set[str]) -> List[str]:
    """
    Download one page as MHTML, extract links, and return new URLs.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-web-security',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage'
            ]
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # Stealth
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)

        print(f"🌐 Downloading: {url}")
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(2)

        # Interact to reveal content
        await scroll_page(page)
        await asyncio.sleep(1)
        await simulate_hover(page)
        await asyncio.sleep(2)

        # Extract links BEFORE taking snapshot (they are in DOM)
        new_links = await extract_links(page, url, visited)

        # Take MHTML snapshot
        cdp = await page.context.new_cdp_session(page)
        mhtml = await cdp.send('Page.captureSnapshot')
        with open(output_file, 'wb') as f:
            f.write(mhtml['data'].encode())

        await browser.close()
        print(f"✅ Saved: {url} -> {os.path.basename(output_file)}")
        return new_links

async def crawl(start_url: str, max_pages: int = 50, output_dir: str = "download"):
    """
    Main crawling logic: BFS over same-domain URLs.
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    visited = set()
    queue = deque([start_url])
    all_links = {}  # map url -> list of extracted links (for debugging)

    # For naming: use domain as base folder? We'll put all MHTMLs in download/
    # But to avoid name collisions, we'll use a counter or full URL hash.
    # Simpler: use sanitized URL path as filename.
    counter = 0

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        # Generate filename
        parsed = urlparse(url)
        path_part = parsed.path.strip('/').replace('/', '_') if parsed.path else "index"
        if not path_part:
            path_part = "index"
        # Truncate long names
        if len(path_part) > 80:
            path_part = path_part[:80]
        filename = f"{path_part}.mhtml"
        mhtml_path = os.path.join("temp", filename)

        try:
            new_links = await save_mhtml_and_extract(url, mhtml_path, visited)
            # Save the MHTML permanently
            final_mhtml_path = os.path.join(output_dir, filename)
            shutil.move(mhtml_path, final_mhtml_path)
            all_links[url] = new_links

            # Add new links to queue
            for link in new_links:
                if link not in visited and link not in queue:
                    queue.append(link)
            print(f"📌 Found {len(new_links)} new links. Queue size: {len(queue)}")

        except Exception as e:
            print(f"❌ Failed to download {url}: {e}")
            if os.path.exists(mhtml_path):
                os.remove(mhtml_path)

        counter += 1
        # Optional delay to be nice to server
        await asyncio.sleep(1)

    # Save the link map as JSON
    map_path = os.path.join(output_dir, "extracted_links_map.json")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(all_links, f, indent=2)
    print(f"📄 Link map saved to {map_path}")

    # Also save as simple list of all discovered URLs
    all_urls_path = os.path.join(output_dir, "all_discovered_urls.txt")
    with open(all_urls_path, "w", encoding="utf-8") as f:
        for url in visited:
            f.write(url + "\n")
    print(f"📄 All URLs saved to {all_urls_path}")

    # Cleanup temp
    shutil.rmtree("temp", ignore_errors=True)
    print(f"✅ Crawling finished. Downloaded {len(visited)} pages.")

def main():
    parser = argparse.ArgumentParser(description="Crawl and download full website as MHTML files.")
    parser.add_argument("--url", required=True, help="Starting URL")
    parser.add_argument("--max", type=int, default=50, help="Maximum pages to download")
    parser.add_argument("--output", default="download", help="Output directory")
    args = parser.parse_args()

    asyncio.run(crawl(args.url, args.max, args.output))

if __name__ == "__main__":
    main()
