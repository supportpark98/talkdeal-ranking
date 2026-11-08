"""카카오 톡딜 출산/유아동 실시간 랭킹 수집기.

톡딜 랭킹 페이지가 내부적으로 쓰는 JSON API를 호출해 상위 상품을 저장한다.
외부 패키지 없이 파이썬 표준 라이브러리만 사용한다.

사용법: python scripts/collect.py [--size 100] [--out data]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

API = (
    "https://store.kakao.com/a/f-s/ranking/product-sale-ranking"
    "?page=0&rankingTabType=contProduct&categoryType=CHILD"
    "&periodType=HOURLY&size={size}&displayPlaceType=RANKING_TAB"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://store.kakao.com/home/best?tab=contProduct&groupId=6&period=HOURLY",
}
KST = timezone(timedelta(hours=9))


def fetch(size, retries=3):
    url = API.format(size=size) + f"&_={int(time.time() * 1000)}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.load(resp)
            if not body.get("result"):
                raise RuntimeError(f"API returned result=false: {str(body)[:300]}")
            return body["data"]
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"수집 실패: {last_err}")


def pick(p):
    """화면의 표시값과 같은 필드만 골라낸다.

    톡딜가 = groupDiscountedPrice, 할인율 = groupDiscountRate,
    주문중 = groupDiscountUserCount, 브랜드 = storeName.
    """
    on_deal = p.get("groupDiscountStatus") == "ON_SALE"
    return {
        "rank": p.get("rank"),
        "productId": p.get("productId"),
        "name": p.get("productName"),
        "brand": p.get("storeName"),
        "price": p.get("groupDiscountedPrice") if on_deal else p.get("discountedPrice"),
        "originalPrice": p.get("originalPrice"),
        "discountRate": p.get("groupDiscountRate") if on_deal else p.get("discountRate"),
        "ordering": p.get("groupDiscountUserCount"),
        "totalSaleCount": p.get("totalSaleCount"),
        "reviewCount": p.get("reviewCount"),
        "category": p.get("categoryName"),
        "image": p.get("productImage"),
        "url": "https://store.kakao.com" + p["linkPath"].split("?")[0] if p.get("linkPath") else None,
        "dealEnd": (p.get("groupDiscountPeriod") or {}).get("to"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    data = fetch(args.size)
    now = datetime.now(KST)
    snapshot = {
        "collectedAt": now.isoformat(timespec="seconds"),
        "aggregatedAt": data.get("aggregatedAt"),  # 카카오 집계 기준 시각 (YYYYMMDDHHMMSS)
        "products": [pick(p) for p in data.get("products", [])],
    }
    if not snapshot["products"]:
        sys.exit("상품이 0개입니다. API 응답 형식이 바뀌었을 수 있어요.")

    snap_dir = os.path.join(args.out, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    name = now.strftime("%Y%m%d_%H%M") + ".json"
    with open(os.path.join(snap_dir, name), "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build import rebuild

    rebuild(args.out, [now.strftime("%Y-%m")])
    print(f"저장: {name} ({len(snapshot['products'])}개, 집계 {snapshot['aggregatedAt']})")


if __name__ == "__main__":
    main()
