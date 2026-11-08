"""수집된 스냅샷(data/snapshots)으로 대시보드용 요약 파일을 만든다.

- data/monthly/YYYY-MM.json : 그 달의 모든 수집 시점과 순위표(압축 형식)
- data/products.json        : 상품 정보(이름, 브랜드, 링크 등) 최신값
- data/index.json           : 월 목록, 처음/마지막 수집 시각

사용법: python scripts/build.py [--out data] [--month 2026-11]
"""
import argparse
import json
import os

# monthly 파일의 rows 열 순서
COLS = ["rank", "productId", "price", "discountRate", "ordering"]


def load_snapshot(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def month_of(name):  # 20261108_1659.json -> 2026-11
    return f"{name[0:4]}-{name[4:6]}"


def rebuild(out="data", months=None):
    snap_dir = os.path.join(out, "snapshots")
    names = sorted(n for n in os.listdir(snap_dir) if n.endswith(".json"))
    all_months = sorted({month_of(n) for n in names})
    targets = all_months if months is None else [m for m in months if m in all_months]

    prod_path = os.path.join(out, "products.json")
    products = {}
    if os.path.exists(prod_path) and months is not None:
        with open(prod_path, encoding="utf-8") as f:
            products = json.load(f)

    os.makedirs(os.path.join(out, "monthly"), exist_ok=True)
    for m in targets:
        snaps = []
        for n in (n for n in names if month_of(n) == m):
            s = load_snapshot(os.path.join(snap_dir, n))
            rows = []
            for p in s["products"]:
                rows.append([p.get(c) if c != "discountRate" or p.get(c) is None else round(p[c]) for c in COLS])
                products[str(p["productId"])] = {
                    "name": p.get("name"), "brand": p.get("brand"), "category": p.get("category"),
                    "url": p.get("url"), "image": p.get("image"), "originalPrice": p.get("originalPrice"),
                }
            snaps.append({"t": s["collectedAt"], "agg": s.get("aggregatedAt"), "rows": rows})
        with open(os.path.join(out, "monthly", f"{m}.json"), "w", encoding="utf-8") as f:
            json.dump({"cols": COLS, "snaps": snaps}, f, ensure_ascii=False, separators=(",", ":"))

    with open(prod_path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, separators=(",", ":"))

    first = load_snapshot(os.path.join(snap_dir, names[0]))["collectedAt"] if names else None
    last = load_snapshot(os.path.join(snap_dir, names[-1]))["collectedAt"] if names else None
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"months": all_months, "first": first, "last": last, "count": len(names)}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--month", action="append")
    a = ap.parse_args()
    rebuild(a.out, a.month)
