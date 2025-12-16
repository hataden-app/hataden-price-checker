from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import os
from dotenv import load_dotenv
from pathlib import Path
from urllib.parse import quote

load_dotenv()

RAKUTEN_APP_ID = os.getenv("RAKUTEN_APP_ID")
YAHOO_APP_ID = os.getenv("YAHOO_APP_ID")
RAKUTEN_AF_ID = os.getenv("RAKUTEN_AF_ID")  # 例: 4e77dab6.420a772f.4e77dab7.6b41839e

VC_SID = os.getenv("VC_SID")
VC_PID = os.getenv("VC_PID")

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI()

@app.get("/debug/env")
def debug_env():
    return {
        "VC_SID_set": bool(VC_SID),
        "VC_PID_set": bool(VC_PID),
        "RAKUTEN_APP_ID_set": bool(RAKUTEN_APP_ID),
        "YAHOO_APP_ID_set": bool(YAHOO_APP_ID),
        "RAKUTEN_AF_ID_set": bool(RAKUTEN_AF_ID),
        "RAKUTEN_AF_ID_head": (RAKUTEN_AF_ID[:8] if RAKUTEN_AF_ID else None),
    }

@app.get("/", response_class=HTMLResponse)
def read_root():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.get("/about", response_class=HTMLResponse)
def about():
    html_path = BASE_DIR / "templates" / "about.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

def normalize_price(p):
    try:
        if p is None:
            return 10**18
        if isinstance(p, (int, float)):
            return int(p)
        s = str(p).replace(",", "").replace("円", "").strip()
        return int(float(s))
    except Exception:
        return 10**18


# =====================
# ✅ 楽天：成果リンク（affiliateUrl）を優先して使う
# =====================
def make_rakuten_affiliate_url_fallback(item_url: str) -> str:
    """
    念のためのフォールバック（基本はAPIが返す affiliateUrl を使う）
    hb.afl の形で作る版。動かなければ affiliateUrl を必ず使う方針でOK。
    """
    if not item_url or not RAKUTEN_AF_ID:
        return item_url

    pc = quote(item_url, safe="")
    # モバイル(m)はpcと同じでOK（楽天側で適切にリダイレクトされることが多い）
    m = pc

    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AF_ID}/?pc={pc}&m={m}"


def search_rakuten(keyword: str, hits: int = 10):
    url = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"

    params = {
        "format": "json",
        "applicationId": RAKUTEN_APP_ID,
        "keyword": keyword,
        "hits": hits,
        # ★これが重要：アフィIDを渡すと affiliateUrl が返ってくる
        "affiliateId": RAKUTEN_AF_ID,
    }

    res = requests.get(url, params=params, timeout=20)
    data = res.json()

    items = []
    for item in data.get("Items", []):
        i = item["Item"]

        # ✅ 正式な成果リンク（これを使う）
        aff_url = i.get("affiliateUrl") or make_rakuten_affiliate_url_fallback(i.get("itemUrl"))

        items.append(
            {
                "source": "rakuten",
                "name": i.get("itemName"),
                "price": i.get("itemPrice"),
                "url": aff_url,
                "shop": i.get("shopName"),
                "image": i["mediumImageUrls"][0]["imageUrl"] if i.get("mediumImageUrls") else None,
            }
        )
    return items


# =====================
# Yahoo：ValueCommerce成果リンク化
# =====================
def make_valuecommerce_affiliate_url(original_url: str) -> str:
    if not original_url:
        return original_url
    if not (VC_SID and VC_PID):
        return original_url

    encoded = quote(original_url, safe="")
    return (
        "https://ck.jp.ap.valuecommerce.com/servlet/referral"
        f"?sid={VC_SID}&pid={VC_PID}&vc_url={encoded}"
    )

def search_yahoo(keyword: str, hits: int = 10):
    url = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
    params = {"appid": YAHOO_APP_ID, "query": keyword, "results": hits}

    res = requests.get(url, params=params, timeout=20)
    data = res.json()

    items = []
    for hit in data.get("hits", []):
        price = hit.get("price")
        if price is None:
            continue

        url_item = hit.get("url")

        image = None
        if "image" in hit and isinstance(hit["image"], dict):
            image = hit["image"].get("medium") or hit["image"].get("small")

        seller = None
        if "seller" in hit and isinstance(hit["seller"], dict):
            seller = hit["seller"].get("name")

        items.append(
            {
                "source": "yahoo",
                "name": hit.get("name"),
                "price": price,
                "url": make_valuecommerce_affiliate_url(url_item),
                "shop": seller or "Yahoo!ショッピング",
                "image": image,
            }
        )
    return items


@app.get("/search")
def search_items(keyword: str, sources: str = "rakuten,yahoo"):
    source_list = [s.strip() for s in sources.split(",")]

    all_items = []
    if "rakuten" in source_list:
        all_items += search_rakuten(keyword, hits=10)
    if "yahoo" in source_list:
        all_items += search_yahoo(keyword, hits=10)

    norm_prices = [normalize_price(i.get("price")) for i in all_items]
    min_price = min(norm_prices) if norm_prices else None

    for item in all_items:
        item["is_cheapest"] = (
            min_price is not None
            and normalize_price(item.get("price")) == min_price
        )

    all_items.sort(key=lambda x: normalize_price(x.get("price")))

    return {
        "keyword": keyword,
        "sources": source_list,
        "count": len(all_items),
        "items": all_items,
    }
