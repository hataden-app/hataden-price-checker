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

# （PWA用 static 配信。すでに static/ を作っているなら有効）
# もし static フォルダが無いなら作るか、この2行はコメントアウトでもOKです。
app.mount("/static", StaticFiles(directory="static"), name="static")


def normalize_price(price):
    """
    price を安全に整数化する。
    変換できない/欠損は大きな値にして末尾へ回す。
    """
    try:
        if price is None:
            return 10**12
        if isinstance(price, str):
            price = price.replace(",", "").replace("円", "").strip()
        return int(price)
    except Exception:
        return 10**12


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
                "price": i["itemPrice"],  # 楽天は数値っぽいが念のため normalize_price で扱う
                "url": i["itemUrl"],
                "shop": i["shopName"],
                "image": i["mediumImageUrls"][0]["imageUrl"]
                if i.get("mediumImageUrls")
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
    for hit in data.get("hits", []):
        price = hit.get("price")
        name = hit.get("name")
        url_item = hit.get("url")

        image = None
        if isinstance(hit.get("image"), dict):
            image = hit["image"].get("medium") or hit["image"].get("small")

        seller = None
        if isinstance(hit.get("seller"), dict):
            seller = hit["seller"].get("name")

        # price が取れないものはスキップ（今まで通り）
        if price is None:
            continue

        items.append(
            {
                "source": "yahoo",
                "name": name,
                "price": price,  # Yahooは数値だけど念のため normalize_price で扱う
                "url": url_item,
                "shop": seller or "Yahoo!ショッピング",
                "image": image,
            }
        )
    return items


from typing import Optional

@app.get("/search")
def search_items(keyword: str, sources: Optional[str] = None):
    """
    楽天＋Yahooで商品検索して、共通フォーマットで返す。
    sources で絞り込み可能:
      - sources=rakuten
      - sources=yahoo
      - sources=rakuten,yahoo
      - sources=rakuten,yahoo,amazon（将来用）
    """
    rakuten_items = search_rakuten(keyword, hits=10)
    yahoo_items = search_yahoo(keyword, hits=10)

    all_items = rakuten_items + yahoo_items

    # --- 追加：sources 指定があれば絞り込み ---
    if sources:
        allowed = {s.strip().lower() for s in sources.split(",") if s.strip()}
        all_items = [item for item in all_items if item.get("source") in allowed]

    # --- 最安値（正規化した価格）を計算 ---
    prices = [normalize_price(item.get("price")) for item in all_items]
    min_price = min(prices) if prices else None

    # --- 最安フラグ付与 ---
    for item in all_items:
        item["is_cheapest"] = (
            min_price is not None and normalize_price(item.get("price")) == min_price
        )

    # --- 安い順にソート（全体） ---
    all_items.sort(key=lambda x: normalize_price(x.get("price")))

    return {
        "keyword": keyword,
        "sources": sorted(list({i.get("source") for i in all_items if i.get("source")})),
        "count": len(all_items),
        "items": all_items,
    }
