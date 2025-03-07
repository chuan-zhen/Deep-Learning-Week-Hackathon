import os
import time
import requests
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "OPENROUTER_API_KEY")

def initialize_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.142 Safari/537.36"
    )
    return webdriver.Chrome(options=chrome_options)

def extract_post_details(element):
    try:
        user_element = WebDriverWait(element, 10).until(
            EC.presence_of_element_located((By.XPATH, './/div[@data-testid="User-Name"]'))
        )
        user = user_element.find_element(By.XPATH, './/span[not(contains(text(), "@"))]').text
        handle = user_element.find_element(By.XPATH, './/span[starts-with(text(), "@")]').text
        if not handle.startswith("@"): handle = "@" + handle.lstrip("@")
        text_element = WebDriverWait(element, 10).until(
            EC.presence_of_element_located((By.XPATH, './/div[@data-testid="tweetText"]'))
        )
        text = element.parent.execute_script("return arguments[0].innerText;", text_element).strip()
        return f"{user} ({handle}): {text}"
    except (NoSuchElementException, TimeoutException):
        return None

def scrape_x_post(post_url):
    driver = initialize_driver()
    posts = []
    try:
        driver.get(post_url)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
        except TimeoutException:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//main//article'))
            )
        main_post = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]')
        main_details = extract_post_details(main_post)
        if main_details:
            posts.append(f"MAIN POST: {main_details}")
        else:
            return posts
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
        reply_sections = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, '//div[@data-testid="cellInnerDiv"][.//article[contains(@data-testid, "tweet")]]')
            )
        )[:5]
        for reply in reply_sections:
            reply_details = extract_post_details(reply)
            if reply_details:
                posts.append(f"REPLY: {reply_details}")
    finally:
        driver.quit()
    return posts

def clean_url(url):
    url = re.sub(r'[.,;:)]$', '', url)
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    major_domains = ['reuters.com', 'nytimes.com', 'washingtonpost.com', 'bbc.com']
    for domain in major_domains:
        if domain in url and not re.search(r'https?://www\.', url):
            url = url.replace('://', '://www.')
    return url

def validate_url(url, verbose=False):
    try:
        url = url.strip()
        url = clean_url(url)
        pattern = re.compile(
            r'^https?://' r'(?:www\.)?' r'[a-zA-Z0-9-]+' r'\.[a-zA-Z]{2,}' r'(?:/[^\s]*)?$', re.IGNORECASE
        )
        if not pattern.match(url): return False
        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
        if not domain_match: return False
        domain = domain_match.group(1).lower()
        TRUSTED_DOMAINS = {
            'reuters.com': True, 'apnews.com': True, 'bbc.com': True, 'nytimes.com': True,
            'washingtonpost.com': True, 'theguardian.com': True, 'cnn.com': True, 'npr.org': True
        }
        if any(trusted_domain in domain for trusted_domain in TRUSTED_DOMAINS): return True
        if domain.endswith('.gov') or domain.endswith('.edu'): return True
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        try:
            response = requests.get(url, timeout=10, headers=headers, allow_redirects=True)
            return 200 <= response.status_code < 300
        except requests.exceptions.RequestException:
            return any(major_domain in domain for major_domain in ['reuters.com', 'apnews.com', 'bbc.com', 'cnn.com'])
    except Exception:
        return False

def analyze_text(prompt):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek/deepseek-r1:free", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000, "temperature": 0.4, "stop": ["\n##"]}
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content'] if 'choices' in data else None
    except Exception:
        return None

def detect_bias(text):
    prompt = f"""Analyze this text for political bias.\n**Verdict**: [Left/Right/Neutral/Mixed]\n**Key Indicators**:\n- List item 1\n- List item 2\n- List item 3\n**Context Analysis**: [2-3 sentence explanation]\nText: "{text}""" 
    return analyze_text(prompt)

def main():
    url = input("Enter X.com post URL: ").strip()
    if not url.startswith(("http://", "https://")):
        print("Invalid URL format. Please include http:// or https://")
        return
    print("Scraping X.com post...")
    posts = scrape_x_post(url)
    if not posts:
        print("No content found. Check URL or try again later.")
        return
    print("\n--- Main Post Analysis ---")
    print(posts[0])
    print("\nBias Detection:")
    print(detect_bias(posts[0]))

if __name__ == "__main__":
    main()

