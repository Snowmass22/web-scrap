"""
transform_and_scrape.py
-----------------------
Post-processing script to derive columns and scrape clinic addresses.

Tasks:
1. Parse `first_name` and `last_name` from `full_name`.
2. Generate `specialization_alias` using canonical mapping.
3. Scrape `address_of_clinic` from `practo_profile_url`.
4. Output specific schema.
"""

import argparse
import sys
import os
import re
import random
import time
import pandas as pd
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Fix Unicode output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "transform_scrape.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("transform_scrape")

# ── 1. Name Parsing ────────────────────────────────────────────────────────
PREFIXES = r"^(Dr\.|Dr|Mr\.|Mr|Ms\.|Ms|Mrs\.|Mrs|Prof\.|Prof|Dr\. med\.)\s+"

def parse_name(full_name: str):
    if not isinstance(full_name, str) or not full_name.strip():
        return "", ""
    
    # 1. Strip trailing tags like (Physiotherapist)
    name = re.sub(r"\(.*?\)$", "", full_name).strip()
    
    # 2. Remove prefix
    name = re.sub(PREFIXES, "", name, flags=re.IGNORECASE).strip()
    
    # 3. Trim extra whitespace
    name = re.sub(r"\s+", " ", name).strip()
    
    tokens = name.split(" ")
    if len(tokens) == 1:
        return tokens[0], ""
    elif len(tokens) >= 2:
        return tokens[0], tokens[-1]
    return "", ""


# ── 2. Specialization Normalization ─────────────────────────────────────────
CANONICAL_MAP = {
    "Gynecologist": "Gynecologist",
    "Gynaecologist": "Gynecologist",
    "Obstetrician": "Gynecologist",
    "Obstetrician and Gynecologist": "Gynecologist",
    "Gynecologist/Obstetrician": "Gynecologist",
    "OB-GYN": "Gynecologist",
    
    "Dermatologist": "Dermatologist",
    "Skin Specialist": "Dermatologist",
    "Cosmetologist": "Dermatologist",
    "Aesthetic Dermatologist": "Dermatologist",
    
    "General Physician": "General Physician",
    "GP": "General Physician",
    "Internal Medicine Specialist": "General Physician",
    "Internal Medicine": "General Physician",
    "General Medicine": "General Physician",
    "General Practitioner": "General Physician",
    
    "Dentist": "Dentist",
    "Dental Surgeon": "Dentist",
    "Endodontist": "Dentist",
    "Orthodontist": "Dentist",
    "Pediatric Dentist": "Dentist",
    "Periodontist": "Dentist",
    "Restorative Dentist": "Dentist",
    "Implantologist": "Dentist",
    "Orthodontist & Dentofacial Orthopedist": "Dentist",
    
    "Pediatrician": "Pediatrician",
    "Orthopedic surgeon": "Orthopedist",
    "Orthopedist": "Orthopedist",
    "Joint Replacement Surgeon": "Orthopedist",
    "Psychiatrist": "Psychiatrist",
    "Psychologist": "Psychologist",
    "Clinical Psychologist": "Psychologist",
    "Counselling Psychologist": "Psychologist",
    "Rehabilitation Psychologist": "Psychologist",
    "Health Psychologist": "Psychologist",
    "Cardiologist": "Cardiologist",
    "Neurologist": "Neurologist",
    "Physiotherapist": "Physiotherapist",
    "Clinical Physiotherapist": "Physiotherapist",
    "Neuro Physiotherapist": "Physiotherapist",
    "Geriatric Physiotherapist": "Physiotherapist",
    "Infertility Specialist": "Infertility Specialist",
    "Pulmonologist": "Pulmonologist",
    "Homoeopath": "Homoeopath",
}

unmapped_specializations = set()

def normalize_specialization(raw_spec: str):
    if not isinstance(raw_spec, str) or not raw_spec.strip():
        return ""
    
    parts = raw_spec.split(",")
    cleaned_parts = []
    
    for part in parts:
        part = re.sub(r"\(Unverified\).*$", "", part).strip()
        if not part:
            continue
            
        if part in CANONICAL_MAP:
            mapped = CANONICAL_MAP[part]
        else:
            mapped = part
            unmapped_specializations.add(part)
        
        # Deduplicate while preserving order
        if mapped not in cleaned_parts:
            cleaned_parts.append(mapped)
            
    return ", ".join(cleaned_parts)

# ── 3. Address Scraping ─────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def _extract_address(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    
    clinics = []
    
    # Strategy 1: Look for data-qa-id containing "address"
    address_nodes = soup.find_all(attrs={"data-qa-id": lambda x: x and "address" in str(x).lower()})
    for node in address_nodes:
        clinics.append(node.get_text(" ", strip=True))
        
    # Strategy 2: Look for specific clinic blocks if Strategy 1 yields nothing
    if not clinics:
        clinic_items = soup.find_all("div", class_="c-profile--clinic--item")
        for item in clinic_items:
            # Typical structure has address in paragraphs inside this container
            text = item.get_text(" ", strip=True)
            text = re.sub(r"Get Directions.*", "", text).strip()
            text = re.sub(r"Call Clinic.*", "", text).strip()
            if text:
                clinics.append(text)
                
    if clinics:
        # Remove duplicates while preserving order
        seen = set()
        unique_clinics = []
        for c in clinics:
            if c and c not in seen:
                seen.add(c)
                unique_clinics.append(c)
        return " | ".join(unique_clinics)
    
    return ""

