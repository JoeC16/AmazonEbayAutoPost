"""
arbitrage_core.py (v4)
- Amazon: robust GET with optional proxy providers (SCRAPERAPI_KEY or ZENROWS_API_KEY).
- eBay: demand & best-price prefer official Finding API if EBAY_APP_ID is set; else HTML fallback.
- Goal: make scans *work reliably* on Render without crashing.
"""
import os, random, re, time, urllib.parse
from typing import List, Optional, Tuple, Set
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

AMAZON_BASE = "https://www.amazon.co.uk"
AMAZON_BEST_ROOT = "https://www.amazon.co.uk/gp/bestsellers"
EBAY_SEARCH_URL = "https://www.ebay.co.uk/sch/i.html"

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

DELAY_MIN = float(os.environ.get("SCRAPER_DELAY_MIN", 0.9))
DELAY_MAX = float(os.environ.get("SCRAPER_DELAY_MAX", 2.0))
MAX_RETRIES = int(os.environ.get("SCRAPER_MAX_RETRIES", 6))
BACKOFF_BASE = float(os.environ.get("SCRAPER_BACKOFF_BASE", 2.0))

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")
ZENROWS_API_KEY = os.environ.get("ZENROWS_API_KEY")

def sleep_polite(a: float = DELAY_MIN, b: float = DELAY_MAX):
    time.sleep(random.uniform(a, b))

class FetchError(Exception):
    pass

def _wrap_with_provider(url: str) -> str:
    """Use a proxy/antibot provider when available (preferred on Render)."""
    if SCRAPERAPI_KEY:
        # country_code=uk to localize prices/listings; keep_headers for UA propagation
        wrapper = "http://api.scraperapi.com"
        params = {"api_key": SCRAPERAPI_KEY, "country_code": "uk", "keep_headers": "true", "url": url}
        return wrapper + "?" + urllib.parse.urlencode(params)
    if ZENROWS_API_KEY:
        wrapper = "https://api.zenrows.com/v1/"
        params = {"apikey": ZENROWS_API_KEY, "url": url, "premium_proxy": "true", "js_render": "false"}
        return wrapper + "?" + urllib.parse.urlencode(params)
    return url

