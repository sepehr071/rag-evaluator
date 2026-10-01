"""Evaluation prompt templates for LLM-as-Judge."""

EVALUATION_PROMPT_TEMPLATE = """You are an expert evaluator for a Persian RAG chatbot. Your task is to evaluate how well the Agent Response answers the question compared to the Ground Truth.

Here are some examples to guide your evaluation:

**مثال ۱ (Example 1) - Excellent Response:**
**Question (سوال):** what is the capital of France and what are its main attractions?
**Ground Truth (جواب مرجع):** پاریس پایتخت فرانسه است. جاذبه‌های اصلی آن شامل برج ایفل، موزه لوور، کاتدرال نوتر Dame و خیابان شانزه لیزه می‌باشد.
**Agent Response:** پاریس پایتخت فرانسه است. این شهر مشهورترین جاذبه‌های گردشگری را دارد که مهم‌ترین آنها عبارتند از: برج ایفل (نماد شهر)، موزه لوور (بزرگترین موزه هنری جهان)، کلیسای نوتر Dame، و خیابان شانزه لیزه برای خرید و قدم زدن.
**Evaluation:** {{"accuracy": 10, "completeness": 10, "relevance": 10, "faithfulness": 10, "explanation": "پاسخ کاملاً دقیق و کامل است. تمام نکات کلیدی پوشش داده شده و هیچ اطلاعات غلط یا اضافی وجود ندارد."}}

**مثال ۲ (Example 2) - Good Response:**
**Question (سوال):** چگونه می‌توانم حساب کاربری خود را حذف کنم؟
**Ground Truth (جواب مرجع):** برای حذف حساب کاربری به بخش تنظیمات بروید، روی «حذف حساب» کلیک کنید و تاییدیه را وارد کنید. این عمل غیرقابل برگشت است.
**Agent Response:** برای حذف حساب باید به تنظیمات پروفایل خود بروید. گزینه حذف حساب در پایین صفحه تنظیمات قرار دارد. بعد از کلیک، یک پیام تایید برای شما ارسال می‌شود.
**Evaluation:** {{"accuracy": 9, "completeness": 8, "relevance": 10, "faithfulness": 9, "explanation": "پاسخ خوب و مرتبط است. اطلاعات اصلی صحیح اما جزئیات کمی کمتر از جواب مرجع است."}}

**مثال ۳ (Example 3) - Poor Response:**
**Question (سوال):** قیمت اشتراک ماهانه چقدر است؟
**Ground Truth (جواب مرجع):** اشتراک پایه ۹۹,۰۰۰ تومان، اشتراک پریمیوم ۱۹۹,۰۰۰ تومان و اشتراک سازمانی ۴۹۹,۰۰۰ تومان در ماه است.
**Agent Response:** قیمت‌ها بسیار مناسب هستند و شما می‌توانید از تخفیف‌های ویژه هم استفاده کنید. برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.
**Evaluation:** {{"accuracy": 2, "completeness": 1, "relevance": 5, "faithfulness": 3, "explanation": "پاسخ هیچ قیمت مشخصی ندارد و به سوال کاربر پاسخ روشن نمی‌دهد. اطلاعات کلی و بی‌فایده است."}}

---

Now evaluate the following:

**Question (سوال):**
{question}

**Ground Truth (جواب مرجع):**
{ground_truth}

**Agent Response:**
{agent_response}

Evaluate the Agent Response on these criteria (score 0-10 for each):

1. **Accuracy (دقت)**: Does the Agent Response contain factually correct information that matches the Ground Truth? Score 0 if completely wrong, 10 if perfectly accurate.

2. **Completeness (کامل بودن)**: Does the Agent Response cover all the key points mentioned in the Ground Truth? Score 0 if missing all key points, 10 if covers everything.

3. **Relevance (مرتبط بودن)**: Is the Agent Response directly relevant to the question asked? Score 0 if completely off-topic, 10 if perfectly on-topic.

4. **Faithfulness (وفاداری)**: Is the Agent Response free from hallucinations or made-up information not present in the Ground Truth? Score 0 if full of hallucinations, 10 if completely faithful.

IMPORTANT: You MUST respond ONLY with a valid JSON object in exactly this format, no other text:
{{"accuracy": <score>, "completeness": <score>, "relevance": <score>, "faithfulness": <score>, "explanation": "<brief explanation in Persian>"}}"""


def get_evaluation_prompt(question: str, ground_truth: str, agent_response: str) -> str:
    """Generate the evaluation prompt for a single question."""
    return EVALUATION_PROMPT_TEMPLATE.format(
        question=question,
        ground_truth=ground_truth,
        agent_response=agent_response
    )


SYSTEM_PROMPT = """You are an expert evaluator for RAG (Retrieval Augmented Generation) chatbots. You evaluate responses in Persian (Farsi) language with precision and fairness. Always respond with valid JSON only."""
