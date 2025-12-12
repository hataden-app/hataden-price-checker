from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import os
from dotenv import load_dotenv
from pathlib import Path
from fastapi.staticfiles import StaticFiles

load_dotenv()

RAKUTEN_APP_ID = os.getenv("RAKUTEN_APP_ID")
YAHOO_APP_ID = os.getenv("YAHOO_APP_ID")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")



@app.get("/", response_class=HTMLResponse)
def read_root():
    """検索画面（index.html）を返す"""
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


def search_rakuten(keyword: str, hits: int = 10):
    """楽天市場APIで商品検索"""
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
                "name": i["itemName"],
                "price": i["itemPrice"],
                "url": i["itemUrl"],
                "shop": i["shopName"],
                "image": i["mediumImageUrls"][0]["imageUrl"]
                if i["mediumImageUrls"]
                else None,
            }
        )
    return items


def search_yahoo(keyword: str, hits: int = 10):
    """YahooショッピングAPIで商品検索（v3）"""
    url = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"

    params = {
        "appid": YAHOO_APP_ID,
        "query": keyword,
        "results": hits,
    }

    res = requests.get(url, params=params)
    data = res.json()

    items = []
    # v3 のレスポンスは hits 配列の中に商品が入っている :contentReference[oaicite:1]{index=1}
    for hit in data.get("hits", []):
        # price は数値（税抜/税込は priceLabel で詳細が取れるが、ここでは price をそのまま使用）:contentReference[oaicite:2]{index=2}
        price = hit.get("price")
        name = hit.get("name")
        url_item = hit.get("url")
        image = None
        if "image" in hit and isinstance(hit["image"], dict):
            image = hit["image"].get("medium") or hit["image"].get("small")
        seller = None
        if "seller" in hit and isinstance(hit["seller"], dict):
            seller = hit["seller"].get("name")

        # price が取れないものはスキップ
        if price is None:
            continue

        items.append(
            {
                "source": "yahoo",
                "name": name,
                "price": price,
                "url": url_item,
                "shop": seller or "Yahoo!ショッピング",
                "image": image,
            }
        )
    return items


@app.get("/search")
def search_items(keyword: str):
    """
    楽天＋Yahooで商品検索して、
    共通フォーマットで結果を返す。
    """
    rakuten_items = search_rakuten(keyword, hits=10)
    yahoo_items = search_yahoo(keyword, hits=10)

    all_items = rakuten_items + yahoo_items

    # 全体から最安値を探して、その価格をマーキング
    min_price = None
    for item in all_items:
        p = item["price"]
        if isinstance(p, str):
            try:
                p = int(p)
            except ValueError:
                continue
        if min_price is None or p < min_price:
            min_price = p

    for item in all_items:
        p = item["price"]
        if isinstance(p, str):
            try:
                p = int(p)
            except ValueError:
                continue
        item["is_cheapest"] = (min_price is not None and p == min_price)

    return {
        "keyword": keyword,
        "count": len(all_items),
        "items": all_items,
    }
