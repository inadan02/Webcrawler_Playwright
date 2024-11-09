from playwright.sync_api import sync_playwright
from tld import get_fld
import tqdm, tqdm.contrib.logging
import argparse
import os
import json
import time
import logging as log
import datetime

class StatisticsCrawler:
    # Tracks statistics for analysis, separated by crawl type (news or gov)
    def __init__(self):
        self.stats = {
            "news": {
                "consent_click_failure": set(),
                "page_load_timeout": set(),
                "page_load_times": [],
            },
            "gov": {
                "consent_click_failure": set(),
                "page_load_timeout": set(),
                "page_load_times": [],
            }
        }

    def update_stat_single_set(self, stat_name, crawl_type, value):
        self.stats[crawl_type][stat_name].add(value)

    def record_page_load_time(self, crawl_type, url, page_load_time):
        self.stats[crawl_type]["page_load_times"].append({"url": url, "page_load_time": page_load_time})

    # def export_to_json(self):
    #     def convert_to_serializable(obj):
    #         if isinstance(obj, set):
    #             return list(obj)
    #         return obj
    #     with open(f"../analysis/stats.json", "w") as file:
    #         json.dump(self.stats, file, indent=4, default=convert_to_serializable)

def parse_arguments():
    parser = argparse.ArgumentParser(description='Crawler with options')
    parser.add_argument('-u', metavar='URL', help='Single URL to crawl')
    parser.add_argument('-l', metavar='FILE', help='File containing list of URLs to crawl')
    parser.add_argument('--crawl-type', choices=['gov', 'news'],  help='Specify the crawl type: gov or news')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    url = args.u
    file_path = args.l
    crawl_type = args.crawl_type
    debug = args.debug
    urls = read_lines_of_file(file_path, crawl_type) if file_path else [ensure_http_prefix(url)] if url else []
    log.basicConfig(format='%(levelname)s: %(message)s', level=log.DEBUG if debug else log.INFO)
    log.getLogger('asyncio').setLevel(log.WARNING)
    return crawl_type, urls

def ensure_http_prefix(url):
    # Ensure URL has the https:// prefix
    if not url.startswith("http://") and not url.startswith("https://"):
        return "https://" + url
    return url

def read_lines_of_file(file_path, crawl_type):
    with open(file_path, 'r') as file:
        urls = [ensure_http_prefix(line.strip()) for line in file]
    return [url for url in urls if (crawl_type == "gov" ) or (crawl_type == "news" )]

def accept_cookie(page, stats_crawler, url, crawl_type):
    accept_words = []
    with open("../utils/accept_words.txt", 'r', encoding="utf-8") as file:
        accept_words = [line.strip() for line in file if line.strip()]
    accept_classes = [
        "iubenda-cs-accept-btn",  
        "btn-accept",  
        "accept",  
    ]
    found_accept_button = False
    def search_and_click_in_frame(frame):
        nonlocal found_accept_button

        for class_name in accept_classes:
            accept_button = frame.query_selector(f'.{class_name}')
            if accept_button and accept_button.is_visible():
                found_accept_button_or_link = True
                try:
                    accept_button.click()
                    frame.wait_for_timeout(1000)
                    # Fallback to JavaScript click if standard click fails
                    if accept_button.is_visible():
                        frame.evaluate("button => button.click()", accept_button)
                        frame.wait_for_timeout(1000)
                except Exception as e:
                    log.debug(f"Click failed on button with class '{class_name}': {e}")
                return True

        for word in accept_words:
            accept_button = frame.query_selector(f'button:has-text("{word}")')
            if accept_button and accept_button.is_visible():
                found_accept_button = True
                try:
                    accept_button.click()
                    frame.wait_for_timeout(1000)
                    if accept_button.is_visible():
                        frame.evaluate("button => button.click()", accept_button)
                        frame.wait_for_timeout(1000)
                except Exception as e:
                    log.debug(f"Click failed on '{word}': {e}")
                return True
        return False
    if search_and_click_in_frame(page):
        return page
    for iframe in page.frames:
        try:
            if search_and_click_in_frame(iframe):
                return page
        except Exception as e:
            log.debug(f"Error while interacting with iframe: {e}")
            continue
    if not found_accept_button:
        log.debug("Failed to find and click accept button")
        domain_of_url = get_fld(url)
        stats_crawler.update_stat_single_set("consent_click_failure", crawl_type, domain_of_url)
    return page

def scroll_to_bottom_in_multiple_steps(page):
    max_height = page.evaluate("document.body.scrollHeight")
    scroll_step = 200
    scroll_position = 0
    while scroll_position < max_height:
        page.evaluate(f"window.scrollBy(0, {scroll_step})")
        scroll_position += scroll_step
        page.wait_for_timeout(100)
    page.evaluate(f"window.scrollBy(0, {scroll_step*20})")
    return page

