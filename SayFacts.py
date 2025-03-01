import os
import time
import requests
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# Load API key from environment variable or use default for development
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY",
                                    "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")


def initialize_driver():
    """Initialize and return a headless Chrome WebDriver with anti-detection options."""
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
    """Extract user and text details from a tweet element."""
    try:
        user_element = WebDriverWait(element, 10).until(
            EC.presence_of_element_located((By.XPATH, './/div[@data-testid="User-Name"]'))
        )
        # Extract display name and handle
        user = user_element.find_element(By.XPATH, './/span[not(contains(text(), "@"))]').text
        handle = user_element.find_element(By.XPATH, './/span[starts-with(text(), "@")]').text
        if not handle.startswith("@"):
            handle = "@" + handle.lstrip("@")

        text_element = WebDriverWait(element, 10).until(
            EC.presence_of_element_located((By.XPATH, './/div[@data-testid="tweetText"]'))
        )
        # Use JavaScript to get inner text to preserve formatting
        text = element.parent.execute_script("return arguments[0].innerText;", text_element).strip()
        return f"{user} ({handle}): {text}"
    except (NoSuchElementException, TimeoutException) as e:
        print(f"Error extracting post details: {str(e)}")
        return None


def scrape_x_post(post_url):
    """Scrape the main post and replies from an X.com post."""
    driver = initialize_driver()
    posts = []

    try:
        driver.get(post_url)
        # Wait for the main tweet to load with a fallback strategy
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))

            )
        except TimeoutException:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//main//article'))

            )

        # Extract the main post
        main_post = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]')
        main_details = extract_post_details(main_post)

        if main_details:
            posts.append(f"MAIN POST: {main_details}")
        else:
            print("Error extracting main post details.")
            return posts  # Early return if main post extraction fails

        # Scroll to load replies
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        # Locate reply sections (limit to first 5)
        reply_sections = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located(

                (By.XPATH, '//div[@data-testid="cellInnerDiv"][.//article[contains(@data-testid, "tweet")]]')
            )
        )[:5]

        for reply in reply_sections:
            reply_details = extract_post_details(reply)
            if reply_details:
                posts.append(f"REPLY: {reply_details}")
            else:
                print("Skipped a reply due to extraction error.")
    except Exception as e:
        print(f"Scraping failed: {str(e)}")
    finally:
        driver.quit()

    return posts


def clean_url(url):
    """Clean and normalize URLs for improved validation."""
    # Remove trailing punctuation
    url = re.sub(r'[.,;:)]$', '', url)

    # Add https:// if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    # Add www. for domains that typically require it
    major_domains = ['reuters.com', 'nytimes.com', 'washingtonpost.com', 'bbc.com']
    for domain in major_domains:
        if domain in url and not re.search(r'https?://www\.', url):
            url = url.replace('://', '://www.')

    # Fix truncated Reuters URLs
    if 'reuters.com/article' in url and not re.search(r'idUS[A-Z0-9]+', url) and not re.search(r'-\d{8}', url):
        # Don't attempt to fix badly truncated URLs
        pass

    # Fix AP News URLs that might be missing the /article/ segment
    if 'apnews.com' in url and '/article/' not in url:
        parts = url.split('apnews.com/')
        if len(parts) > 1 and parts[1] and not parts[1].startswith('article/'):
            url = f"https://www.apnews.com/article/{parts[1]}"

    return url


