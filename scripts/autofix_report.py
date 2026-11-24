"""자동 분석(autofix.yml) 결과를 PR 본문·메일로 만든다.

Claude가 autofix_out/result.json 에 남긴 판단(verdict, title, cause, action, verified)을 읽는다.
파일이 없거나 깨졌으면 "분석이 결론을 못 냈다"는 메일을 보낸다.

사용법:
  python scripts/autofix_report.py pr-body --dir autofix_out --run-id 123
  python scripts/autofix_report.py mail --dir autofix_out --run-id 123 [--pr-url URL] [--skip-reason 글]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_health import DASHBOARD, send  # noqa: E402

VERDICT_KO = {
    "transient": "일시적인 문제 (코드 수정 필요 없음)",
    "fix": "코드 수정이 필요한 문제",
    "needs_human": "사람의 확인이 필요한 문제",
}


def load_result(d):
    try:
        with open(os.path.join(d, "result.json"), encoding="utf-8") as f:
            r = json.load(f)
        return r if isinstance(r, dict) and r.get("verdict") in VERDICT_KO else None
    except (OSError, ValueError):
        return None


def run_link(run_id):
    repo = os.environ.get("GITHUB_REPOSITORY", "supportpark98/talkdeal-ranking")
    return f"https://github.com/{repo}/actions/runs/{run_id}" if run_id else ""


def analysis_link():
    if os.environ.get("GITHUB_RUN_ID"):
        return run_link(os.environ["GITHUB_RUN_ID"])
    return ""


def pr_body(d, run_id):
    r = load_result(d) or {}
    lines = [
        "수집 실패를 Claude가 자동으로 분석해서 만든 수정안입니다. 내용을 확인한 뒤 직접 합쳐(merge) 주세요.",
        "",
        "## 원인",
        r.get("cause", "(설명 없음)"),
        "",
        "## 수정 내용",
        r.get("action", "(설명 없음)"),
    ]
    if r.get("verified"):
        lines += ["", "## 확인 결과", r["verified"]]
    lines += ["", "## 참고", f"- 실패한 수집 실행: {run_link(run_id)}"]
    if analysis_link():
        lines.append(f"- 자동 분석 실행 기록: {analysis_link()}")
    lines += ["", "합치면 다음 예약 수집부터 바뀐 코드로 수집합니다. 맞지 않으면 PR을 닫으면 됩니다."]
    return "\n".join(lines)


def mail(d, run_id, pr_url, skip_reason):
    if skip_reason:
        subject = "[톡딜 랭킹] 자동 분석 건너뜀"
        body = [skip_reason]
    else:
        r = load_result(d)
        if not r:
            subject = "[톡딜 랭킹] 자동 분석: 결론을 내지 못했습니다"
            body = ["Claude가 실패 원인을 분석했지만 결론 파일을 남기지 못했습니다.",
                    "실행 기록을 직접 확인해 주세요."]
        else:
            v = r["verdict"]
            subject = f"[톡딜 랭킹] 자동 분석: {r.get('title') or VERDICT_KO[v]}"
            body = [f"판단: {VERDICT_KO[v]}", "", "원인:", r.get("cause", ""), "",
                    "조치:" if v != "needs_human" else "해야 할 일:", r.get("action", "")]
            if r.get("verified"):
                body += ["", "확인 결과:", r["verified"]]
            if v == "fix":
                if pr_url:
                    body += ["", f"수정 PR: {pr_url}",
                             "PR 내용을 확인하고 'Merge pull request'를 누르면 적용됩니다. 맞지 않으면 PR을 닫아 주세요."]
                else:
                    body += ["", "수정안은 만들었지만 PR을 여는 데 실패했습니다. 실행 기록을 확인해 주세요."]
            elif v == "transient":
                body += ["", "다음 예약 수집에서 자동으로 다시 시도하므로 따로 하실 일은 없습니다."]
    body += ["", f"대시보드: {DASHBOARD}"]
    if run_id:
        body.append(f"실패한 수집 실행: {run_link(run_id)}")
    if analysis_link():
        body.append(f"자동 분석 실행 기록: {analysis_link()}")
    text = "\n".join(body)
    print(subject + "\n" + text)
    send(subject, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["pr-body", "mail"])
    ap.add_argument("--dir", default="autofix_out")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--pr-url", default="")
    ap.add_argument("--skip-reason", default="")
    a = ap.parse_args()
    if a.mode == "pr-body":
        print(pr_body(a.dir, a.run_id))
    else:
        mail(a.dir, a.run_id, a.pr_url, a.skip_reason)


if __name__ == "__main__":
    main()
