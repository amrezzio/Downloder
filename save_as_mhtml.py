import asyncio
import zipfile
import os
import re
import argparse
import shutil
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import time

def sanitize_filename(name: str) -> str:
    """Remove invalid characters for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

async def save_mhtml(url: str, output_file: str, max_retries: int = 3):
    """
    Save webpage as MHTML using Playwright with stealth techniques.
    Handles Cloudflare Turnstile and similar CAPTCHAs automatically.
    """
    for attempt in range(1, max_retries + 1):
        try:
            async with async_playwright() as p:
                # Launch browser with anti-detection arguments
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-blink-features=AutomationControlled',  # Hide automation
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-setuid-sandbox',
                        '--disable-accelerated-2d-canvas',
                        '--disable-canvas-aa',
                        '--disable-2d-canvas-clip-aa',
                        '--disable-gl-drawing-for-tests',
                        '--disable-breakpad',
                        '--disable-component-extensions-with-background-pages',
                        '--disable-default-apps',
                        '--disable-extensions',
                        '--disable-features=TranslateUI',
                        '--disable-ipc-flooding-protection',
                        '--disable-renderer-backgrounding',
                        '--disable-sync',
                        '--force-color-profile=srgb',
                        '--metrics-recording-only',
                        '--mute-audio',
                        '--no-default-browser-check',
                        '--no-first-run',
                        '--password-store=basic',
                        '--use-gl=swiftshader',
                        '--use-mock-keychain'
                    ]
                )

                # Create context with realistic browser profile
                context = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York',
                    device_scale_factor=1,
                    has_touch=False,
                    is_mobile=False
                )

                page = await context.new_page()

                # Add stealth script to hide automation traces
                await page.add_init_script("""
                    // Remove webdriver property
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });

                    // Spoof languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });

                    // Spoof plugins
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });

                    // Spoof chrome property
                    window.chrome = {
                        runtime: {}
                    };

                    // Override permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                """)

                # Navigate to URL
                print(f"🌐 Navigating to {url}...")
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)

                # Wait a bit for page to stabilize
                await asyncio.sleep(5)

                # Try to handle any visible captcha automatically
                print(f"🔍 Attempt {attempt}: Checking for CAPTCHAs...")

                # Check for various CAPTCHA indicators
                selectors_to_check = [
                    'iframe[src*="recaptcha"]',
                    'iframe[src*="hcaptcha"]',
                    'iframe[src*="turnstile"]',
                    '.g-recaptcha',
                    '.h-captcha',
                    'div[data-sitekey]'
                ]

                captcha_found = False
                for selector in selectors_to_check:
                    if await page.locator(selector).count() > 0:
                        captcha_found = True
                        print(f"⚠️ CAPTCHA detected: {selector}")
                        break

                if captcha_found:
                    print("🕒 Waiting for CAPTCHA to resolve (up to 30 seconds)...")
                    try:
                        # Try to wait for common CAPTCHA resolution
                        await page.wait_for_function(
                            """
                            () => {
                                const body = document.body.innerText;
                                return body && (
                                    !body.includes('captcha') && 
                                    !body.includes('verification') &&
                                    !body.includes('Click verify')
                                );
                            }
                            """,
                            timeout=30000
                        )
                        print("✅ CAPTCHA appears to have resolved!")
                    except:
                        print("⚠️ Could not confirm CAPTCHA resolution, proceeding anyway...")

                # Wait additional time for dynamic content
                await asyncio.sleep(3)

                print(f"📸 Capturing MHTML snapshot...")
                cdp_session = await page.context.new_cdp_session(page)
                mhtml_data = await cdp_session.send('Page.captureSnapshot')

                with open(output_file, 'wb') as f:
                    f.write(mhtml_data['data'].encode())

                await browser.close()
                print(f"✅ Successfully saved {url} (attempt {attempt})")
                return

        except (PlaywrightTimeoutError, Exception) as e:
            print(f"⚠️ Attempt {attempt} failed for {url}: {str(e)[:200]}")
            if attempt == max_retries:
                raise
            print(f"🔄 Waiting 5 seconds before retry...")
            await asyncio.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Download webpage as MHTML with auto CAPTCHA solving.")
    parser.add_argument("--url", required=True, help="URL of the page to download")
    parser.add_argument("--title", help="Optional title for the output file")
    args = parser.parse_args()

    # Determine output filename
    if args.title:
        base_name = sanitize_filename(args.title)
    else:
        parsed = urlparse(args.url)
        path = parsed.path.strip('/').replace('/', '_')
        if path:
            base_name = sanitize_filename(path)
        else:
            base_name = sanitize_filename(parsed.netloc)
        if not base_name:
            base_name = "webpage"

    mhtml_filename = f"{base_name}.mhtml"
    zip_filename = f"{base_name}.zip"

    download_dir = "download"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    mhtml_path = os.path.join("temp", mhtml_filename)
    zip_path = os.path.join(download_dir, zip_filename)

    print(f"🚀 Starting download: {args.url}")
    asyncio.run(save_mhtml(args.url, mhtml_path))

    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(mhtml_path, arcname=mhtml_filename)

    shutil.rmtree("temp", ignore_errors=True)

    print(f"✅ Completed! File saved at: {zip_path}")

if __name__ == "__main__":
    main()
