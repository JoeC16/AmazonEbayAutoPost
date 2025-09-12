
"""
ebay_api.py
Minimal eBay Sell API helper for creating draft listings (offers) using OAuth refresh token.
Designed for compliant sourcing (your stock/wholesale/3PL), not retail-to-retail dropshipping.
"""
import os, time, json, base64, requests
from typing import List, Optional, Dict

EBAY_OAUTH_TOKEN_URL_PROD = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_OAUTH_TOKEN_URL_SANDBOX = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

SELL_INVENTORY_BASE_PROD = "https://api.ebay.com/sell/inventory/v1"
SELL_INVENTORY_BASE_SANDBOX = "https://api.sandbox.ebay.com/sell/inventory/v1"
SELL_OFFER_BASE_PROD = "https://api.ebay.com/sell/offer/v1"
SELL_OFFER_BASE_SANDBOX = "https://api.sandbox.ebay.com/sell/offer/v1"

def _env(name: str, default: Optional[str]=None) -> Optional[str]:
    return os.environ.get(name, default)

def _token_endpoint():
    return EBAY_OAUTH_TOKEN_URL_SANDBOX if _env("EBAY_ENV","PROD").upper()!="PROD" else EBAY_OAUTH_TOKEN_URL_PROD

def _inventory_base():
    return SELL_INVENTORY_BASE_SANDBOX if _env("EBAY_ENV","PROD").upper()!="PROD" else SELL_INVENTORY_BASE_PROD

def _offer_base():
    return SELL_OFFER_BASE_SANDBOX if _env("EBAY_ENV","PROD").upper()!="PROD" else SELL_OFFER_BASE_PROD

def get_access_token_from_refresh() -> str:
    cid = _env("EBAY_CLIENT_ID")
    sec = _env("EBAY_CLIENT_SECRET")
    rtoken = _env("EBAY_REFRESH_TOKEN")
    if not cid or not sec or not rtoken:
        raise RuntimeError("Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET / EBAY_REFRESH_TOKEN")
    import base64, requests
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type":"application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rtoken,
        "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.offer"
    }
    resp = requests.post(_token_endpoint(), headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]

def create_or_update_inventory_item(access_token: str, sku: str, title: str, price: float, currency: str, quantity: int,
                                    imageUrls: List[str], description: str, brand: str="Generic") -> None:
    url = _inventory_base() + f"/inventory_item/{sku}"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type":"application/json"}
    body = {
        "availability": {"shipToLocationAvailability": {"quantity": quantity}},
        "product": {"title": title[:80], "description": description[:4000], "brand": brand, "imageUrls": imageUrls},
        "condition": "NEW",
        "packageWeightAndSize": {"dimensions": {"unit": "CENTIMETER", "length": "10", "width": "10", "height": "10"}, "weight": {"value": "0.5", "unit": "KILOGRAM"}},
        "price": {"value": f"{price:.2f}", "currency": currency}
    }
    resp = requests.put(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()

def create_offer(access_token: str, sku: str, marketplaceId: str, categoryId: str, price: float, quantity: int) -> str:
    url = _offer_base() + "/offer"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type":"application/json"}
    body = {
        "sku": sku,
        "marketplaceId": marketplaceId,
        "format": "FIXED_PRICE",
        "availableQuantity": quantity,
        "categoryId": categoryId,
        "pricingSummary": {"price": {"value": f"{price:.2f}", "currency": "GBP"}},
        "listingPolicies": {
            "fulfillmentPolicyId": os.environ.get("EBAY_FULFILLMENT_POLICY_ID"),
            "paymentPolicyId": os.environ.get("EBAY_PAYMENT_POLICY_ID"),
            "returnPolicyId": os.environ.get("EBAY_RETURN_POLICY_ID"),
        }
    }
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()["offerId"]

def publish_offer(access_token: str, offerId: str) -> Dict:
    url = _offer_base() + f"/offer/{offerId}/publish"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type":"application/json"}
    resp = requests.post(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()
