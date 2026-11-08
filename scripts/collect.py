"""카카오 톡딜 실시간 랭킹 수집기 (여러 카테고리).

톡딜 랭킹 페이지가 내부적으로 쓰는 JSON API를 호출해 카테고리별 상위 상품을 저장한다.
외부 패키지 없이 파이썬 표준 라이브러리만 사용한다.

저장 구조 (장기 보관을 위해 압축 형식으로 저장):
- data/monthly/<카테고리>/YYYY-MM.json : 그 달의 수집 시점별 순위표
- data/products/YYYY-MM.json          : 그 달에 등장한 상품 정보 (이름, 브랜드, 링크 등)
- data/index.json                     : 카테고리 목록, 카테고리별 월 목록, 처음/마지막 수집 시각

사용법: python scripts/collect.py [--size 100] [--out data] [--cat CHILD ...]
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
    "?page=0&rankingTabType=contProduct&categoryType={cat}"
    "&periodType=HOURLY&size={size}&displayPlaceType=RANKING_TAB"
)
# 대시보드 드롭다운 순서. groupId는 톡딜 랭킹 페이지 주소의 groupId 값.
CATEGORIES = [
    {"key": "CHILD", "name": "출산/유아동", "groupId": "6"},
    {"key": "ALL", "name": "전체", "groupId": "all"},
    {"key": "LIVE", "name": "라이브", "groupId": "1"},
    {"key": "LIFE", "name": "생활", "groupId": "9"},
    {"key": "BEAUTY", "name": "뷰티", "groupId": "2"},
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://store.kakao.com/home/best?tab=contProduct",
}
KST = timezone(timedelta(hours=9))

# monthly 파일 rows의 열 순서
COLS = [
    "rank", "productId", "price", "discountRate", "ordering",
    "originalPrice", "maxBenefitPrice", "totalSaleCount", "reviewCount", "satisfaction", "label",
    "liveStartAt",
]


def fetch(cat, size, retries=3):
    url = API.format(cat=cat, size=size) + f"&_={int(time.time() * 1000)}"
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
    raise RuntimeError(f"{cat} 수집 실패: {last_err}")


def pick(p):
    """화면의 표시값과 같은 필드만 골라 (행, 상품정보)로 나눈다.

    톡딜 진행 중이면 톡딜가 = groupDiscountedPrice, 할인율 = groupDiscountRate,
    주문중 = groupDiscountUserCount. 정상가 = originalPrice, 최대혜택가 = maxDiscountedPrice. 톡딜이 아닌 일반 상품은 주문중 수량이 없다(None).
    """
    on_deal = p.get("groupDiscountStatus") == "ON_SALE"
    rate = p.get("groupDiscountRate") if on_deal else p.get("discountRate")
    row = {
        "rank": p.get("rank"),
        "productId": p.get("productId"),
        "price": p.get("groupDiscountedPrice") if on_deal else p.get("discountedPrice"),
        "discountRate": round(rate) if rate is not None else None,
        "ordering": p.get("groupDiscountUserCount") if on_deal else None,
        "originalPrice": p.get("originalPrice"),
        "maxBenefitPrice": p.get("maxDiscountedPrice"),
        "totalSaleCount": p.get("totalSaleCount"),
        "reviewCount": p.get("reviewCount"),
        "satisfaction": p.get("productPositivePercentage"),
        "label": p.get("label"),
        # 라이브 방송 시작 시각 (YYYYMMDDHHMMSS). 라이브가 없으면 None
        "liveStartAt": p.get("liveStartAt"),
    }
    meta = {
        "name": p.get("productName"),
        "brand": p.get("storeName"),
        "category": p.get("categoryName"),
        "url": "https://store.kakao.com" + p["linkPath"].split("?")[0] if p.get("linkPath") else None,
        "image": p.get("productImage"),
        "brandStore": bool(p.get("isBrandTalkStore")),
        "freeDelivery": bool(p.get("freeDelivery")),
        # 톡딜 기간 (YYYYMMDDHHMMSS)
        "dealStart": (p.get("groupDiscountPeriod") or {}).get("from") if on_deal else None,
        "dealEnd": (p.get("groupDiscountPeriod") or {}).get("to") if on_deal else None,
    }
    return row, meta


def read_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def save_snapshot(out, cat, t_iso, agg, rows, metas):
    """한 카테고리의 한 시점을 월별 파일에 덧붙이고 상품 정보를 갱신한다."""
    month = t_iso[:7]
    mpath = os.path.join(out, "monthly", cat, f"{month}.json")
    monthly = read_json(mpath, {"cols": COLS, "snaps": []})
    if monthly.get("cols") != COLS:
        raise RuntimeError(f"{mpath}의 열 구성이 다릅니다")
    monthly["snaps"] = [s for s in monthly["snaps"] if s["t"] != t_iso]
    monthly["snaps"].append({"t": t_iso, "agg": agg, "rows": [[r.get(c) for c in COLS] for r in rows]})
    monthly["snaps"].sort(key=lambda s: s["t"])
    write_json(mpath, monthly)

    ppath = os.path.join(out, "products", f"{month}.json")
    products = read_json(ppath, {})
    products.update(metas)
    write_json(ppath, products)


def rebuild_index(out):
    cats = []
    first = last = None
    count = 0
    for c in CATEGORIES:
        d = os.path.join(out, "monthly", c["key"])
        months = sorted(n[:-5] for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []
        if not months:
            continue
        cats.append({**c, "months": months})
        f_snaps = read_json(os.path.join(d, months[0] + ".json"), {})["snaps"]
        l_snaps = read_json(os.path.join(d, months[-1] + ".json"), {})["snaps"]
        if f_snaps and (first is None or f_snaps[0]["t"] < first):
            first = f_snaps[0]["t"]
        if l_snaps and (last is None or l_snaps[-1]["t"] > last):
            last = l_snaps[-1]["t"]
        if c["key"] == CATEGORIES[0]["key"]:
            count = sum(len(read_json(os.path.join(d, m + ".json"), {})["snaps"]) for m in months)
    pdir = os.path.join(out, "products")
    pmonths = sorted(n[:-5] for n in os.listdir(pdir) if n.endswith(".json")) if os.path.isdir(pdir) else []
    write_json(os.path.join(out, "index.json"),
               {"categories": cats, "productMonths": pmonths, "first": first, "last": last, "count": count})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--out", default="data")
    ap.add_argument("--cat", action="append", help="특정 카테고리만 (예: CHILD)")
    args = ap.parse_args()

    targets = [c for c in CATEGORIES if not args.cat or c["key"] in args.cat]
    t_iso = datetime.now(KST).isoformat(timespec="seconds")
    failed = []
    for c in targets:
        try:
            data = fetch(c["key"], args.size)
            picked = [pick(p) for p in data.get("products", [])]
            if not picked:
                raise RuntimeError("상품이 0개 (API 응답 형식이 바뀌었을 수 있음)")
            rows = [r for r, _ in picked]
            metas = {str(r["productId"]): m for r, m in picked}
            save_snapshot(args.out, c["key"], t_iso, data.get("aggregatedAt"), rows, metas)
            print(f"{c['name']}: {len(rows)}개 (집계 {data.get('aggregatedAt')})")
        except Exception as e:  # noqa: BLE001
            failed.append(c["key"])
            print(f"::warning::{c['name']} 실패: {e}")
    rebuild_index(args.out)
    if len(failed) == len(targets):
        sys.exit("모든 카테고리 수집 실패")


if __name__ == "__main__":
    main()
