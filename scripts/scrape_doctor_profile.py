"""
scrape_doctor_profile.py
Scrapes a single Practo doctor profile page and returns structured data.

Features:
 - Random 2-4 second delay between requests (polite crawling)
 - Rotating pool of realistic User-Agent strings
 - Dual logging: scraper.log (debug) + scrape_log.txt (structured request audit)
"""

import re
import json
import random
import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Delay config ─────────────────────────────────────────────────────────────
DELAY_MIN = 2.0   # seconds
DELAY_MAX = 4.0   # seconds

# ── Rotating User-Agent pool (realistic desktop browsers) ────────────────────
USER_AGENTS = [
    # Chrome 124 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome 124 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox 125 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge 124 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

# ── Logging setup ────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

# General debug log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Structured request audit log (scrape_log.txt)
_audit_handler = logging.FileHandler("logs/scrape_log.txt", encoding="utf-8")
_audit_handler.setFormatter(logging.Formatter("%(message)s"))
_audit_log = logging.getLogger("scrape_audit")
_audit_log.setLevel(logging.INFO)
_audit_log.addHandler(_audit_handler)
_audit_log.propagate = False  # don't echo to console

# ─────────────────────────────────────────────────────────────────────────────
# Request audit logger
# ─────────────────────────────────────────────────────────────────────────────
def _log_request(
    url: str,
    status: str,           # SUCCESS | BLOCKED | TIMEOUT | ERROR | NOT_FOUND
    name: str | None = None,
    detail: str = "",
) -> None:
    """
    Write one structured line to logs/scrape_log.txt.
    Format: TIMESTAMP | STATUS | URL | NAME | DETAIL
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name_str = name or "-"
    detail_str = detail.replace("|", "/")   # avoid field separator in detail
    _audit_log.info(f"{ts} | {status:<10} | {url} | {name_str} | {detail_str}")


# ─────────────────────────────────────────────────────────────────────────────
# HTML fetcher
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_html(url: str, timeout_ms: int = 30_000) -> str | None:
    """Launch Playwright in headed mode, navigate to url, return rendered HTML."""
    ua = random.choice(USER_AGENTS)
    log.debug(f"Using UA: {ua[:60]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,          # headed mode bypasses Cloudflare bot detection
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
            ],
        )
        ctx = browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        # Hide the webdriver flag
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Wait for the doctor name element — confirms the profile loaded
            page.wait_for_selector(
                "[data-qa-id='doctor-name'], h1.c-profile__title",
                timeout=12_000,
            )
            page.wait_for_timeout(3_000)   # allow full React hydration
        except PlaywrightTimeout:
            log.warning(f"Timeout waiting for content on {url}")
        except Exception as exc:
            log.error(f"Navigation error for {url}: {exc}")
        finally:
            html = page.content()
            browser.close()
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Field extractors
# ─────────────────────────────────────────────────────────────────────────────
def _qa(soup: BeautifulSoup, qa_id: str) -> str | None:
    """Return stripped text from the first element with the given data-qa-id."""
    el = soup.find(attrs={"data-qa-id": qa_id})
    return el.get_text(strip=True) if el else None


def _extract_full_name(soup: BeautifulSoup, ld: dict) -> str | None:
    try:
        return _qa(soup, "doctor-name") or ld.get("name")
    except Exception:
        return None


def _extract_specialization(soup: BeautifulSoup, ld: dict) -> str | None:
    try:
        # data-qa-id="specializations-item" elements (may be multiple)
        items = soup.find_all(attrs={"data-qa-id": "specializations-item"})
        if items:
            return ", ".join(i.get_text(strip=True) for i in items)
        # Fallback: JSON-LD medicalSpecialty
        specs = ld.get("medicalSpecialty", [])
        if specs:
            return ", ".join(specs)
        # Fallback: parse the combined specialization text
        raw = _qa(soup, "doctor-specializations") or ""
        match = re.match(r"^([A-Za-z &/\-,]+)", raw)
        return match.group(1).strip() if match else None
    except Exception:
        return None


def _extract_qualification(soup: BeautifulSoup) -> str | None:
    try:
        return _qa(soup, "doctor-qualifications")
    except Exception:
        return None


def _extract_experience(soup: BeautifulSoup, ld: dict) -> str | None:
    try:
        # The combined specializations element contains "NYears Experience"
        raw = _qa(soup, "doctor-specializations") or ""
        match = re.search(r"(\d+)\s*[Yy]ear", raw)
        if match:
            return match.group(1) + " years"
        # Fallback: description in JSON-LD
        desc = ld.get("description", "")
        match = re.search(r"experience of (\d+) year", desc, re.IGNORECASE)
        return match.group(1) + " years" if match else None
    except Exception:
        return None


def _extract_location(url: str) -> str | None:
    try:
        # URL pattern: practo.com/<city>/doctor/...
        match = re.search(r"practo\.com/([^/]+)/(?:doctor|therapist)/", url)
        return match.group(1).title() if match else None
    except Exception:
        return None


def _extract_registration(soup: BeautifulSoup) -> str | None:
    try:
        # May have multiple registration entries
        items = soup.find_all(attrs={"data-qa-id": "registrations-item"})
        if not items:
            return None
        # Return the full text of each entry (reg_no + council + year)
        # e.g. "2018051408 Maharashtra Medical Council, 2018"
        entries = [item.get_text(strip=True) for item in items]
        return "; ".join(entries)
    except Exception:
        return None


def _extract_clinic_address(soup: BeautifulSoup) -> str | None:
    try:
        clinics = []
        # Strategy 1: Look for data-qa-id containing "address"
        address_nodes = soup.find_all(attrs={"data-qa-id": lambda x: x and "address" in str(x).lower()})
        for node in address_nodes:
            clinics.append(node.get_text(" ", strip=True))
            
        # Strategy 2: Look for specific clinic blocks if Strategy 1 yields nothing
        if not clinics:
            clinic_items = soup.find_all("div", class_="c-profile--clinic--item")
            for item in clinic_items:
                text = item.get_text(" ", strip=True)
                text = re.sub(r"Get Directions.*", "", text).strip()
                text = re.sub(r"Call Clinic.*", "", text).strip()
                if text:
                    clinics.append(text)
                    
        if clinics:
            seen = set()
            unique_clinics = []
            for c in clinics:
                if c and c not in seen:
                    seen.add(c)
                    unique_clinics.append(c)
            return " | ".join(unique_clinics)
    except Exception:
        pass
    return None


def _load_ld_json(soup: BeautifulSoup) -> dict:
    """Return the first Physician JSON-LD block, or empty dict."""
    for tag in soup.find_all("script", type="application/ld+json"):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if entry.get("@type") == "Physician":
                    return entry
        except Exception:
            continue
    return {}


# ── Specialization Canonical Mapping ─────────────────────────────────────────
CANONICAL_MAP = {
    "Gynecologist": "Gynecologist", "Gynaecologist": "Gynecologist", "Obstetrician": "Gynecologist",
    "Obstetrician and Gynecologist": "Gynecologist", "Gynecologist/Obstetrician": "Gynecologist", "OB-GYN": "Gynecologist",
    "Dermatologist": "Dermatologist", "Skin Specialist": "Dermatologist", "Cosmetologist": "Dermatologist",
    "Aesthetic Dermatologist": "Dermatologist",
    "General Physician": "General Physician", "GP": "General Physician", "Internal Medicine Specialist": "General Physician",
    "Internal Medicine": "General Physician", "General Medicine": "General Physician", "General Practitioner": "General Physician",
    "Dentist": "Dentist", "Dental Surgeon": "Dentist", "Endodontist": "Dentist", "Orthodontist": "Dentist",
    "Pediatric Dentist": "Dentist", "Periodontist": "Dentist", "Restorative Dentist": "Dentist", "Implantologist": "Dentist",
    "Orthodontist & Dentofacial Orthopedist": "Dentist",
    "Pediatrician": "Pediatrician", "Orthopedic surgeon": "Orthopedist", "Orthopedist": "Orthopedist",
    "Joint Replacement Surgeon": "Orthopedist", "Psychiatrist": "Psychiatrist", "Psychologist": "Psychologist",
    "Clinical Psychologist": "Psychologist", "Counselling Psychologist": "Psychologist",
    "Rehabilitation Psychologist": "Psychologist", "Health Psychologist": "Psychologist",
    "Cardiologist": "Cardiologist", "Neurologist": "Neurologist", "Physiotherapist": "Physiotherapist",
    "Clinical Physiotherapist": "Physiotherapist", "Neuro Physiotherapist": "Physiotherapist",
    "Geriatric Physiotherapist": "Physiotherapist", "Infertility Specialist": "Infertility Specialist",
    "Pulmonologist": "Pulmonologist", "Homoeopath": "Homoeopath",
}

def _parse_name_parts(full_name: str | None) -> tuple[str, str]:
    if not full_name or not full_name.strip():
        return "", ""
    prefixes = r"^(Dr\.|Dr|Mr\.|Mr|Ms\.|Ms|Mrs\.|Mrs|Prof\.|Prof|Dr\. med\.)\s+"
    name = re.sub(r"\(.*?\)$", "", full_name).strip()
    name = re.sub(prefixes, "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+", " ", name).strip()
    tokens = name.split(" ")
    if len(tokens) == 1:
        return tokens[0], ""
    elif len(tokens) >= 2:
        return tokens[0], tokens[-1]
    return "", ""

def _build_specialization_alias(raw_spec: str | None) -> str:
    if not raw_spec or not raw_spec.strip():
        return ""
    parts = raw_spec.split(",")
    cleaned_parts = []
    for part in parts:
        part = re.sub(r"\(Unverified\).*$", "", part).strip()
        if not part: continue
        mapped = CANONICAL_MAP.get(part, part)
        if mapped not in cleaned_parts:
            cleaned_parts.append(mapped)
    return ", ".join(cleaned_parts)

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def scrape_doctor_profile(url: str) -> dict:
    """
    Scrape a Practo doctor profile page and return a structured dict.

    Returns a dict with keys:
        full_name, first_name, last_name, specialization, specialization_alias,
        qualification, experience, location, registration_details, address_of_clinic, practo_profile_url

    Missing fields return None instead of raising.
    """
    log.info(f"Scraping: {url}")
    result = {
        "full_name":             None,
        "first_name":            None,
        "last_name":             None,
        "specialization":        None,
        "specialization_alias":  None,
        "qualification":         None,
        "experience":            None,
        "location":              None,
        "registration_details":  None,
        "address_of_clinic":     None,
        "practo_profile_url":    url,
    }

    html = _fetch_html(url)
    if not html:
        log.warning(f"No HTML returned for {url}")
        _log_request(url, "ERROR", detail="No HTML returned")
        return result

    soup = BeautifulSoup(html, "lxml")

    # Detect challenge / 404 page
    title_el = soup.find("title")
    title = title_el.get_text(strip=True) if title_el else ""

    if "challenge" in title.lower():
        log.warning(f"Bot-challenge page received: {url}")
        _log_request(url, "BLOCKED", detail=f"title='{title}'")
        result["location"] = _extract_location(url)
        return result

    if not soup.find(attrs={"data-qa-id": "doctor-name"}):
        log.warning(f"Profile not found / empty (title='{title}'): {url}")
        _log_request(url, "NOT_FOUND", detail=f"title='{title}'")
        result["location"] = _extract_location(url)
        return result

    ld = _load_ld_json(soup)

    result["full_name"]            = _extract_full_name(soup, ld)
    result["specialization"]       = _extract_specialization(soup, ld)
    result["qualification"]        = _extract_qualification(soup)
    result["experience"]           = _extract_experience(soup, ld)
    result["location"]             = _extract_location(url)
    result["registration_details"] = _extract_registration(soup)
    result["address_of_clinic"]    = _extract_clinic_address(soup)
    
    first, last = _parse_name_parts(result["full_name"])
    result["first_name"] = first
    result["last_name"] = last
    result["specialization_alias"] = _build_specialization_alias(result["specialization"])

    log.info(f"  → {result['full_name']} | {result['specialization']} | {result['experience']}")
    _log_request(
        url,
        "SUCCESS",
        name=result["full_name"],
        detail=f"{result['specialization']} | {result['experience']}",
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Quick test on 5 sample URLs
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base, "output", "profile_urls_pune.csv")

    df = pd.read_csv(csv_path)
    # Prefer doctor/ URLs only for the test
    doctor_urls = (
        df[df["url"].str.contains("/doctor/", na=False)]["url"]
        .dropna()
        .tolist()
    )
    sample_urls = doctor_urls[:5]

    print(f"\n{'='*70}")
    print(f"Testing scrape_doctor_profile() on {len(sample_urls)} URLs")
    print(f"{'='*70}\n")

    results = []
    for i, url in enumerate(sample_urls, 1):
        print(f"[{i}/{len(sample_urls)}] {url}")
        data = scrape_doctor_profile(url)
        results.append(data)
        for k, v in data.items():
            if k != "practo_profile_url":
                print(f"  {k:>20}: {v}")
        print()

        # ── Polite inter-request delay (skip after last URL) ──────────────
        if i < len(sample_urls):
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            log.info(f"Waiting {delay:.1f}s before next request...")
            time.sleep(delay)

    print(f"{'='*70}")
    print("Summary DataFrame:")
    print(f"{'='*70}")
    print(pd.DataFrame(results).to_string(index=False))

    print(f"\nRequest log written to: logs/scrape_log.txt")
