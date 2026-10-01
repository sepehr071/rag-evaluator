"""Seed a demo result file from uploads/sample_qa.csv without calling any LLM.

Runs the real LLMJudge pipeline (prompt building, JSON parsing, aggregation),
but replaces the OpenRouter HTTP call with canned, fictional judgments so the
dashboard can be explored and screenshotted offline. Output is clearly marked
as demo data (model = "demo (no LLM call)").

Usage:  python scripts/seed_demo_results.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENROUTER_API_KEY", "demo-no-network")
for _k in ("SECRET_KEY", "ADMIN_PASSWORD", "EXPERT_PASSWORD"):
    os.environ.setdefault(_k, "demo")

from config import Config  # noqa: E402
from evaluator import DataLoader, LLMJudge  # noqa: E402

# Fictional judge outputs, one per sample row, in the same JSON shape the real prompt asks for.
DEMO_JUDGMENTS = [
    (10, 10, 10, 10, "پاسخ دقیقاً با جواب مرجع مطابقت دارد و هیچ اطلاعات اضافه‌ای ندارد."),
    (2, 6, 9, 3, "تعداد روزهای مرخصی (۳۰ روز) با جواب مرجع (۲۶ روز) مغایرت دارد؛ پاسخ مرتبط است اما عدد نادرست ارائه شده."),
    (8, 6, 10, 9, "مراحل ثبت در سامانه و تایید سرپرست درست است، اما شرط «حداقل دو روز قبل» ذکر نشده است."),
    (5, 2, 7, 8, "پاسخ طفره‌آمیز است: مهلت ۱۴ روزه و زمان بازپرداخت را نمی‌گوید و کاربر را به واحد مالی ارجاع می‌دهد."),
    (9, 10, 10, 7, "مدت دوره آزمایشی درست است؛ جمله مربوط به «تمدید یا استخدام رسمی» در جواب مرجع نیامده و کمی فراتر از منبع است."),
    (1, 0, 2, 2, "پاسخ به سؤال ربطی ندارد: به جای گزارش فوری به فناوری اطلاعات، درباره ضمانت دستگاه صحبت می‌کند."),
    (10, 10, 10, 10, "سقف بودجه آموزشی و شرط تایید سرپرست هر دو به‌درستی بیان شده‌اند."),
    (0, 1, 8, 1, "The response contradicts the reference: dress code is business casual, not formal suits."),
]

# Two fictional human reviews so the human-in-the-loop columns are populated.
DEMO_HUMAN = {
    0: {"score": 10, "comment": "کامل و دقیق.", "evaluated_at": "2026-09-28 10:12:00"},
    1: {"score": 3, "comment": "عدد مرخصی اشتباه است؛ خطای جدی.", "evaluated_at": "2026-09-28 10:14:30"},
    3: {"score": 4, "comment": "", "evaluated_at": "2026-09-28 10:17:05"},
}


def main():
    loader = DataLoader(os.path.join(Config.UPLOADS_DIR, "sample_qa.csv"))
    loader.load()
    questions = loader.get_all_questions()

    judge = LLMJudge()
    judge.submit_delay = 0
    judge.max_workers = 1
    canned = {}
    for q, (a, c, r, f, why) in zip(questions, DEMO_JUDGMENTS):
        body = {"accuracy": a, "completeness": c, "relevance": r, "faithfulness": f, "explanation": why}
        canned[q["question"]] = json.dumps(body, ensure_ascii=False)

    def fake_request(prompt):
        text = next(v for k, v in canned.items() if k in prompt)
        return {"choices": [{"message": {"content": text}}]}

    judge._make_request = fake_request
    results = judge.evaluate_batch(questions)
    for r in results:
        if r["id"] in DEMO_HUMAN:
            r["human_evaluation"] = DEMO_HUMAN[r["id"]]

    data = {
        "timestamp": "20260928_101000",
        "model": "demo (no LLM call)",
        "dataset_file": "sample_qa.csv",
        "total_questions": len(questions),
        "aggregates": judge.calculate_aggregate_scores(results),
        "results": results,
    }
    out = os.path.join(Config.RESULTS_DIR, "evaluation_demo.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    assert data["aggregates"]["total_evaluated"] == len(questions), data["aggregates"]
    print(f"wrote {out}: overall {data['aggregates']['overall']['average']}")


if __name__ == "__main__":
    main()