def validate_url(url, verbose=False):
    """Universal URL validator with special handling for news domains."""
    try:
        url = url.strip()
        url = clean_url(url)

        # Basic URL pattern check
        pattern = re.compile(
            r'^https?://'  # Protocol
            r'(?:www\.)?'  # Optional www
            r'[a-zA-Z0-9-]+'  # Domain name
            r'\.[a-zA-Z]{2,}'  # TLD
            r'(?:/[^\s]*)?$',  # Optional path
            re.IGNORECASE
        )
        if not pattern.match(url):
            if verbose:
                print(f"URL failed pattern validation: {url}")
            return False

        # Extract domain for special handling
        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
        if not domain_match:
            return False
        domain = domain_match.group(1).lower()

        # ---- DOMAIN-SPECIFIC HANDLING ----

        # 1. Known trusted domains that often block scrapers
        TRUSTED_DOMAINS = {
            'reuters.com': True,
            'apnews.com': True,
            'bbc.com': True,
            'bbc.co.uk': True,
            'nytimes.com': True,
            'washingtonpost.com': True,
            'theguardian.com': True,
            'cnn.com': True,
            'npr.org': True,
            'aljazeera.com': True,
            'france24.com': True,
            'dw.com': True,
        }

        # Check if this is a trusted domain
        for trusted_domain, accept in TRUSTED_DOMAINS.items():
            if trusted_domain in domain and accept:
                if verbose:
                    print(f"Trusted domain: {domain}")
                return True

        # 2. Check for government and educational domains
        if domain.endswith('.gov') or domain.endswith('.edu'):
            if verbose:
                print(f"Government or educational domain: {domain}")
            return True

        # 3. For other domains, test with a request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml',
        }

        try:
            response = requests.get(url, timeout=10, headers=headers, allow_redirects=True)

            # Success case - 2xx status code
            if 200 <= response.status_code < 300:
                return True

            # Common error codes - check URL structure
            elif response.status_code in [403, 429]:
                # Only accept well-structured URLs when blocked
                if '/article/' in url or '/news/' in url:
                    if verbose:
                        print(f"Blocked but well-structured URL: {url}")
                    return True
                return False

            # Clear failure cases
            elif response.status_code == 404:
                return False

            # For other errors, reject
            else:
                return False

        except requests.exceptions.RequestException:
            # Connection problems - only accept URLs from major domains
            for major_domain in ['reuters.com', 'apnews.com', 'bbc.com', 'cnn.com']:
                if major_domain in domain:
                    if verbose:
                        print(f"Connection issue but major domain: {url}")
                    return True
            return False

    except Exception as e:
        if verbose:
            print(f"URL validation error: {str(e)}")
        return False


def analyze_text(prompt):
    """Send the prompt to the AI API and return the response."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek/deepseek-r1:free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.4,
        "stop": ["\n##"]
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()

        data = response.json()
        if 'choices' not in data:
            return None

        content = data['choices'][0]['message']['content']
        return content

    except Exception as e:
        print(f"API Error: {str(e)}")
        return None


def detect_bias(text):
    """Detect political bias in text."""
    prompt = f"""
Analyze this text for political bias. Follow EXACTLY this format:

**Verdict**: [Left/Right/Neutral/Mixed]

**Key Indicators**:
- List item 1
- List item 2
- List item 3

**Context Analysis**: [2-3 sentence explanation]

Text: "{text}"

