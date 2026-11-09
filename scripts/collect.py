"""카카오 톡딜 일간(최근 24시간) 랭킹 수집기 (여러 카테고리).

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
    "&periodType={period}&size={size}&displayPlaceType=RANKING_TAB"
)
# 대시보드 드롭다운 순서. groupId는 톡딜 랭킹 페이지 주소의 groupId 값.
CATEGORIES = [
    {"key": "ALL", "name": "전체", "groupId": "all"},
    {"key": "CHILD", "name": "출산/유아동", "groupId": "6"},
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


def fetch(cat, size, retries=3, period="DAILY"):
    url = API.format(cat=cat, size=size, period=period) + f"&_={int(time.time() * 1000)}"
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


# 랭킹 API는 일부 톡딜 상품의 최대혜택가(maxDiscountedPrice)를 빼고 보낸다 (랭킹 집계 뒤에 켜진 혜택 등).
# 상품 페이지가 쓰는 최대혜택가 API로 비어 있는 값만 채운다. 한 번에 20개까지.
MAX_DISCOUNT_API = "https://store.kakao.com/a/discounts/api/max-discount?"


def fetch_max_discount(ids):
    out = {}
    for i in range(0, len(ids), 20):
        chunk = ids[i:i + 20]
        url = MAX_DISCOUNT_API + "&".join(f"productIds={x}" for x in chunk) + f"&_={int(time.time() * 1000)}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        for pr in (body.get("data") or {}).get("prices", []):
            if pr.get("maxDiscountPrice") is not None:
                out[pr.get("productId")] = pr["maxDiscountPrice"]
    return out


def fill_max_benefit(rows, cache):
    """톡딜 상품 중 최대혜택가가 빠진 행을 채운다. 실패해도 수집은 계속한다. cache는 카테고리 사이에서 공유."""
    need = [r["productId"] for r in rows
            if r.get("ordering") is not None and r.get("maxBenefitPrice") is None and r["productId"] not in cache]
    if need:
        try:
            cache.update(fetch_max_discount(need))
        except Exception as e:  # noqa: BLE001
            print(f"::warning::최대혜택가 보충 실패: {e}")
    n = 0
    for r in rows:
        if r.get("ordering") is not None and r.get("maxBenefitPrice") is None and r["productId"] in cache:
            r["maxBenefitPrice"] = cache[r["productId"]]
            n += 1
    return n


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
    times = []
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
            # 대시보드 기간 선택지에 실제로 있는 수집 시점만 보여주기 위한 목록
            times = [s["t"] for m in months for s in read_json(os.path.join(d, m + ".json"), {})["snaps"]]
            count = len(times)
    pdir = os.path.join(out, "products")
    pmonths = sorted(n[:-5] for n in os.listdir(pdir) if n.endswith(".json")) if os.path.isdir(pdir) else []
    write_json(os.path.join(out, "index.json"),
               {"categories": cats, "productMonths": pmonths, "first": first, "last": last, "count": count, "times": times})


# 정해진 수집 시각(9·16·18·23시 50분, 백업은 20분 뒤). 각 시각의 40분 ~ 다음 시 40분 사이 실행만 그 슬롯으로 저장한다.
# GitHub 예약 실행이 몇 시간씩 늦게 도는 경우가 있어서, 창 밖에서 돈 실행은 저장하지 않는다.
SLOT_HOURS = (9, 16, 18, 23)


def slot_of(dt):
    """KST 시각 -> (날짜 'YYYY-MM-DD', 슬롯 시) 또는 None. 0시대 실행은 전날 23시로 친다."""
    dt = dt.astimezone(KST)
    for h in SLOT_HOURS:
        start = dt.replace(hour=h, minute=40, second=0, microsecond=0)
        if h == 23 and dt.hour == 0:
            start -= timedelta(days=1)
        if start <= dt < start + timedelta(hours=1):
            return (start.strftime("%Y-%m-%d"), h)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--out", default="data")
    ap.add_argument("--cat", action="append", help="특정 카테고리만 (예: CHILD)")
    # 임시: 갱신 시점 테스트용으로 실시간(HOURLY) 전체 랭킹도 data/test_hourly/에 따로 저장 (대시보드에는 안 나옴)
    ap.add_argument("--hourly-test", action="store_true")
    # 정기 수집용: 수집 시각 창 밖이거나, 그 슬롯이 이미 저장돼 있으면(본 수집이 끝난 뒤의 백업 등) 저장하지 않는다
    ap.add_argument("--skip-if-saved", action="store_true")
    args = ap.parse_args()

    targets = [c for c in CATEGORIES if not args.cat or c["key"] in args.cat]
    if args.skip_if_saved:
        now = datetime.now(KST)
        slot = slot_of(now)
        if not slot:
            print(f"{now:%m/%d %H:%M}은 정해진 수집 시각이 아니라 건너뜀 (늦게 시작된 예약 실행)")
            return
        d = os.path.join(args.out, "monthly", targets[0]["key"])
        months = sorted(n for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []
        snaps = read_json(os.path.join(d, months[-1]), {}).get("snaps", []) if months else []
        if any(slot_of(datetime.fromisoformat(x["t"])) == slot for x in snaps[-3:]):
            print(f"{slot[0]} {slot[1]}시 수집은 이미 저장되어 있어 건너뜀")
            return
    t_iso = datetime.now(KST).isoformat(timespec="seconds")
    failed = []
    mx_cache = {}
    for c in targets:
        try:
            data = fetch(c["key"], args.size)
            picked = [pick(p) for p in data.get("products", [])]
            if not picked:
                raise RuntimeError("상품이 0개 (API 응답 형식이 바뀌었을 수 있음)")
            rows = [r for r, _ in picked]
            metas = {str(r["productId"]): m for r, m in picked}
            filled = fill_max_benefit(rows, mx_cache)
            save_snapshot(args.out, c["key"], t_iso, data.get("aggregatedAt"), rows, metas)
            print(f"{c['name']}: {len(rows)}개 (집계 {data.get('aggregatedAt')}, 최대혜택가 보충 {filled}개)")
        except Exception as e:  # noqa: BLE001
            failed.append(c["key"])
            print(f"::warning::{c['name']} 실패: {e}")
    rebuild_index(args.out)
    if args.hourly_test:
        try:
            data = fetch("ALL", args.size, period="HOURLY")
            picked = [pick(p) for p in data.get("products", [])]
            save_snapshot(os.path.join(args.out, "test_hourly"), "ALL", t_iso, data.get("aggregatedAt"),
                          [r for r, _ in picked], {str(r["productId"]): m for r, m in picked})
            print(f"실시간 전체(테스트): {len(picked)}개 (집계 {data.get('aggregatedAt')})")
        except Exception as e:  # noqa: BLE001
            print(f"::warning::실시간 전체(테스트) 실패: {e}")
    if len(failed) == len(targets):
        sys.exit("모든 카테고리 수집 실패")


if __name__ == "__main__":
    main()
