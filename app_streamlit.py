
import streamlit as st
import pandas as pd
from datetime import datetime
import uuid, os

from arbitrage_core import find_opportunities, discover_best_seller_categories
from ebay_api import get_access_token_from_refresh, create_or_update_inventory_item, create_offer, publish_offer

st.set_page_config(page_title="Amazon→eBay Research (UK) + Auto-post", page_icon="🚀", layout="wide")

st.title("Amazon → eBay Research (UK) + Auto-post (optional)")
st.caption("Find Amazon UK best sellers with profit & demand on eBay. Optionally create draft eBay listings (Sell API).")

with st.expander("⚠️ Policy notice", expanded=False):
    st.markdown("""
- **eBay** prohibits retail-to-retail dropshipping (e.g., listing on eBay then buying from Amazon to ship). Use compliant sources (your stock, wholesale, 3PL).
- **Amazon Prime T&Cs** prohibit using Prime to ship to **your customers** or for **resale**.
This app is for **market research**; auto-post is provided for compliant inventory only.
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
    max_ebay_results = st.slider("Max eBay results to scan", min_value=3, max_value=20, value=8, step=1)
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

            st.markdown("### Optional: Create draft eBay listings")
            st.caption("Requires environment variables for eBay API. Creates inventory items & offers, then publishes as a draft/active listing depending on your policies/account.")
            can_post = all(os.environ.get(k) for k in ["EBAY_CLIENT_ID","EBAY_CLIENT_SECRET","EBAY_REFRESH_TOKEN","EBAY_FULFILLMENT_POLICY_ID","EBAY_PAYMENT_POLICY_ID","EBAY_RETURN_POLICY_ID"])
            if not can_post:
                st.warning("Set EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_REFRESH_TOKEN, EBAY_*_POLICY_ID env vars to enable auto-post.")
            else:
                post_rows = st.multiselect("Pick rows to post (by title)", options=df["title"].tolist())
                target_price_adj = st.slider("Increase listing price (%)", min_value=0, max_value=50, value=10, step=1)
                if st.button("Create draft listings now"):
                    try:
                        token = get_access_token_from_refresh()
                        done = 0
                        for _, row in df[df["title"].isin(post_rows)].iterrows():
                            import uuid
                            sku = "SKU-" + uuid.uuid4().hex[:10].upper()
                            title = row["title"][:80]
                            price = float(row["ebay_total_price"]) if row["ebay_total_price"] else float(row["ebay_price"] or 0.0)
                            price = price * (1 + target_price_adj/100.0)
                            imageUrls = [row["image_url"]] if row["image_url"] else []
                            desc = f"{row['title']}\n\nSourced from compliant inventory. See photos for details."
                            create_or_update_inventory_item(token, sku=sku, title=title, price=price, currency="GBP",
                                                            quantity=3, imageUrls=imageUrls, description=desc)
                            offer_id = create_offer(token, sku=sku, marketplaceId=os.environ.get("EBAY_MARKETPLACE_ID","EBAY_GB"),
                                                    categoryId=os.environ.get("EBAY_DEFAULT_CATEGORY_ID","179175"),
                                                    price=price, quantity=3)
                            publish_offer(token, offerId=offer_id)
                            done += 1
                        st.success(f"Created {done} draft offers. Check your eBay Seller Hub.")
                    except Exception as e:
                        st.error(f"Posting failed: {e}")
else:
    st.info("Choose auto-discover or paste URLs, then click **Run scan**.")
