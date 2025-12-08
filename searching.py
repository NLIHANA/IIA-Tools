from googletrans import Translator
import asyncio
import requests
from bs4 import BeautifulSoup
import pycld2 as cld2
import re
from collections import Counter
from datetime import datetime
import pytz
import streamlit as st
from urllib.parse import urlparse, urlunparse
import random
import requests_cache
import spacy
from googlesearch import search
from googleapiclient.discovery import build
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time
import tempfile
import string
import unicodedata

# Install cache for HTTP requests
requests_cache.install_cache('http_cache', expire_after=300)

#headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36"}
headers = {"User-Agent": "AdsBot-Google (+http://www.google.com/adsbot.html)"}

# Error handler function to streamline error handling
def error_handler(function, item, error_message):
    st.error(f"Error processing {function} for '{item}': {error_message}")
    return "Error", "Error"

def extract_domain_from_url(url):
    try:
        domain = urlparse(url).netloc
        domain = domain.replace('www.', '')
    
        # Regular expression to remove common domain suffixes
        domain = re.sub(r'\.(com|org|net|gov|edu|co|co\.[a-z]{2,2}|[a-z]{2,})$', '', domain)
        return domain
    except Exception as e:
        error_handler("extract domain", url, e)
        return url

def guess_words(concatenated_sentence):
    """
    Splits a concatenated sentence into all possible valid words using all available spaCy language models.
    Only returns words with more than 3 letters and removes duplicates.
    
    :param concatenated_sentence: A string with no spaces (e.g., 'colegiohebreounion').
    :return: A list of unique valid words.
    """
    def is_valid_word(nlp, word):
        """Checks if a word is valid using spaCy's lexeme and word probabilities."""
        try:
            lexeme = nlp.vocab[word]
            return lexeme.is_alpha and len(word) > 3 and (not lexeme.is_oov or lexeme.prob > -20)
        except Exception as e:
            error_handler("is valid word", word, e)
            return False

    def find_all_splits(sentence):
        """Recursively finds all valid word splits for a given sentence."""
        if not sentence:
            return [[]]  # Return a list with an empty list when sentence is empty

        all_splits = []
        for i in range(1, len(sentence) + 1):
            word_candidate = sentence[:i]
            # Only consider splits where the word is longer than 3 letters
            if len(word_candidate) > 3:
                remaining_sentence = sentence[i:]
                remaining_splits = find_all_splits(remaining_sentence)
                for split in remaining_splits:
                    all_splits.append([word_candidate] + split)
        return all_splits

    try:
        # Load all the language models
        models = {
            "English": spacy.load("en_core_web_md"),
            "Spanish": spacy.load("es_core_news_md"),
            "French": spacy.load("fr_core_news_md"),
            "Portuguese": spacy.load("pt_core_news_md"),
            "Italian": spacy.load("it_core_news_md")
        }
        
        # First, split the concatenated sentence once
        splits = find_all_splits(concatenated_sentence)
    
        # Flatten the list of splits into a list of word candidates
        word_candidates = [word for split in splits for word in split]
    
        # Set to collect all valid words
        all_valid_words = set()
    
        # Check each word_candidate in all languages
        for word_candidate in word_candidates:
            for language, nlp in models.items():
                if is_valid_word(nlp, word_candidate):
                    all_valid_words.add(word_candidate)
                    break  # If valid in any language, add and stop checking further languages
        
        # Translate each word to English and check validity
        for word in list(all_valid_words):
            translated_word = translate_to_english(word).lower()
            if is_valid_word(models["English"], translated_word):
                all_valid_words.add(translated_word)
    
        # Convert set to a list and return it
        return list(all_valid_words)
    except Exception as e:
        error_handler("guess words", url, e)
        return "Error"

# Function to calculate score based on keyword matching
def calculate_url_score(words, keywords):
    matching_words = set(words).intersection(keywords)
    return len(matching_words), matching_words

