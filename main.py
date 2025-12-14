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

# 楽天アフィリエイトID（あなたのやつ）
RAKUTEN_AF_ID = os.getenv("RAKUTEN_AF_ID")  # ← 環境変数から読む


# ValueCommerce（Yahoo用：あなたのsid/pid）
VC_SID = os.getenv("VC_SID")  # 3759503
VC_PID = os.getenv("VC_PID")  # 892373053

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

@app.get("/debug/env")
def debug_env():
    return {
        "VC_SID_set": bool(VC_SID),
        "VC_PID_set": bool(VC_PID),
        "RAKUTEN_APP_ID_set": bool(RAKUTEN_APP_ID),
        "YAHOO_APP_ID_set": bool(YAHOO_APP_ID),
        "RAKUTEN_AF_ID_set": bool(RAKUTEN_AF_ID),  # ★追加
        "RAKUTEN_AF_ID_head": (RAKUTEN_AF_ID[:8] if RAKUTEN_AF_ID else None),  # ★任意（確認用）
    }



@app.get("/", response_class=HTMLResponse)
def read_root():
    """検索画面（index.html）を返す"""
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# =====================
# 共通：価格を安全にint化（ソート用）
# =====================
def normalize_price(p):
    """price が文字列でも数値でも int に正規化（失敗したら大きい値にして最後へ）"""
    try:
        if p is None:
            return 10**18
        if isinstance(p, (int, float)):
            return int(p)
        s = str(p)
        s = s.replace(",", "").replace("円", "").strip()
        return int(float(s))
    except Exception:
        return 10**18


# =====================
# 楽天：アフィURL生成（rafcid二重防止）
# =====================
def make_rakuten_affiliate_url(item_url: str) -> str:
    if not item_url:
        return item_url
    if not RAKUTEN_AF_ID:
        return item_url
    base_url = item_url.split("?")[0]
    return f"{base_url}?rafcid={RAKUTEN_AF_ID}"


def search_rakuten(keyword: str, hits: int = 10):
    """楽天市場APIで商品検索（アフィ対応）"""
    url = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"

    params = {
        "format": "json",
        "applicationId": RAKUTEN_APP_ID,
        "keyword": keyword,
        "hits": hits,
    }

    res = requests.get(url, params=params)
    data = res.json()

    items = []
    for item in data.get("Items", []):
        i = item["Item"]

        items.append(
            {
                "source": "rakuten",
                "name": i.get("itemName"),
                "price": i.get("itemPrice"),
                "url": make_rakuten_affiliate_url(i.get("itemUrl")),
                "shop": i.get("shopName"),
                "image": i["mediumImageUrls"][0]["imageUrl"] if i.get("mediumImageUrls") else None,
            }
        )
    return items


# =====================
# Yahoo：ValueCommerce成果リンク化（直URLでもアフィになる）
# =====================
def make_valuecommerce_affiliate_url(original_url: str) -> str:
    if not original_url:
        return original_url
    if not (VC_SID and VC_PID):
        return original_url  # 未設定なら元URLのまま

    encoded = quote(original_url, safe="")
    return (
        "https://ck.jp.ap.valuecommerce.com/servlet/referral"
        f"?sid={VC_SID}&pid={VC_PID}&vc_url={encoded}"
    )


def search_yahoo(keyword: str, hits: int = 10):
    """YahooショッピングAPIで商品検索（v3）＋VC成果リンク化"""
    url = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"

    params = {
        "appid": YAHOO_APP_ID,
        "query": keyword,
        "results": hits,
    }

    res = requests.get(url, params=params)
    data = res.json()

    items = []
    for hit in data.get("hits", []):
        price = hit.get("price")
        if price is None:
            continue

        name = hit.get("name")
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
                "name": name,
                "price": price,
                # ★ここが今回の本丸：Yahooリンクを必ずVC成果リンクに包む
                "url": make_valuecommerce_affiliate_url(url_item),
                "shop": seller or "Yahoo!ショッピング",
                "image": image,
            }
        )
    return items


@app.get("/search")
def search_items(keyword: str):
    """楽天＋Yahooで検索して、最安判定＋安い順ソートして返す"""
    rakuten_items = search_rakuten(keyword, hits=10)
    yahoo_items = search_yahoo(keyword, hits=10)

    all_items = rakuten_items + yahoo_items

    # 最安値判定（価格を正規化して比較）
    norm_prices = [normalize_price(i.get("price")) for i in all_items]
    min_price = min(norm_prices) if norm_prices else None

    for item in all_items:
        item["is_cheapest"] = (
            min_price is not None and normalize_price(item.get("price")) == min_price
        )

    # 全体を価格昇順にソート
    all_items.sort(key=lambda x: normalize_price(x.get("price")))

    return {
        "keyword": keyword,
        "sources": sorted(list({i.get("source") for i in all_items if i.get("source")})),
        "count": len(all_items),
        "items": all_items,
    }
