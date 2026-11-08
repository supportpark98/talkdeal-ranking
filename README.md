# 톡딜 출산/유아동 랭킹 트래커

카카오 톡딜 [출산/유아동 실시간 랭킹](https://store.kakao.com/home/best?tab=contProduct&groupId=6&period=HOURLY) 상위 100개를
하루 3번(한국 시간 10시, 18시, 24시) 수집해서 대시보드로 보여줍니다.

## 구성

| 경로 | 설명 |
| --- | --- |
| `scripts/collect.py` | 랭킹 API를 호출해 스냅샷을 저장 (파이썬 표준 라이브러리만 사용) |
| `.github/workflows/collect.yml` | 예약 실행 후 `data/`에 커밋 |
| `index.html` | 대시보드 (GitHub Pages로 공개) |
| `scripts/build.py` | 스냅샷으로 대시보드용 요약 파일 생성 |
| `data/snapshots/*.json` | 수집 시점별 랭킹 원본 (보관용) |
| `data/monthly/YYYY-MM.json` | 월별 순위/가격/주문중 요약 (대시보드가 기간에 맞는 달만 불러옴) |
| `data/products.json` | 상품 정보 (이름, 브랜드, 링크, 이미지) |
| `data/index.json` | 월 목록과 처음/마지막 수집 시각 |

## 수집 항목

순위, 상품명, 브랜드(스토어명), 톡딜가, 정가, 할인율, 주문중 수량, 누적 판매량, 리뷰 수, 카테고리, 이미지, 상품 링크

## 직접 실행

```bash
python scripts/collect.py --size 100 --out data
python -m http.server  # http://localhost:8000 에서 대시보드 확인
```

Actions 탭의 "톡딜 랭킹 수집" 워크플로에서 **Run workflow**로 언제든 수동 수집할 수 있어요.
GitHub 예약 실행은 몇 분에서 수십 분 늦게 시작될 수 있습니다.