def count_j_in_domain(url):
    domain = extract_domain_from_url(url)
    return domain.count('j')


def duckduckgo_search(query, num_results=100, language="en"):
    """
    Scrape DuckDuckGo (HTML endpoint) for result links.

    Args:
        query (str): Search query.
        num_results (int): Maximum number of result URLs to return.
        language (str): BCP-47 language tag (e.g., "en", "de").
                        DuckDuckGo's region/language param is 'kl' (e.g., "us-en", "de-de").
                        This function maps "en" -> "us-en" by default and "xx" -> "xx-xx".
        headers (dict): Optional requests headers. If None, a reasonable default is used.

    Returns:
        list[str]: List of result URLs.
    """
    DDG_HEADERS = {'origin': 'https://lite.duckduckgo.com', 'referer': 'https://lite.duckduckgo.com/'}
    results = []
    start = 0                 # DuckDuckGo uses 's' as an offset (0-based)
    page_size_guess = 50      # DDG HTML typically returns up to ~50 per page; safe to step by 50
    BASE_URL = 'https://lite.duckduckgo.com/lite/'
    
    # Map simple language code to DDG's 'kl' region-language format
    # If you have a more precise mapping, replace this heuristic.
    lang = (language or "en").lower()
    if lang == "en":
        kl = "us-en"
    else:
        kl = f"{lang}-{lang}"


    while len(results) < num_results:
        params = {
            "q": query,
            "kl": kl,
            "s": str(start)   # offset for pagination
        }

        try:
            response = requests.get(BASE_URL, params=params, headers=DDG_HEADERS, timeout=30)
            response.raise_for_status()

            st.write(f"### DuckDuckGo HTML (offset {start})")
            st.code(response.text[:2000], language="html")  # preview first ~2k chars for debugging

            soup = BeautifulSoup(response.text, "html.parser")

            # Each result is typically in a div.result with an anchor 'a.result__a'
            for a in soup.select("div.result a.result__a"):
                href = a.get("href")
                if href:
                    results.append(href)
                    if len(results) >= num_results:
                        break

            # If we didn't find any new results on this page, stop.
            # (Covers end-of-results or layout changes)
            if start == 0 and not results:
                # No results at all on first page
                break
            # If this page yielded nothing beyond what we already had, stop.
            # (Heuristic: count how many we had before this fetch)
            # More explicit check:
            found_links_this_page = len(soup.select("div.result a.result__a"))
            if found_links_this_page == 0:
                break

            # Move to the next page
            start += page_size_guess

            # Be polite: random delay between requests
            time.sleep(random.uniform(2, 6))

        except Exception as e:
            # Keep your existing error handler interface
            error_handler("duckduckgo search", query, e)
            break

    # Truncate to exactly num_results in case we over-collected
    results = results[:num_results]

    if results:
        st.info(f"Fetched {len(results)} DuckDuckGo results for '{query}'")
        return results
    else:
        st.error(f"No DuckDuckGo results found for the query '{query}'")
        return []



def google_search_homemade(query, num_results=100, language="en"):
    results = []
    start = 0  # Google uses `start` parameter for pagination

    while len(results) < num_results:
        search_url = f"https://www.google.com/search?q={query}&hl={language}&lr=lang_{language}&num=10&start={start}"
        try:
            # Make the HTTP request
            response = requests.get(search_url, headers=headers)
            response.raise_for_status()
            
            st.write("### Raw HTML Response")
            st.code(response.text[:2000], language="html")  # Limit to the first 2000 characters for readability

            # Parse the response with BeautifulSoup
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Extract links from search results
            result_divs = soup.find_all("div", class_="tF2Cxc")
            for div in result_divs:
                link_tag = div.find("a")
                if link_tag and link_tag["href"]:
                    results.append(link_tag["href"])
                    if len(results) >= num_results:  # Stop if we've reached the desired number
                        break

            # Update `start` for the next page
            start += 10  # Google paginates by increments of 10

            # Stop if no results are found on the current page
            if not result_divs:
                break

            # Pause before the next request
            delay = random.uniform(2, 10) 
            time.sleep(delay)

        except Exception as e:
            error_handler("google search", query, e)
            break  # Stop the loop if there's an error

    if results:
        st.info(f"Fetched {len(results)} results for '{query}'")
    else:
        st.error(f"No results found for the query '{query}'")
    return results