Important Rules:
1. NEVER include sources or URLs
2. Focus only on language and framing
3. Maximum 150 words
"""
    return analyze_text(prompt)


def extract_topics(claim):
    """Extract key topics from a claim for customizing the fact-check prompt."""
    # Define common topic categories
    topics = {
        "politics": ["president", "government", "election", "vote", "congress", "senate", "politician", "democrat",
                     "republican"],
        "international": ["ukraine", "russia", "putin", "zelensky", "china", "chinese", "israel", "gaza", "palestine",
                          "nato"],
        "health": ["covid", "vaccine", "health", "medical", "virus", "pandemic", "disease", "doctor", "hospital"],
        "climate": ["climate", "carbon", "global warming", "emissions", "environment", "pollution", "renewable"],
        "economy": ["inflation", "economy", "recession", "interest rate", "federal reserve", "stock market",
                    "unemployment"],
        "social": ["immigration", "lgbtq", "transgender", "abortion", "race", "racism", "protest", "rights"]
    }

    # Check for topics in the claim
    found_topics = []
    claim_lower = claim.lower()

    for topic, keywords in topics.items():
        for keyword in keywords:
            if keyword.lower() in claim_lower:
                found_topics.append(topic)
                break

    # Return unique topics
    return list(set(found_topics))


def fact_check_claim(claim):
    """Dynamic fact-checking that adapts to the claim's topic."""
    # Extract topics to customize the prompt
    topics = extract_topics(claim)

    # Base prompt structure
    base_prompt = f"""
Fact-check: "{claim}"

FOLLOW THIS EXACT FORMAT:

[1] Verification: True/False/Misleading/Unproven

[2] Evidence-Source Pairs:
- 1. FIRST EVIDENCE POINT (WORKING_URL)
- 2. SECOND EVIDENCE POINT (WORKING_URL)
- 3. THIRD EVIDENCE POINT (WORKING_URL)

[3] Confidence: High/Medium/Low

[4] Verified Sources:
- WORKING_URL1
- WORKING_URL2
- WORKING_URL3

**Explanation**:
Brief summary of your analysis.

SOURCE REQUIREMENTS:
1. ONLY use established news organizations like:
   - Reuters (www.reuters.com)
   - Associated Press (apnews.com)
   - BBC News (www.bbc.com/news)
   - NPR (www.npr.org)
   - The Guardian (www.theguardian.com)
   - Al Jazeera (www.aljazeera.com)

2. Each URL MUST:
   - Be from the last 5 years
   - Link to a specific article (not a homepage)
   - Include the full domain and path
   - Use properly formatted article IDs
   - Be a real, functional URL (not made up)

3. Source formatting rules:
   - Reuters: Use https://www.reuters.com/article/ format with complete article ID
   - AP News: Use https://apnews.com/article/ format with complete article ID
   - BBC: Use https://www.bbc.com/news/ format with proper ID
"""

    # Add topic-specific guidance
    topic_guidance = ""

    if "politics" in topics:
        topic_guidance += """
POLITICAL CLAIM GUIDANCE:
- Check party affiliations and political context
- Verify voting records when relevant
- Use non-partisan sources when possible
- Check for out-of-context quotes
"""

    if "international" in topics:
        topic_guidance += """
INTERNATIONAL CLAIM GUIDANCE:
- Verify the chronology of events and leadership terms
- Check territorial claims against recognized boundaries
- Consider geopolitical contexts and potential biases
- Use sources from multiple countries when possible
"""

    if "health" in topics:
        topic_guidance += """
HEALTH CLAIM GUIDANCE:
- Use medical journals and health organizations as sources
- Verify credentials of cited experts
- Check if claims are based on peer-reviewed research
- Consider scientific consensus vs. outlier opinions
"""

    if "climate" in topics:
        topic_guidance += """
CLIMATE CLAIM GUIDANCE:
- Use scientific sources and climate research organizations
- Distinguish between weather events and climate trends
- Check claims against IPCC and other scientific consensus
- Verify environmental statistics and their proper context
"""

    if "economy" in topics:
        topic_guidance += """
ECONOMIC CLAIM GUIDANCE:
- Use official economic data sources
- Verify the timeframe for economic statistics
- Check for cherry-picked economic indicators
- Consider multiple economic metrics for context
"""

    if "social" in topics:
        topic_guidance += """
SOCIAL ISSUE GUIDANCE:
- Check definitions of controversial terms
- Verify statistics about demographic groups
- Consider legal contexts and relevant court rulings
- Distinguish between policy positions and implemented actions
"""

    # Add sample URLs based on topics for better AI guidance
    sample_urls = """
SAMPLE URL FORMATS THAT WORK:
- https://www.reuters.com/article/us-usa-politics-idUSKCN1VN2JZ
- https://apnews.com/article/2abed2d3e4bd48e8ad5ed6bea064ad72
- https://www.bbc.com/news/world-europe-59599066
- https://www.theguardian.com/world/2023/jan/25/article-name
"""

    # Combine all parts into the final prompt
    complete_prompt = base_prompt + topic_guidance + sample_urls

    # Call the API with the complete prompt
    return analyze_text(complete_prompt)