def get(url: str) -> requests.Response:
    """
    Robust GET with rotating headers, retry/backoff and optional proxy providers.
    Raises FetchError if all retries fail.
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        headers = {
            "User-Agent": random.choice(HEADERS_POOL),
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
        }
        try:
            url_eff = _wrap_with_provider(url)
            resp = requests.get(url_eff, headers=headers, timeout=30)
            # If using provider, many errors are handled upstream; still handle 403/429/5xx
            if resp.status_code in (429, 503, 502, 520, 522, 524):
                time.sleep(BACKOFF_BASE * attempt);  continue
            if resp.status_code == 403:
                time.sleep(BACKOFF_BASE * attempt)
                if attempt < MAX_RETRIES:
                    continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            time.sleep(BACKOFF_BASE * attempt)
    raise FetchError(f"Failed to fetch after retries: {url} :: {last_exc}")

_price_re = re.compile(r"£\s*([0-9]+(?:[\.,][0-9]{1,2})?)")
def parse_price_gbp(text: str) -> Optional[float]:
    if not text:
        return None
    m = _price_re.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "").replace(" ", "").replace("£", ""))
    except:
        return None

def safe_int(text: str) -> Optional[int]:
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None

def safe_float(text: str) -> Optional[float]:
    try:
        return float(text)
    except:
        return None

@dataclass
class AmazonProduct:
    title: str
    asin: Optional[str]
    price_gbp: Optional[float]
    prime: bool
    rating: Optional[float]
    reviews_count: Optional[int]
    url: str
    category_url: str
    image_url: Optional[str] = None

@dataclass
class EbayResult:
    title: str
    price_gbp: Optional[float]
    shipping_gbp: float
    url: str

@dataclass
class OpportunityRow:
    title: str
    amazon_price: Optional[float]
    ebay_price: Optional[float]
    ebay_shipping: float
    ebay_total_price: Optional[float]
    estimated_ebay_fee: Optional[float]
    est_profit_gbp: Optional[float]
    est_margin: Optional[float]
    prime: bool
    rating: Optional[float]
    reviews: Optional[int]
    amazon_url: str
    ebay_url: str
    asin: Optional[str]
    category_url: str
    image_url: Optional[str]
    sold_recent: int

DEFAULT_SEED_CATEGORIES = [
    f"{AMAZON_BEST_ROOT}/electronics",
    f"{AMAZON_BEST_ROOT}/kitchen",
    f"{AMAZON_BEST_ROOT}/computers",
    f"{AMAZON_BEST_ROOT}/garden",
    f"{AMAZON_BEST_ROOT}/sports",
    f"{AMAZON_BEST_ROOT}/toys",
    f"{AMAZON_BEST_ROOT}/health",
    f"{AMAZON_BEST_ROOT}/beauty",
    f"{AMAZON_BEST_ROOT}/diy",
    f"{AMAZON_BEST_ROOT}/automotive"
]

def discover_best_seller_categories(max_categories: int = 20) -> List[str]:
    found: Set[str] = set()
    try:
        resp = get(AMAZON_BEST_ROOT)
        soup = BeautifulSoup(resp.text, "html.parser")
        anchors = soup.select("a[href*='/gp/bestsellers/']")
        for a in anchors:
            href = a.get("href","")
            if not href: 
                continue
            url = href if href.startswith("http") else urllib.parse.urljoin(AMAZON_BASE, href)
            path = urllib.parse.urlparse(url).path
            if re.search(r"/gp/bestsellers/[^/]+/?$", path):
                found.add(url)
                if len(found) >= max_categories:
                    break
        if not found:
            found.update(DEFAULT_SEED_CATEGORIES[:max_categories])
    except FetchError:
        found.update(DEFAULT_SEED_CATEGORIES[:max_categories])
    return sorted(found)[:max_categories]

def extract_asin_from_href(href: str) -> Optional[str]:
    if not href:
        return None
    m = re.search(r"/dp/([A-Z0-9]{10})", href)
    if m:
        return m.group(1)
    m = re.search(r"/gp/product/([A-Z0-9]{10})", href)
    if m:
        return m.group(1)
    return None

def parse_amazon_bestseller_card(card, category_url: str) -> Optional[AmazonProduct]:
    link = card.select_one("a.a-link-normal:not(.aok-block)")
    if not link:
        link = card.select_one("a.a-link-normal")
    if not link:
        return None
    href = link.get("href", "")
    url = href if href.startswith("http") else urllib.parse.urljoin(AMAZON_BASE, href)

    title_el = card.select_one("div._cDEzb_p13n-sc-css-line-clamp-3_g3dy1, span.a-size-small, span.a-size-base, span._cDEzb_p13n-sc-css-line-clamp-2_EWgCb")
    title = (title_el.get_text(" ", strip=True) if title_el else link.get("title") or "").strip()
    if not title:
        title = link.get_text(" ", strip=True)

    asin = extract_asin_from_href(href)

    price_el = card.select_one("span._cDEzb_p13n-sc-price_3mJ9Z, span.a-color-price")
    if not price_el:
        price_el = card.select_one("span.a-offscreen")
    price_gbp = parse_price_gbp(price_el.get_text(" ", strip=True) if price_el else "")

    prime = bool(card.select_one("i.a-icon-prime, span[aria-label*='Prime']"))

    rating = None
    rating_el = card.select_one("i.a-icon-star-small span.a-icon-alt, span.a-icon-alt")
    if rating_el:
        m = re.search(r"([0-9]+\.[0-9])", rating_el.get_text(strip=True))
        rating = safe_float(m.group(1)) if m else None
    reviews_count = None
    reviews_el = card.select_one("span.a-size-base, span.a-size-small")
    if reviews_el:
        reviews_count = safe_int(reviews_el.get_text())

    img = card.select_one("img")
    image_url = img.get("src") if img and img.get("src","").startswith("http") else None

    return AmazonProduct(
        title=title[:180],
        asin=asin,
        price_gbp=price_gbp,
        prime=prime,
        rating=rating,
        reviews_count=reviews_count,
        url=url,
        category_url=category_url,
        image_url=image_url
    )

def scrape_amazon_bestsellers(category_url: str, max_items: int = 50) -> List[AmazonProduct]:
    out: List[AmazonProduct] = []
    for pg in [1, 2, 3]:
        url = category_url + ("&" if "?" in category_url else "?") + f"pg={pg}"
        sleep_polite()
        resp = get(url)  # now uses proxy + retries
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.zg-grid-general-faceout, div._cDEzb_grid-cell_1uMOS")
        if not cards:
            cards = soup.select("div.a-section.a-spacing-none.aok-relative")
        for c in cards:
            prod = parse_amazon_bestseller_card(c, category_url=category_url)
            if prod and prod.price_gbp is not None and prod.title:
                out.append(prod)
                if len(out) >= max_items:
                    return out
    return out

# ---------- eBay via official API (preferred) ----------
def ebay_find_best_price_api(app_id: str, query: str) -> Optional[EbayResult]:
    """
    Uses eBay Finding API 'findItemsByKeywords' with filters:
    - BuyItNowOnly
    - Condition: New
    - Sort: PricePlusShippingLowest
    """
    endpoint = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": app_id,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "keywords": query,
        "buyerPostalCode": "SW1A1AA",  # London centre; improve with user location if desired
        "sortOrder": "PricePlusShippingLowest",
        "itemFilter(0).name": "ListingType",
        "itemFilter(0).value(0)": "FixedPrice",
        "itemFilter(1).name": "Condition",
        "itemFilter(1).value(0)": "1000",  # New
        "itemFilter(2).name": "LocatedIn",
        "itemFilter(2).value(0)": "GB",
        "paginationInput.entriesPerPage": "10",
    }
    resp = requests.get(endpoint, params=params, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    try:
        items = data["findItemsByKeywordsResponse"][0]["searchResult"][0].get("item", [])
        if not items:
            return None
        # pick cheapest total (price + shipping)
        best = None
        for it in items:
            selling = it.get("sellingStatus", [{}])[0]
            price = float(selling.get("currentPrice", [{}])[0].get("__value__", "0"))
            ship_raw = it.get("shippingInfo", [{}])[0].get("shippingServiceCost", [{}])
            ship_cost = float(ship_raw[0].get("__value__", "0")) if ship_raw else 0.0
            total = price + ship_cost
            if best is None or total < best[0]:
                best = (total, price, ship_cost, it.get("viewItemURL", [""])[0], it.get("title", [""])[0])
        if not best:
            return None
        total, price, ship_cost, url, title = best
        return EbayResult(title=title[:200], price_gbp=price, shipping_gbp=ship_cost, url=url)
    except Exception:
        return None

def ebay_completed_sold_count_api(app_id: str, query: str, entries: int = 50) -> int:
    """
    Uses eBay Finding API 'findCompletedItems' + SoldItemsOnly=true to count recent solds.
    """
    endpoint = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": app_id,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "keywords": query,
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value(0)": "true",
        "itemFilter(1).name": "LocatedIn",
        "itemFilter(1).value(0)": "GB",
        "paginationInput.entriesPerPage": str(entries),
        "sortOrder": "EndTimeSoonest"
    }
    resp = requests.get(endpoint, params=params, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("findCompletedItemsResponse", [{}])[0].get("searchResult", [{}])[0].get("item", [])
    # Count items that ended with sales (eBay finding doesn't always provide quantity, but presence counts as sold)
    return len(items)

# ---------- eBay HTML fallback ----------
def scrape_ebay_best_price(query: str, max_results: int = 8) -> Optional[EbayResult]:
    params = {"_nkw": query, "LH_BIN": "1", "LH_PrefLoc": "1", "LH_ItemCondition": "1000", "rt": "nc", "_sop": "15"}
    url = EBAY_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    sleep_polite()
    resp = get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.s-item")[:max_results]
    best: Optional[EbayResult] = None
    for it in items:
        title_el = it.select_one("div.s-item__title span[role='heading'], h3.s-item__title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        price_el = it.select_one("span.s-item__price")
        price = parse_price_gbp(price_el.get_text(strip=True) if price_el else "")
        ship_el = it.select_one("span.s-item__shipping, span.s-item__logisticsCost")
        shipping = parse_price_gbp(ship_el.get_text(strip=True) if ship_el else "") or 0.0
        link_el = it.select_one("a.s-item__link")
        link = link_el.get("href") if link_el else url
        if price is None:
            continue
        total = price + shipping
        if best is None or total < (best.price_gbp or 9e9) + (best.shipping_gbp or 0):
            best = EbayResult(title=title[:200], price_gbp=price, shipping_gbp=shipping, url=link)
    return best

def ebay_sold_count_html(query: str, max_scan: int = 20) -> int:
    params = {"_nkw": query, "LH_Sold": "1", "LH_Complete": "1", "rt": "nc", "_sop": "10"}
    url = EBAY_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    sleep_polite(0.6, 1.4)
    resp = get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.s-item")[:max_scan]
    total_sold = 0
    for it in items:
        sold_el = None
        for sel in ["span.s-item__hotness", "span.BOLD", "span.s-item__quantitySold", "span[aria-label*='sold']"]:
            sold_el = it.select_one(sel)
            if sold_el:
                break
        text = sold_el.get_text(" ", strip=True).lower() if sold_el else ""
        m = re.search(r"([0-9][0-9,\.]*)\s+sold", text)
        if m:
            try:
                total_sold += int(m.group(1).replace(",", ""))
            except:
                pass
    return total_sold

def estimate_profit(amazon_price: Optional[float], ebay_price: Optional[float], ebay_shipping: float,
                    fee_rate: float, fixed_fee: float):
    if amazon_price is None or ebay_price is None:
        return None, None, None
    ebay_total_price = ebay_price + ebay_shipping
    fee = ebay_total_price * fee_rate + fixed_fee
    profit = ebay_total_price - amazon_price - fee
    margin = profit / ebay_total_price if ebay_total_price else None
    return ebay_total_price, fee, profit if margin is not None else (None, None, None)

def find_opportunities(categories: List[str],
                       min_profit: float = 3.0,
                       min_margin: float = 0.12,
                       min_sold_recent: int = 10,
                       ebay_fee_rate: float = 0.13,
                       ebay_fixed_fee: float = 0.30,
                       max_items: int = 50,
                       max_ebay_results: int = 8,
                       avoid_keywords: List[str] = None,
                       query_words: int = 8):
    if avoid_keywords is None:
        avoid_keywords = ["Apple iPhone","Nike","PlayStation","Xbox","Gift Card"]
    rows: List[OpportunityRow] = []
    EBAY_APP_ID = os.environ.get("EBAY_APP_ID")  # Finding API key
    for cat in categories:
        products = scrape_amazon_bestsellers(cat, max_items=max_items)
        for p in products:
            if any(k.lower() in p.title.lower() for k in avoid_keywords):
                continue
            query = " ".join(p.title.split()[:query_words])
            # eBay best price
            if EBAY_APP_ID:
                best = ebay_find_best_price_api(EBAY_APP_ID, query)
            else:
                best = scrape_ebay_best_price(query, max_results=max_ebay_results)
            ebay_price = best.price_gbp if best else None
            ebay_ship = best.shipping_gbp if best else 0.0
            # eBay demand
            sold_recent = 0
            if EBAY_APP_ID:
                sold_recent = ebay_completed_sold_count_api(EBAY_APP_ID, query, entries=50)
            else:
                sold_recent = ebay_sold_count_html(query, max_scan=20)
            ebay_total, fees, profit = estimate_profit(p.price_gbp, ebay_price, ebay_ship, ebay_fee_rate, ebay_fixed_fee)
            margin = (profit / ebay_total) if (profit is not None and ebay_total) else None
            if (profit is not None and margin is not None
                and sold_recent >= min_sold_recent and profit >= min_profit and margin >= min_margin):
                rows.append(OpportunityRow(
                    title=p.title,
                    amazon_price=p.price_gbp,
                    ebay_price=ebay_price,
                    ebay_shipping=ebay_ship,
                    ebay_total_price=ebay_total,
                    estimated_ebay_fee=fees,
                    est_profit_gbp=profit,
                    est_margin=margin,
                    prime=p.prime,
                    rating=p.rating,
                    reviews=p.reviews_count,
                    amazon_url=p.url,
                    ebay_url=best.url if best else "",
                    asin=p.asin,
                    category_url=p.category_url,
                    image_url=p.image_url,
                    sold_recent=sold_recent
                ))
    rows.sort(key=lambda r: (r.est_profit_gbp or -9e9, r.sold_recent), reverse=True)
    return rows