def google_search_selenium(query, num_results=10, language="en"):
    try:
        temp_dir = tempfile.mkdtemp()

        # Setup headless browser options
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"--user-data-dir={temp_dir}")
        
        driver = webdriver.Chrome(options=chrome_options)
        
        search_url = f"https://www.google.com/search?q={query}&hl={language}&num=10"
        driver.get(search_url)
    
        time.sleep(2)  # Allow time for JavaScript to load
    
        # Get page source after JavaScript has rendered the results
        html = driver.page_source
    
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        result_divs = soup.find_all("div", class_="tF2Cxc")
        
        for div in result_divs:
            link_tag = div.find("a")
            if link_tag and link_tag["href"]:
                results.append(link_tag["href"])
                if len(results) >= num_results:
                    break
    
        driver.quit()  # Quit the browser session
        
        return results
    except Exception as e:
        error_handler("google search", query, e)



def google_search(query, num_results=100, language="en"):
    """
    Fetch up to `num_results` results (Google CSE exposes at most 100 organic results).
    Handles paging with start indices in [1..91] and fixes language parameters.
    """
    api_key = st.secrets["cse_key"]
    cse_id = st.secrets["cse_id"]

    # Normalize language codes:
    # - hl: can be "en" or "es-ES" etc., but we’ll keep it simple and pass what we can.
    # - lr: MUST be in the form "lang_xx" (two-letter code only). If not available, omit.
    lang_for_hl = (language or "en")
    lang_for_lr = (language.split("-")[0].lower() if language else "en")
    lr_param = f"lang_{lang_for_lr}" if len(lang_for_lr) == 2 else None

    try:
        service = build("customsearch", "v1", developerKey=api_key)

        # Google CSE returns at most 10 results per page and at most ~100 total.
        target = min(int(num_results), 100)

        all_results = []
        start_index = 1  # valid range is 1..91 (with num=10)

        while len(all_results) < target and start_index <= 91:
            # Ask only for what we still need (<=10)
            page_num = min(10, target - len(all_results))

            req = {
                "q": query,
                "cx": cse_id,
                "num": page_num,
                "start": start_index,
                "hl": lang_for_hl,
            }
            if lr_param:
                req["lr"] = lr_param

            results = service.cse().list(**req).execute()

            items = results.get("items", [])
            if not items:
                break  # no more items available

            for item in items:
                link = item.get("link")
                if link:
                    all_results.append(link)
                    if len(all_results) >= target:
                        break

            # Advance to the next page. With num<=10, the next valid start is +10.
            start_index += 10

            # Optional: stop early if we’ve reached the end of available results.
            total_avail_str = results.get("searchInformation", {}).get("totalResults", "0")
            try:
                total_avail = int(total_avail_str)
                if start_index > total_avail:
                    break
            except ValueError:
                pass  # if Google doesn’t return a parseable number, just keep paging

        st.info(f"Fetched {len(all_results)} results for '{query}'")
        return all_results

    except Exception as e:
        st.error(f"An error occurred during the search: {e}")
        return []

def translate_text(input, lang_code):
    if not input.strip():
        return ""
    if not isinstance(input, str):
        input = str(input)
    translator = Translator()
    try:
        translation = translator.translate(input, src='auto', dest=lang_code)
        return translation.text
    except Exception as e:
        error_handler("translating", input, e)
        return f"{input} (error)"