def validate_sources(content):
    """Extract and validate evidence-source pairs from fact-check content."""
    if "[4] Verified Sources:" not in content:
        return content

    lines = content.split('\n')

    # Extract verification result
    verification_match = re.search(r'\[1\]\s*Verification:\s*(.*)', content)
    verification_text = verification_match.group(1).strip() if verification_match else "Unproven"

    # Extract evidence-source pairs
    evidence_source_pairs = []
    evidence_pattern = re.compile(r'-\s*\d*\.?\s*(.*?)\s*\((https?://[^\s)]+)\)')

    in_evidence_section = False
    for line in lines:
        line = line.strip()
        if "[2]" in line and "Evidence" in line:
            in_evidence_section = True
            continue
        if in_evidence_section and "[3]" in line:
            in_evidence_section = False
            continue
        if in_evidence_section and line.startswith("-"):
            match = evidence_pattern.search(line)
            if match:
                evidence, url = match.groups()
                evidence_source_pairs.append((evidence.strip(), url.strip()))

    # Extract source URLs
    source_urls = []
    in_sources_section = False
    for line in lines:
        line = line.strip()
        if "[4]" in line and "Verified Sources" in line:
            in_sources_section = True
            continue
        if in_sources_section and (not line or line.startswith("[")):
            in_sources_section = False
            continue
        if in_sources_section and line.startswith("-"):
            url_match = re.search(r'-\s*(https?://[^\s]+)', line)
            if url_match:
                source_urls.append(url_match.group(1).strip())

    # Validate URLs
    all_urls = set([url for _, url in evidence_source_pairs] + source_urls)
    valid_urls = {}

    print(f"Validating {len(all_urls)} URLs...")
    for url in all_urls:
        valid_urls[url] = validate_url(url)

    # Filter for valid evidence-source pairs
    valid_pairs = [(evidence, url) for evidence, url in evidence_source_pairs if url in valid_urls and valid_urls[url]]

    # Build updated response
    if valid_pairs:
        confidence = 'High' if len(valid_pairs) >= 3 else 'Medium' if len(valid_pairs) >= 1 else 'Low'
        result = (
            f"[1] Verification: {verification_text}\n\n"
            f"[2] Evidence-Source Pairs:\n"
        )

        for i, (evidence, url) in enumerate(valid_pairs, 1):
            result += f"- {i}. {evidence} ({url})\n"

        result += f"\n[3] Confidence: {confidence}\n\n"
        result += "[4] Verified Sources:\n"

        for _, url in valid_pairs:
            result += f"- {url}\n"

        # Add explanation if provided
        explanation_match = re.search(r'\*\*Explanation\*\*:(.+?)(?=\n\n|\Z)', content, re.DOTALL)
        if explanation_match:
            explanation = explanation_match.group(1).strip()
            result += f"\n\n**Explanation**:\n{explanation}"

        return result
    else:
        return (
            "[1] Verification: Unproven\n\n"
            "[2] Evidence-Source Pairs:\n"
            "- No verifiable evidence found\n\n"
            "[3] Confidence: Low\n\n"
            "[4] Verified Sources:\n"
            "- No valid sources available"
        )


def test_urls_before_display(fact_check_result):
    """Test URLs and provide a clean validation report."""
    if not fact_check_result:
        return "Fact-checking failed."

    # Extract all URLs
    url_pattern = re.compile(r'(https?://[^\s)]+)')
    urls = url_pattern.findall(fact_check_result)

    # Test each URL
    url_status = {}
    valid_count = 0
    invalid_count = 0

    print("Validating URLs...")
    for url in urls:
        url = url.strip()
        if url not in url_status:  # Avoid duplicates
            is_valid = validate_url(url)
            url_status[url] = is_valid
            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1

    # Create a compact validation report
    url_report = f"\nURL Validation: {valid_count} valid, {invalid_count} invalid"

    # List invalid URLs if any
    if invalid_count > 0:
        url_report += "\nInvalid URLs:"
        for url, is_valid in url_status.items():
            if not is_valid:
                url_report += f"\n- {url}"
                # Mark invalid URLs in the result
                fact_check_result = fact_check_result.replace(
                    url,
                    f"{url} [INVALID]"
                )

    return f"{fact_check_result}\n{url_report}"


def main():
    """Main function with streamlined output."""
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
    bias_result = detect_bias(posts[0])
    if bias_result:
        print(bias_result)
    else:
        print("Bias analysis failed.")

    print("\nFact-Checking:")
    # Extract just the text content from the main post
    post_content = posts[0]
    if "MAIN POST: " in post_content:
        post_content = post_content.split("MAIN POST: ")[1]

    # Get fact check result
    fact_check_result = fact_check_claim(post_content)

    if fact_check_result:
        # Process with streamlined validation
        validated_content = validate_sources(fact_check_result)
        # Display with clean formatting
        final_result = test_urls_before_display(validated_content)
        print(final_result)
    else:
        print("Fact-checking failed.")


if __name__ == "__main__":
    main()