def scrape_address(page, url: str) -> str:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        try:
            page.wait_for_selector("[data-qa-id='doctor-name'], h1.c-profile__title", timeout=5_000)
        except PlaywrightTimeout:
            pass # Check HTML anyway
            
        time.sleep(1) # Small delay for rendering
        html = page.content()
        
        soup = BeautifulSoup(html, "lxml")
        title_el = soup.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        if "challenge" in title.lower():
            log.warning(f"Bot challenge hit for {url}")
            return ""
            
        return _extract_address(html)
    except Exception as e:
        log.error(f"Error scraping {url}: {e}")
        return ""

def batch_scrape_addresses(df: pd.DataFrame, limit: int = None, output_path: str = None) -> pd.DataFrame:
    tracker_file = None
    done_urls = set()
    
    if output_path:
        tracker_file = Path(output_path).parent / f".scraped_urls_{Path(output_path).stem}.txt"
        if tracker_file.exists():
            with open(tracker_file, "r", encoding="utf-8") as f:
                done_urls = {line.strip() for line in f if line.strip()}
            log.info(f"Loaded {len(done_urls):,} already-processed URLs from tracker.")

    # Only scrape URLs that haven't been visited yet
    all_urls = df['practo_profile_url'].dropna().unique()
    urls_to_scrape = [u for u in all_urls if u not in done_urls]
    
    if limit:
        urls_to_scrape = urls_to_scrape[:limit]
        
    if len(urls_to_scrape) == 0:
        log.info("No URLs need scraping (all already processed).")
        return df

    log.info(f"Going to scrape {len(urls_to_scrape)} remaining URLs for addresses (skipping {len(done_urls):,} already done)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        
        for i, url in enumerate(urls_to_scrape, 1):
            ua = random.choice(USER_AGENTS)
            ctx = browser.new_context(user_agent=ua)
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = ctx.new_page()
            
            log.info(f"[{i}/{len(urls_to_scrape)}] Scraping {url}")
            address = scrape_address(page, url)
            
            if not address:
                log.info("Retrying once...")
                time.sleep(random.uniform(1, 2))
                address = scrape_address(page, url)
                
            if not address:
                log.info(f"  -> Address not found.")
                address = ""
            else:
                log.info(f"  -> Address: {address[:60]}...")
            
            if address:
                df.loc[df['practo_profile_url'] == url, 'address_of_clinic'] = address
                
            done_urls.add(url)
            if tracker_file:
                with open(tracker_file, "a", encoding="utf-8") as tf:
                    tf.write(f"{url}\n")
                    
            ctx.close()
            
            # Incremental save every 20 records
            if output_path and i % 20 == 0:
                log.info("Incremental save to CSV...")
                df.to_csv(output_path, index=False, encoding="utf-8-sig")
            
            if i < len(urls_to_scrape):
                time.sleep(random.uniform(1.5, 3.5))
                
        browser.close()
        
    return df

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="Input CSV (e.g. checkpoint)")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument("--limit", type=int, default=None, help="Limit scraping for testing")
    args = parser.parse_args()
    
    log.info(f"Reading {args.input}...")
    df = pd.read_csv(args.input, dtype=str)
    
    # Initialize new columns
    if 'address_of_clinic' not in df.columns:
        df['address_of_clinic'] = ""
    
    log.info("Applying text transformations...")
    # 1. Names
    parsed_names = df['full_name'].apply(parse_name)
    df['first_name'] = parsed_names.apply(lambda x: x[0])
    df['last_name'] = parsed_names.apply(lambda x: x[1])
    
    # 2. Specializations
    df['specialization_alias'] = df['specialization'].apply(normalize_specialization)
    
    if unmapped_specializations:
        log.info(f"Found {len(unmapped_specializations)} unmapped specializations. Top 20: {list(unmapped_specializations)[:20]}")
    
    # 3. Final Formatting Setup before scraping so incremental saves have correct schema
    final_cols = [
        "full_name", "first_name", "last_name", "specialization", "specialization_alias", 
        "qualification", "experience", "address_of_clinic", "location", 
        "registration_details", "practo_profile_url"
    ]
    
    for col in final_cols:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
        df[col] = df[col].replace({"nan": "", "None": "", "NaN": "", "NA": ""})
        
    df = df[final_cols]
    
    # 4. Scrape addresses
    log.info("Starting address scraping phase...")
    df = batch_scrape_addresses(df, limit=args.limit, output_path=args.output)
    
    # Final cleanup
    for col in final_cols:
        df[col] = df[col].fillna("").astype(str).str.strip()
        df[col] = df[col].replace({"nan": "", "None": "", "NaN": "", "NA": ""})
    
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    log.info(f"Saved final CSV to {args.output}")
    
    xlsx_path = args.output.replace(".csv", ".xlsx")
    try:
        df.to_excel(xlsx_path, index=False)
        log.info(f"Saved XLSX to {xlsx_path}")
    except Exception as e:
        log.warning(f"Could not save XLSX: {e}")

if __name__ == "__main__":
    main()