# Function to fetch title from a URL
def get_title(url):
    title = ""
    try:
        # Add scheme if missing
        if not re.match(r'^https?://', url):
            url = 'https://' + url
        response = requests.get(url, timeout=30, headers=headers)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        # Try to get the title
        title = soup.title.string if soup.title else ""
        title = re.sub(r'[\r\n]+', ' ', title.strip()) if title else ""
        if title is not str:
            title = str(title)
        return title
    except requests.exceptions.RequestException as e:
        error_handler("get title", url, e)
        return "Error"


# Function to fetch description from a URL
def get_description(url):
    description = ""
    try:
        # Add scheme if missing
        if not re.match(r'^https?://', url):
            url = 'https://' + url
        response = requests.get(url, timeout=30, headers=headers)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        # Try to get the description
        description_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
        description = description_tag['content'] if description_tag else ""
        description = re.sub(r'[\r\n]+', ' ', description.strip()) if description else ""
        if description is not str:
            description = str(description)
        return description
    except requests.exceptions.RequestException as e:
        error_handler("get description", url, e)
        return "Error"

# Helper function to combine title and description text
def combine_text(title, description):
    try:
        # Handle missing title or description by replacing with empty string
        title = (title or "").strip().lower()  # Use empty string if title is None or empty
        description = (description or "").strip().lower()  # Use empty string if description is None or empty
        
        # Combine the title and description, ensuring no None values are included
        combined_text = f"{title} {description}".strip()
        return combined_text
    except Exception as e:
        error_handler("combine text", title, e)
        return title



# Function to detect language using CLD2
def detect_language(title, description):
    combined_text = combine_text(title, description)
    try:
        # Check for Hebrew letters in the text
        if re.search(r'[\u0590-\u05FF]', combined_text):
            languages = ["hebrew"]
        else:
            languages = []
        # Use CLD2 for further language detection
        is_reliable, _, lang_details = cld2.detect(combined_text)
        if is_reliable:
            detected_languages = [detail[0].lower() for detail in lang_details if detail[0] != "Unknown"]
            languages.extend(detected_languages)
            languages = list(set(languages))  # Remove duplicates
        return languages if languages else ["unknown"]
    except Exception as e:
        error_handler("detecting language", title, e)
        return ["unknown"]

def translate_to_english(input):
    if not input.strip():
        return ""
    if not isinstance(input, str):
        input = str(input)
    translator = Translator()
    try:
        translation = translator.translate(input, src='auto', dest='en')
        return translation.text
    except Exception as e:
        error_handler("translating", input, e)
        return input


def count_keywords(title, description, good_keywords, bad_keywords):
    """Count occurrences of good and bad keywords in the title and description."""
    try:
        combined_text = combine_text(title, description)
        # Normalize dashes and hyphens to spaces
        for dash in ["-", "–", "—", "−"]:
            combined_text = combined_text.replace(dash, " ")
        # Unicode normalization to strip accents/special chars
        combined_text = unicodedata.normalize("NFKD", combined_text).encode("ascii", "ignore").decode()
        # Convert to lowercase for case-insensitive matching
        combined_text = combined_text.lower()
        # Remove punctuation
        combined_text = combined_text.translate(str.maketrans("", "", string.punctuation))
        # Normalize whitespace
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()
        # Prepare keyword lists (also lowercased)
        good_keywords = [word.lower() for word in good_keywords]
        bad_keywords = [word.lower() for word in bad_keywords]
        # Count keywords
        word_counts = Counter(combined_text.split())
        good_count = sum(word_counts[word] for word in good_keywords if word in word_counts)
        bad_count = sum(word_counts[word] for word in bad_keywords if word in word_counts)
        return good_count, bad_count
    except Exception as e:
        error_handler("counting keywords", title, e)
        return 0, 0

    
