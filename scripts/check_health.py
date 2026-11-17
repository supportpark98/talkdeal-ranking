"""수집 결과 검사 + 이상 시 메일 알림.

카카오가 랭킹 구조를 바꾸면 수집이 조용히 망가질 수 있어서, 아래 경우에 메일을 보낸다.
- 수집 프로그램이 오류로 멈춤 (워크플로의 수집 단계가 실패)
- 카테고리 받기 실패, 상품 0개, 또는 평소(최근 수집 중앙값)의 절반도 안 되는 상품 수
- 핵심 값(상품명, 가격, 순위)이 비어 있는 상품이 10% 이상
- 마지막 수집이 24시간 넘게 없음 (매일 따로 실행하는 health.yml에서 검사)

메일 설정 (GitHub 저장소 Settings > Secrets and variables > Actions 의 Secrets):
- MAIL_USERNAME : 보내는 Gmail 주소
- MAIL_PASSWORD : 그 Gmail의 앱 비밀번호 (16자리)
- MAIL_TO       : 받는 주소들 (쉼표로 구분). 저장소가 공개라 주소를 코드에 적지 않고 Secret에 둔다

사용법:
  python scripts/check_health.py collect --report run_report.json --log collect.log --outcome success
  python scripts/check_health.py stale
  python scripts/check_health.py test
"""
import argparse
import json
import os
import smtplib
import ssl
import statistics
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

KST = timezone(timedelta(hours=9))
DATA = "data"
DASHBOARD = "https://talkdeal-ranking.pages.dev/"

FEW_RATIO = 0.5        # 평소 상품 수의 이 비율 미만이면 '급감'
MISSING_RATIO = 0.1    # 핵심 값이 빈 상품이 이 비율 이상이면 이상
STALE_HOURS = 24       # 마지막 수집이 이보다 오래되면 이상
FIELD_NAMES = {"name": "상품명이", "price": "가격이", "rank": "순위가"}


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def run_url():
    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return None


def usual_count(cat, exclude_t):
    """그 카테고리의 최근 수집(이번 수집 제외) 8번의 상품 수 중앙값. 기록이 3번 미만이면 None."""
    d = os.path.join(DATA, "monthly", cat)
    if not os.path.isdir(d):
        return None
    counts = []
    for name in sorted((n for n in os.listdir(d) if n.endswith(".json")), reverse=True):
        snaps = (read_json(os.path.join(d, name), {}) or {}).get("snaps", [])
        for s in reversed(snaps):
            if s.get("t") != exclude_t:
                counts.append(len(s.get("rows", [])))
            if len(counts) >= 8:
                break
        if len(counts) >= 8:
            break
    return statistics.median(counts) if len(counts) >= 3 else None


def check_collect(report_path, log_path, outcome):
    problems = []
    if outcome and outcome != "success":
        tail = ""
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                tail = "".join(f.readlines()[-30:])
        except OSError:
            pass
        what = "시간 초과 등으로 중단됐습니다" if outcome == "cancelled" else "오류로 멈췄습니다"
        problems.append(f"[전체] 수집 프로그램이 {what} (결과: {outcome}).\n"
                        + (f"    마지막 실행 기록:\n" + "\n".join("      " + x for x in tail.splitlines()) if tail else ""))
    report = read_json(report_path) if report_path else None
    if not report or not report.get("saved"):
        return problems   # 건너뛴 실행(백업 등)이거나 저장 전에 멈춤 -> 위의 오류 검사만
    for key, c in report.get("categories", {}).items():
        name, count = c.get("name", key), c.get("count", 0)
        if c.get("error"):
            problems.append(f"[{name}] 수집 실패: {c['error']}")
            continue
        if count == 0:
            problems.append(f"[{name}] 상품이 0개입니다 (카카오 응답 형식이 바뀌었을 수 있음)")
            continue
        usual = usual_count(key, report.get("t"))
        if usual and count < usual * FEW_RATIO:
            problems.append(f"[{name}] 상품 수가 평소보다 크게 적습니다: 이번 {count}개, 평소 {usual:g}개")
        for field, n in (c.get("missing") or {}).items():
            if n and n >= count * MISSING_RATIO:
                problems.append(f"[{name}] {FIELD_NAMES.get(field, field + '이')} 빈 상품이 {n}개 / {count}개 "
                                f"(카카오가 항목 이름을 바꿨을 수 있음)")
    return problems


def check_stale():
    idx = read_json(os.path.join(DATA, "index.json"), {}) or {}
    last = idx.get("last")
    if not last:
        return ["[전체] 저장된 수집 기록을 찾을 수 없습니다 (data/index.json)"]
    last_dt = datetime.fromisoformat(last)
    hours = (datetime.now(KST) - last_dt).total_seconds() / 3600
    if hours > STALE_HOURS:
        return [f"[전체] {hours:.0f}시간 동안 새 데이터가 없습니다. 마지막 수집: {last_dt.astimezone(KST):%m월 %d일 %H:%M}"]
    return []


def send(subject, body):
    user, pw, to = (os.environ.get(k, "").strip() for k in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_TO"))
    if not (user and pw and to):
        print("::warning::메일 설정(MAIL_USERNAME, MAIL_PASSWORD, MAIL_TO Secret)이 없어 메일을 보내지 못했습니다")
        print(subject + "\n" + body)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"톡딜 랭킹 알림 <{user}>"
    msg["To"] = ", ".join(x.strip() for x in to.replace(";", ",").split(",") if x.strip())
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, pw.replace(" ", ""))
        s.send_message(msg)
    print(f"메일 발송 완료: {subject}")
    return True


def compose(problems, title):
    now = datetime.now(KST)
    lines = [f"{title}", f"확인 시각: {now:%Y-%m-%d %H:%M} (한국 시간)", "", "문제:"]
    lines += [f"- {p}" for p in problems]
    lines += ["", f"대시보드: {DASHBOARD}"]
    if run_url():
        lines.append(f"실행 기록: {run_url()}")
    lines += ["", "카테고리 하나만 문제면 나머지 카테고리는 정상 수집되고 있습니다.",
              "같은 문제가 고쳐질 때까지 수집할 때마다 이 메일이 옵니다."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["collect", "stale", "test"])
    ap.add_argument("--report")
    ap.add_argument("--log")
    ap.add_argument("--outcome")
    args = ap.parse_args()

    if args.mode == "test":
        body = compose(["[테스트] 이 메일은 알림 설정 확인용 테스트입니다. 실제 문제는 없습니다."],
                       "톡딜 랭킹 수집 알림 테스트")
        ok = send("[톡딜 랭킹] 알림 테스트 메일", body)
        sys.exit(0 if ok else 1)

    problems = check_collect(args.report, args.log, args.outcome) if args.mode == "collect" else check_stale()
    if not problems:
        print("이상 없음")
        return
    print("\n".join(problems))
    cats = sorted({p[1:p.index("]")] for p in problems})
    send(f"[톡딜 랭킹] 수집 이상: {', '.join(cats)}", compose(problems, "톡딜 랭킹 수집에서 이상이 발견되었습니다."))


if __name__ == "__main__":
    main()
