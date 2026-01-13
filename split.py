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

# Process URLs and classify them
def domain_split(client, sheet_id, urls, source_name):
    keywords_sheet = client.open_by_key(st.secrets["keywords_id"]).worksheet("Keywords")  
    good_keywords = [kw.lower() for kw in keywords_sheet.col_values(1)[1:]]  # Lowercase good keywords
    bad_keywords = [kw.lower() for kw in keywords_sheet.col_values(3)[1:]]  # Lowercase bad keywords
    headers = ["URL", "Matching Count", "Matching Words", "J Count", "Words", "Source", "Timestamp"]
    results_sheet = client.open_by_key(sheet_id).worksheet("Results")
    if len(results_sheet.get_all_values()) < 1:  # Only the header exists
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