# def crawler(playwright, url, stats_crawler, url_index, crawl_type):
#     browser = playwright.chromium.launch(headless=True, slow_mo=50)
#     context = browser.new_context()
#     url_domain = get_fld(url)
#     output_dir = f"../crawl_data_{crawl_type}"
#     os.makedirs(output_dir, exist_ok=True)
#     har_file_path = os.path.join(output_dir, f"{url_domain}_{crawl_type}.har")
#     context = browser.new_context(
#         record_video_dir=output_dir,
#         record_video_size={"width": 640, "height": 480},
#         record_har_path=har_file_path
#     )
#     page = context.new_page()
#     start_time = time.time()
#     page.goto(url)
#     page.wait_for_load_state('load')
#     page_load_time = time.time() - start_time
#     stats_crawler.record_page_load_time(crawl_type, url, page_load_time)
#     page.wait_for_timeout(10000)
#     page.screenshot(path=os.path.join(output_dir, f"{url_domain}_{crawl_type}_pre_consent.png"))
#     try:
#         page = accept_cookie(page, stats_crawler, url, crawl_type)
#     except:
#         stats_crawler.update_stat_single_set("page_load_timeout", crawl_type, url_domain)
#     page.screenshot(path=os.path.join(output_dir, f"{url_domain}_{crawl_type}_post_consent.png"))
#     page.wait_for_timeout(3000)
#     page = scroll_to_bottom_in_multiple_steps(page)
#     page.wait_for_timeout(3000)
#     video_path = page.video.path()
#     new_video_path = os.path.join(output_dir, f"{url_domain}_{crawl_type}.webm")
#     os.replace(video_path, new_video_path)
#     context.close()
#     browser.close()

import time  # Import time to use sleep

def crawler(playwright, url, stats_crawler, url_index, crawl_type):
    browser = playwright.chromium.launch(headless=True, slow_mo=50)
    url_domain = get_fld(url)
    output_dir = f"../crawl_data_{crawl_type}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Set paths for HAR and video files
    har_file_path = os.path.join(output_dir, f"{url_domain}_{crawl_type}.har")
    video_output_path = os.path.join(output_dir, f"{url_domain}_{crawl_type}.webm")

    context = browser.new_context(
        record_video_dir=output_dir,
        record_video_size={"width": 640, "height": 480},
        record_har_path=har_file_path
    )
    
    page = context.new_page()
    start_time = time.time()
    page.goto(url)
    page.wait_for_load_state('load')
    page_load_time = time.time() - start_time
    stats_crawler.record_page_load_time(crawl_type, url, page_load_time)
    
    # Implement the waiting sequence as required
    page.wait_for_timeout(10000)  # Wait 10 seconds
    page.screenshot(path=os.path.join(output_dir, f"{url_domain}_{crawl_type}_pre_consent.png"))
    
    # Attempt to accept cookies
    try:
        page = accept_cookie(page, stats_crawler, url, crawl_type)
    except Exception as e:
        log.debug(f"Error accepting cookies on {url}: {e}")
        stats_crawler.update_stat_single_set("page_load_timeout", crawl_type, url_domain)
    
    page.screenshot(path=os.path.join(output_dir, f"{url_domain}_{crawl_type}_post_consent.png"))
    page.wait_for_timeout(3000)  # Wait 3 seconds after accepting cookies
    page = scroll_to_bottom_in_multiple_steps(page)
    page.wait_for_timeout(3000)  # Wait 3 seconds after scrolling
    
    # Close the page and context to ensure files are released
    video_path = page.video.path()
    page.close()  # Close the page explicitly
    context.close()  # Close the context to finalize HAR and video recording
    
    # Wait briefly to ensure the file is fully written and released
    time.sleep(1)
    
    # Rename/move the video file
    try:
        os.replace(video_path, video_output_path)
    except Exception as e:
        log.error(f"Failed to move video file for {url}: {e}")
    
    # Ensure browser is fully closed
    browser.close()


def run_crawler(playwright, url, stats_crawler, url_index, num_urls, crawl_type):
    log.debug(f'{url_index + 1}/{num_urls} Running crawler on {url} ({crawl_type})')
    try:
        crawler(playwright, url, stats_crawler, url_index, crawl_type)
    except Exception as e:
        log.error(f"Failed to crawl page {url}: {e}")

def main():
    crawl_type, urls = parse_arguments()
    stats_crawler = StatisticsCrawler()
    with sync_playwright() as playwright:
        with tqdm.contrib.logging.logging_redirect_tqdm():
            for url_index, url in tqdm.tqdm(enumerate(urls), total=len(urls)):
                run_crawler(playwright, url, stats_crawler, url_index, len(urls), crawl_type)
    # stats_crawler.export_to_json()


#python crawl.py -u rtl.de --debug --crawl-type news 
#python crawl.py -l ../utils/news_sites.txt --debug --crawl-type news
if __name__ == "__main__":
    main()
