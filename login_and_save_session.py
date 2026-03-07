#!/usr/bin/env python3
"""
One-off script: open ECOES, wait for you to log in in the browser, then save
the session to ecoes_session.json so the main scraper can reuse it.

Run with: ECOES_HEADLESS=false python login_and_save_session.py
Then run: python scrape_all_communications.py
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

import config


def main() -> None:
    with sync_playwright() as p:
        browser = p[config.BROWSER].launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(config.BASE_URL + config.SECURE_COMMS_PATH, wait_until="domcontentloaded")
        print("Log in in the browser. When you see the Secure Communications list, press Enter here.")
        input()
        context.storage_state(path=config.STORAGE_STATE_PATH)
        print(f"Session saved to {config.STORAGE_STATE_PATH}")
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
