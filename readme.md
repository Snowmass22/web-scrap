# Web‑Scrap Practo Doctor Profiles

A lightweight Python toolkit for extracting doctor profile data from Practo across multiple Indian cities.

---

## ✨ Overview

- **Bulk scraper** (`scripts/bulk_scraper.py`) – multi‑threaded, checkpoint‑aware scraper that can resume after interruptions.
- **Single‑profile scraper** (`scripts/scrape_doctor_profile.py`) – core Playwright‑based routine that fetches a page, renders it, and parses the needed fields.
- **URL filter** (`scripts/filter_pune_urls.py`) – extracts location‑specific URLs from the master sitemap CSV.
- **Utility scripts** – helpers for fetching the sitemap, sampling profiles, and post‑processing.

The pipeline is designed to run **in parallel** both **within a city** (ThreadPoolExecutor) and **across multiple cities** (simply launch several `bulk_scraper.py` processes with different `--location` arguments).

---

## 🛠️ Prerequisites

- **Python 3.10+**
- **Playwright** (installed via `pip install playwright` and then `playwright install`)
- **Pandas**, **BeautifulSoup4**, **requests**
- A modern browser (Chromium) – Playwright will download it automatically.

> **Tip:** The scraper runs with `headless=False` to bypass Cloudflare bot detection.  If you prefer headless mode, change `headless=False` to `True` in `scrape_doctor_profile.py` (line ~92).

---

## ⚙️ Installation

```bash
# Clone the repository (if you haven't already)
git clone https://github.com/your‑username/web-scrap.git
cd web-scrap

# Create a virtual environment (recommended)
python -m venv .venv
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt   # create this file if missing:
# pandas==2.*, beautifulsoup4==4.*, playwright==1.*, tqdm, etc.

# Install Playwright browsers
playwright install
```

---

## 🚀 Quick Start – Scrape a Single City

1. **Generate the master URL list** (only needed once). Example for Pune:
   ```bash
   python scripts/fetch_profiles_sitemap.py -l pune
   ```
   This produces `output/profile_urls_pune.csv`.

2. **Filter URLs for the desired location** (optional – useful when the sitemap contains many cities):
   ```bash
   python scripts/filter_pune_urls.py -l mumbai   # change the -l argument as needed
   ```
   Output: `output/profile_urls_mumbai.csv`.

3. **Run the bulk scraper**:
   ```bash
   python scripts/bulk_scraper.py -l mumbai
   ```
   - Results are stored in `output/practo_doctors_checkpoint_mumbai.csv` (incremental checkpoint).
   - Failed URLs go to `output/failed_urls_mumbai.csv`.
   - Use `--checkpoint` / `--failed` flags to customise paths.

---

## 🔄 Parallel Execution Across Cities

Open separate terminals (or background tasks) and launch a scraper for each location:

```bash
# Terminal 1 – Delhi
python scripts/bulk_scraper.py -l delhi &

# Terminal 2 – Mumbai
python scripts/bulk_scraper.py -l mumbai &

# Terminal 3 – Bangalore
python scripts/bulk_scraper.py -l bangalore &
```

Each process works on its own CSV files, so there are no write‑conflicts.  Adjust `MAX_WORKERS` in `scripts/bulk_scraper.py` (default = 3) if your machine needs fewer concurrent browsers.

---

## 📂 Directory Layout

```
web-scrap/
│   .gitignore
│   README.md          ← you are reading this now
│
├─ scripts/            ← all executable Python utilities
│   ├─ bulk_scraper.py
│   ├─ scrape_doctor_profile.py
│   ├─ filter_pune_urls.py
│   ├─ fetch_profiles_sitemap.py
│   ├─ fetch_sample_profile.py
│   └─ ...
│
├─ output/             ← generated CSV/Excel files
│   ├─ profile_urls_*.csv
│   ├─ practo_doctors_checkpoint_*.csv
│   └─ failed_urls_*.csv
│
└─ logs/               ← scraper logs (scraper.log, scrape_log.txt)
```

---

## 🧹 Cleaning Up

To start a fresh run, simply delete the checkpoint and failed‑URL files for that city:
```bash
rm output/practo_doctors_checkpoint_mumbai.csv
rm output/failed_urls_mumbai.csv
```
The scraper will then re‑process every URL from the filtered CSV.

---

## 🤝 Contributing

Feel free to open issues or submit pull‑requests.  When adding new features, keep the following in mind:
- Preserve the **checkpoint‑friendly** design.
- Log structured events via `_log_request` in `scrape_doctor_profile.py`.
- Update the README with any new scripts or command‑line options.

---

## 📜 License

This project is provided **as‑is** under the MIT License.  Use it responsibly and respect Practo’s terms of service.

---

Happy scraping! 🎉
