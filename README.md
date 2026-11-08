# 톡딜 실시간 랭킹 트래커

카카오 톡딜 실시간 랭킹(전체, 출산/유아동, 생활, 뷰티) 상위 100개를
하루 3번(한국 시간 10시, 18시, 24시) 수집해서 대시보드로 보여줍니다.

## 구성

| 경로 | 설명 |
| --- | --- |
| `scripts/collect.py` | 카테고리별 랭킹 API를 호출해 저장 (파이썬 표준 라이브러리만 사용). 카테고리 목록은 파일 안 `CATEGORIES` |
| `.github/workflows/collect.yml` | 예약 실행 후 `data/`에 커밋 |
| `index.html` | 대시보드 (GitHub Pages로 공개). `?cat=LIFE`처럼 주소로 카테고리 지정 가능 |
| `data/monthly/<카테고리>/YYYY-MM.json` | 월별 수집 시점별 순위표 (순위, 가격, 할인율, 주문중, 정가, 최대혜택가, 누적판매, 리뷰수, 만족률, 라벨) |
| `data/products/YYYY-MM.json` | 그 달에 등장한 상품 정보 (이름, 브랜드, 카테고리, 링크, 이미지, 브랜드 공식 여부 등) |
| `data/index.json` | 카테고리별 월 목록과 처음/마지막 수집 시각 |

용량: 1회 수집(4개 카테고리)이 약 25KB라 1년에 30MB 안팎입니다.

## 직접 실행

```bash
python scripts/collect.py --size 100 --out data
python -m http.server  # http://localhost:8000 에서 대시보드 확인
```

Actions 탭의 "톡딜 랭킹 수집" 워크플로에서 **Run workflow**로 언제든 수동 수집할 수 있어요.
GitHub 예약 실행은 몇 분에서 수십 분 늦게 시작될 수 있습니다.