# Function to calculate score
def calculate_score(url, title, description, languages, good_keywords, bad_keywords):
    try:
        # Count keywords in the original text
        original_good_count, original_bad_count = count_keywords(title, description, good_keywords, bad_keywords)

        # Translate if any language is not English
        if languages and any(lang.lower() != 'english' for lang in languages):
            trans_title = translate_to_english(title)
            trans_description = translate_to_english(description)
            # Count keywords in the translated text
            translated_good_count, translated_bad_count = count_keywords(trans_title, trans_description, good_keywords, bad_keywords)
        else:
            translated_good_count = 0
            translated_bad_count = 0

        # Total keyword counts
        total_good_count = original_good_count + translated_good_count
        total_bad_count = original_bad_count + translated_bad_count

        if total_bad_count > 1:
            return "C", "Bad keywords", total_good_count, total_bad_count

        if url.endswith(".il") or url.endswith(".il/") or "hebrew" in languages:
            return "A", "Hebrew / .il", total_good_count, total_bad_count

        if total_good_count > 0:
            return "B", "Good keywords", total_good_count, total_bad_count

        return "C", "No good keywords", total_good_count, total_bad_count

    except Exception as e:
        st.error(f"Error processing calculate score for {url}: {e}")
        return "C", "Error", 0, 0



# Function to filter out ignored URLs
def filter_ignored_urls(block_list, classified_urls):
    ignored_set = set(block_list)  # Convert to set for faster lookups
    filtered_urls = [(url, source) for url, source in classified_urls if url not in ignored_set]
    return filtered_urls
    

# Function to search and filter URLs based on query
def search_and_filter_urls(query, block_list, num_results=100, language="en", homepage_only=False, engine="API"):
    search_results = []
    try:
        if engine == "api":
            search_results = google_search(query, num_results, language) or []
        elif engine == "homemade":
            search_results = google_search_homemade(query, num_results, language) or []
        elif engine == "library":
            search_results = google_search_library(query, num_results, language) or []
        elif engine == "selenium":
            search_results = google_search_selenium(query, num_results, language) or []
        elif engine == "duckduckgo":
            search_results = duckduckgo_search(query, num_results, language) or []
        else:
            st.error(f"Unknown engine '{engine}'. Falling back to API.")
            search_results = google_search(query, num_results, language) or []  
    except Exception as e:
        st.error(f"Search engine '{engine}' failed: {e}")
        search_results = []
    st.write(f"Engine resolved to: '{engine}'")   
    classified_urls = []
    
    for result in search_results:
        parsed_url = urlparse(result)
        if homepage_only:
            if parsed_url.path not in ("", "/") or parsed_url.query or parsed_url.fragment:
                continue
            source = f"search for '{query}' (d)"
        else:
            # Strip URL to domain or subdomain
            stripped_url = urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))
            source = f"search for '{query}' (d)" if parsed_url.path in ("", "/") and not parsed_url.query and not parsed_url.fragment else f"search for '{query}' (p)"
            result = stripped_url  # Replace result with stripped URL
        classified_urls.append((result, source))

    # Deduplicate, excluding www if root domain is present
    seen_domains = set()
    deduplicated_urls = []

    for url, source in classified_urls:
        parsed_url = urlparse(url)
        netloc = parsed_url.netloc

        # Check if it's a www domain
        if netloc.startswith("www."):
            root_domain = netloc[4:]  # Strip 'www.'
        else:
            root_domain = netloc

        # Skip www.x.com if x.com is already seen
        if netloc.startswith("www.") and root_domain in seen_domains:
            continue

        # Add both the full domain and root domain to the seen set
        seen_domains.add(root_domain)
        deduplicated_urls.append((url, source))

    # Filter out ignored URLs if provided
    deduplicated_urls = filter_ignored_urls(block_list, deduplicated_urls)
    
    return deduplicated_urls



# Function to update Google Sheets after processing each keyword
def update_google_sheets(rows_to_sure, rows_to_not_sure, sure_sheet, not_sure_sheet):
    if rows_to_sure:
        sure_sheet.append_rows(rows_to_sure, value_input_option='RAW')
    if rows_to_not_sure:
        not_sure_sheet.append_rows(rows_to_not_sure, value_input_option='RAW')


