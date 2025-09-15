import streamlit as st
import pandas as pd
from datetime import datetime
import os

from arbitrage_core import find_opportunities, discover_best_seller_categories

st.set_page_config(page_title="Amazon→eBay Research (UK) — Reliable Scan", page_icon="🔍", layout="wide")

st.title("Amazon → eBay Research (UK) — Reliable Scan")
st.caption("Uses official eBay Finding API (if EBAY_APP_ID set) and proxy provider for Amazon (if configured) to reduce blocks.")

with st.expander("Setup status"):
    has_app = bool(os.environ.get("EBAY_APP_ID"))
    has_scraper = bool(os.environ.get("SCRAPERAPI_KEY") or os.environ.get("ZENROWS_API_KEY"))
    st.write(f"eBay Finding API (EBAY_APP_ID): {'✅ set' if has_app else '⚠️ not set — will fallback to HTML scraping'}")
    st.write(f"Amazon proxy (SCRAPERAPI_KEY or ZENROWS_API_KEY): {'✅ set' if has_scraper else '⚠️ not set — may see occasional blocks on Render'}")

with st.expander("⚠️ Policy notice", expanded=False):
    st.markdown("""
- **eBay** prohibits retail-to-retail dropshipping (e.g., listing on eBay then buying from Amazon to ship). Use compliant sources (your stock, wholesale, 3PL).
- **Amazon Prime T&Cs** prohibit using Prime to ship to **your customers** or for **resale**.
This app is for **market research**; auto-post (if you enable it separately) should be for compliant inventory only.
""")

with st.sidebar:
    st.header("Scan settings")
    autod = st.checkbox("Auto-discover Amazon Best Seller categories", value=True)
    max_cats = st.slider("How many categories to scan", 5, 40, 12, 1)
    cats_text = ""
    if not autod:
        cats_text = st.text_area("Amazon Best Sellers URLs (one per line)", height=160, placeholder="https://www.amazon.co.uk/gp/bestsellers/electronics\nhttps://www.amazon.co.uk/gp/bestsellers/kitchen")

    min_profit = st.number_input("Min profit (£)", min_value=0.0, max_value=1000.0, value=3.0, step=0.5)
    min_margin = st.slider("Min margin (%)", min_value=0, max_value=50, value=12, step=1)
    min_sold = st.slider("Min 'sold recently' (eBay)", min_value=0, max_value=200, value=10, step=1)
    ebay_fee_rate = st.number_input("eBay fee rate (e.g., 0.13 = 13%)", min_value=0.0, max_value=0.3, value=0.13, step=0.01, format="%.2f")
    ebay_fixed_fee = st.number_input("eBay fixed fee (£)", min_value=0.0, max_value=2.0, value=0.30, step=0.05)
    max_items = st.slider("Max Amazon items per category", min_value=10, max_value=200, value=50, step=10)
    max_ebay_results = st.slider("Max eBay results to scan (HTML fallback only)", min_value=3, max_value=20, value=8, step=1)
    query_words = st.slider("Use first N title words for eBay query", min_value=4, max_value=20, value=8, step=1)
    avoid = st.text_input("Avoid keywords (comma-separated)", value="Apple iPhone,Nike,PlayStation,Xbox,Gift Card")
    run = st.button("Run scan")

if run:
    if autod:
        with st.spinner("Discovering Amazon Best Seller categories..."):
            categories = discover_best_seller_categories(max_categories=max_cats)
    else:
        categories = [ln.strip() for ln in cats_text.splitlines() if ln.strip()]

    if not categories:
        st.error("No categories to scan. Provide URLs or use auto-discover.")
    else:
        with st.spinner("Scanning categories, verifying eBay demand, and calculating profit..."):
            results = find_opportunities(
                categories=categories,
                min_profit=min_profit,
                min_margin=min_margin/100.0,
                min_sold_recent=min_sold,
                ebay_fee_rate=ebay_fee_rate,
                ebay_fixed_fee=ebay_fixed_fee,
                max_items=max_items,
                max_ebay_results=max_ebay_results,
                avoid_keywords=[s.strip() for s in avoid.split(",") if s.strip()],
                query_words=query_words
            )
        if not results:
            st.info("No items matched your thresholds. Try lowering thresholds or adjusting categories.")
        else:
            df = pd.DataFrame([r.__dict__ for r in results])
            df["est_margin_pct"] = (df["est_margin"] * 100).round(2)
            cols = ["title","amazon_price","ebay_price","ebay_shipping","ebay_total_price","estimated_ebay_fee","est_profit_gbp","est_margin_pct","sold_recent","prime","rating","reviews","amazon_url","ebay_url","asin","category_url","image_url"]
            df = df[cols]
            st.success(f"Found {len(df)} suggestions across {len(categories)} categories")
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button("Download Suggestions CSV", data=csv, file_name=f"suggestions_{ts}.csv", mime="text/csv")
else:
    st.info("Choose auto-discover or paste URLs, then click **Run scan**.")
