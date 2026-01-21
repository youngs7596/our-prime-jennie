import asyncio
from playwright.async_api import async_playwright
import os

DASHBOARD_URL = "http://localhost"

async def run():
    async with async_playwright() as p:
        # Launch browser (headless for server environment)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()

        print("1. Navigating to Dashboard login...")
        try:
            await page.goto("http://localhost")
            # Wait for potential redirect
            await page.wait_for_load_state('networkidle')
            
            # Check if login is needed (look for login inputs)
            # Login.tsx uses placeholder="admin" for username and type="password" for password
            if await page.locator('input[placeholder="admin"]').count() > 0 or "login" in page.url:
                print("   Logging in...")
                await page.fill('input[placeholder="admin"]', 'admin')
                await page.fill('input[type="password"]', 'q1w2e3R$')
                await page.click('button[type="submit"]') # Assuming standard submit button
                await page.wait_for_load_state('networkidle')
                print("   Login submitted.")
            else:
                print("   Already logged in or no login found.")

            # Ensure we are on the dashboard
            await page.wait_for_timeout(2000) # Wait for SPA transition
            
            # 2. Capture Overview
            print("2. Capturing Overview...")
            await page.screenshot(path="docs/screenshots/dashboard_overview.png")
            
            # 3. Capture Portfolio & Check Naver Links
            print("3. Navigating to Portfolio...")
            # Try clicking the sidebar link if possible, or force navigate
            await page.goto("http://localhost/portfolio")
            await page.wait_for_load_state('networkidle')
            print("   Waiting for data load (10s)...")
            await page.wait_for_timeout(10000) # Wait for data load (extended)
            
            # Scroll down to ensure list is rendered
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Capture screenshot
            await page.screenshot(path="docs/screenshots/dashboard_portfolio.png")
            # Dump HTML for debug
            with open("docs/screenshots/portfolio_dump.html", "w") as f:
                f.write(await page.content())
            
            # Check for Naver links
            # Try various selectors for Naver icon/link
            naver_links = await page.locator('a[href*="finance.naver.com"]').count()
            naver_icon_n = await page.locator('text="N"').count() # Rough check for 'N' icon text
            
            # Check for empty state
            empty_state = await page.locator('text="보유 종목이 없습니다"').count()
            no_results = await page.locator('text="검색 결과가 없습니다"').count()
            
            if empty_state > 0:
                print("   [INFO] Portfolio is empty ('보유 종목이 없습니다'). Cannot verify Naver links.")
            elif no_results > 0:
                print("   [INFO] No search results ('검색 결과가 없습니다'). Cannot verify Naver links.")
            else:
                print(f"   Found {naver_links} Naver Finance links.")
                if naver_links > 0:
                    print("   [SUCCESS] Naver links are present.")
                else:
                    print("   [WARNING] Portfolio items exist but No Naver links found.")
                    # Debug: print page content snippet
                    content = await page.content()
                    print(f"   DEBUG: Page Content Length: {len(content)}")

            # 4. Capture Performance
            print("4. Navigating to Performance...")
            await page.goto(f"{DASHBOARD_URL}/performance")
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)
            await page.screenshot(path="docs/screenshots/dashboard_performance.png")

            # 5. System Page
            print("5. Navigating to System...")
            await page.goto(f"{DASHBOARD_URL}/system")
            await page.wait_for_selector("text=System Status", state="visible")
            await page.wait_for_timeout(2000) # Wait for metrics to load
            await page.screenshot(path="docs/screenshots/dashboard_system.png")
            
            # Check for Real-time Watcher Status
            if await page.is_visible("text=Real-time Watcher Status"):
                 print("[SUCCESS] Real-time Watcher Status section found.")
                 # Check if it shows metrics (not 'offline')
                 if await page.is_visible("text=Tick Count"):
                     print("[SUCCESS] Real-time metrics (Tick Count) are visible.")
                 else:
                     print("[WARNING] Real-time metrics not visible (might be offline).")
            else:
                 print("[ERROR] Real-time Watcher Status section NOT found.")

            # Check that Scheduler Jobs is GONE
            if not await page.is_visible("text=Scheduler Jobs"):
                 print("[SUCCESS] Scheduler Jobs section is correctly removed.")
            else:
                 print("[ERROR] Scheduler Jobs section is STILL present.")
                 
            # Check that Oracle Cloud is GONE
            content = await page.content()
            if "Oracle Cloud" not in content:
                 print("[SUCCESS] Oracle Cloud (ATP) references are correctly removed.")
            else:
                 print("[ERROR] Oracle Cloud (ATP) references are STILL present.")

            # 6. Capture Settings
            print("6. Navigating to Settings...")
            await page.goto(f"{DASHBOARD_URL}/settings")
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)
            await page.screenshot(path="docs/screenshots/dashboard_settings.png")
            
            print("Done. Screenshots saved to docs/screenshots/")
            
        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="docs/screenshots/error_state.png")
        
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