# Function to add headers to sheets
def check_and_add_headers(sheet):
    headers = ["URL", "Title", "Description", "Tier", "Details", "Source","Languages", "Good Keywords", "Bad Keywords" , "Timestamp"]
    # Check if the sheet has any data (excluding the header row)
    if len(sheet.get_all_values()) <= 1:  # Only the header exists
        sheet.insert_row(headers, 1)

# Fetch sheets and extract keywords
def fetch_and_get_keywords(client, sheet_id):
    """Fetch necessary Google Sheets and extract good and bad keywords."""
    try:
        keywords_sheet = client.open_by_key(st.secrets["keywords_id"]).worksheet("Keywords")
        block_sheet = client.open_by_key(st.secrets["keywords_id"]).worksheet("Block")
        sure_sheet = client.open_by_key(sheet_id).worksheet("Sure")
        not_sure_sheet = client.open_by_key(sheet_id).worksheet("Not Sure")      
        good_keywords = [kw.lower() for kw in keywords_sheet.col_values(1)[1:]]  # Lowercase good keywords
        bad_keywords = [kw.lower() for kw in keywords_sheet.col_values(3)[1:]]  # Lowercase bad keywords
        block_list = block_sheet.col_values(1)[1:]
        return keywords_sheet, sure_sheet, not_sure_sheet, good_keywords, bad_keywords, block_list
    except Exception as e:
        error_handler("fetch and get keywords", sheet_id, e)

# Process a single URL and evaluate it
def process_single_url(url, source, good_keywords, bad_keywords):
    """Process a single URL and return a row of data and its score."""
    timestamp = datetime.now(pytz.timezone('Asia/Jerusalem')).strftime("%Y-%m-%d %H:%M:%S")
    try:
        title = get_title(url)
        description = get_description(url)
        languages = detect_language(title, description)
        lang_text = ", ".join(languages) if languages else "unknown"
        score, details, good_count, bad_count = calculate_score(url, title, description, languages, good_keywords, bad_keywords)
        title_en = translate_text(title, "en")
        description_en = translate_text(description, "en")
        row_data = [url, title, description, title_en, description_en, score, details, source, lang_text, good_count, bad_count, timestamp]
    except Exception as e:
        st.error(f"Error processing URL '{url}': {e}")
        score = "C"
        row_data = [url, title if title else "Error", "Error", "Error", "Error", score, "Error", source if source else "Error", "Error", "Error", "Error", timestamp if timestamp else "Error"]    
    return row_data, score


# Process keywords to fetch and evaluate URLs
def process_keywords(client, sheet_id, keywords, lang="en", inurl=False, limit=100, homepage=False, engine="API"):
    """Process a list of keywords to fetch and evaluate URLs."""
    keywords_sheet, sure_sheet, not_sure_sheet, good_keywords, bad_keywords, block_list = fetch_and_get_keywords(client, sheet_id)

    check_and_add_headers(sure_sheet)
    check_and_add_headers(not_sure_sheet)
    for keyword in keywords:
        st.info(f"Processing '{keyword}'...")
        rows_to_sure, rows_to_not_sure = [], []
        delay = random.uniform(10, 60)
        time.sleep(delay)
        
        try:
            homepage_urls = search_and_filter_urls(keyword, block_list, num_results=limit, language=lang, homepage_only=homepage, engine=engine)
            inurl_urls = []
            if inurl:
                inurl_urls = search_and_filter_urls(f"inurl:{keyword}", block_list, num_results=limit, language=lang, homepage_only=homepage, engine=engine)

            all_urls = list({url: source for url, source in homepage_urls + inurl_urls}.items())
            for url, source in all_urls:
                row_data, score = process_single_url(url, source, good_keywords, bad_keywords)
                if score in ["A", "B"]:
                    rows_to_sure.append(row_data)
                else:
                    rows_to_not_sure.append(row_data)
                                    
                # Update Google Sheets when there are 20 rows in either list
                if len(rows_to_not_sure) >= 10 or len(rows_to_sure) >= 10:
                    update_google_sheets(rows_to_sure, rows_to_not_sure, sure_sheet, not_sure_sheet)
                    st.info("Updated google sheets")
                    rows_to_sure, rows_to_not_sure = [], []  # Clear the list after updating

            # Final update for any remaining rows
            if rows_to_sure or rows_to_not_sure:
                update_google_sheets(rows_to_sure, rows_to_not_sure, sure_sheet, not_sure_sheet)
            st.success(f"Finished processing '{keyword}'")
        except Exception as e:
            st.error(f"Error processing '{keyword}': {e}")

# Process URLs and classify them
def process_urls(client, sheet_id, urls, source_name):
    """Process a list of URLs and classify them."""
    try:
        with st.status("Working..."):
            keywords_sheet, sure_sheet, not_sure_sheet, good_keywords, bad_keywords, block_list = fetch_and_get_keywords(client, sheet_id)
            check_and_add_headers(sure_sheet)
            check_and_add_headers(not_sure_sheet)
            rows_to_sure, rows_to_not_sure = [], []
        
            for url in urls:
                st.write(f"Working on '{url}'")
                row_data, score = process_single_url(url, source_name, good_keywords, bad_keywords)
                if score in ["A", "B"]:
                    rows_to_sure.append(row_data)
                else:
                    rows_to_not_sure.append(row_data)
                    
                # Update Google Sheets when there are 20 rows in either list
                if len(rows_to_not_sure) >= 20 or len(rows_to_sure) >= 20:
                    update_google_sheets(rows_to_sure, rows_to_not_sure, sure_sheet, not_sure_sheet)
                    st.write("Updated google sheets")
                    rows_to_sure, rows_to_not_sure = [], []  # Clear the list after updating

            # Final update for any remaining rows
            if rows_to_sure or rows_to_not_sure:
                update_google_sheets(rows_to_sure, rows_to_not_sure, sure_sheet, not_sure_sheet)
        st.success(f"Finished processing '{source_name}'")
    except Exception as e:
        st.error(f"Error processing '{source_name}': {e}")

# Process URLs and classify them
def domain_split(client, sheet_id, urls, source_name):
    keywords_sheet = client.open_by_key(st.secrets["keywords_id"]).worksheet("Keywords")  
    good_keywords = [kw.lower() for kw in keywords_sheet.col_values(1)[1:]]  # Lowercase good keywords
    bad_keywords = [kw.lower() for kw in keywords_sheet.col_values(3)[1:]]  # Lowercase bad keywords
    headers = ["URL", "Matching Count", "Matching Words", "J Count", "Words", "Source", "Timestamp"]
    results_sheet = client.open_by_key(sheet_id).worksheet("Results")
    if len(results_sheet.get_all_values()) <= 1:  # Only the header exists
        results_sheet.insert_row(headers, 1)
    try:
        with st.status("Working..."):
            rows = []
            for url in urls:
                st.write(f"Working on '{url}'")
                timestamp = datetime.now(pytz.timezone('Asia/Jerusalem')).strftime("%Y-%m-%d %H:%M:%S")
                words = guess_words(extract_domain_from_url(url))
                matching_count, matching_keywords = calculate_url_score(words, good_keywords)
                j_count = count_j_in_domain(url)
                row_data = [url, matching_count, ", ".join(matching_keywords), j_count, ", ".join(words), source_name, timestamp]
                rows.append(row_data)    
            results_sheet.append_rows(rows, value_input_option='RAW')
        st.success(f"Finished processing '{source_name}'")
    except Exception as e:
        st.error(f"Error processing '{source_name}': {e}")
