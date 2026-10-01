"""LLM-as-Judge implementation using OpenRouter API."""

import requests
import json
import time
import re
import logging
from typing import Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import Config
from .prompts import get_evaluation_prompt, SYSTEM_PROMPT

# Configure logging
logger = logging.getLogger(__name__)


class LLMJudge:
    """Evaluates RAG responses using an LLM via OpenRouter."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.OPENROUTER_API_KEY
        self.api_url = Config.OPENROUTER_API_URL
        self.model_id = Config.MODEL_ID
        self.request_delay = Config.REQUEST_DELAY
        self.temperature = Config.JUDGE_TEMPERATURE
        self.max_tokens = Config.JUDGE_MAX_TOKENS
        self.reasoning_effort = Config.JUDGE_REASONING_EFFORT
        self.max_workers = Config.JUDGE_MAX_WORKERS
        self.submit_delay = Config.JUDGE_SUBMIT_DELAY

        if not self.api_key:
            raise ValueError("OpenRouter API key is required. Set OPENROUTER_API_KEY environment variable.")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=60),
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException
        )),
        reraise=True
    )
    def _make_request(self, prompt: str) -> Dict:
        """Make a request to OpenRouter API with retry logic.

        Retries are performed for network-related errors (connection issues,
        timeouts). Does NOT retry for client errors (4xx) like auth failures
        or invalid requests.

        Args:
            prompt: The evaluation prompt to send

        Returns:
            Dict: The JSON response from the API

        Raises:
            HTTPError: For 4xx/5xx responses that should not be retried
            RequestException: For network errors after retries are exhausted
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "RAG Evaluator"
        }

        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        # Reasoning is optional — disable (off/none/empty) to cut latency + cost
        if self.reasoning_effort and self.reasoning_effort.lower() not in ("off", "none", "false"):
            payload["reasoning"] = {"effort": self.reasoning_effort}

        response = requests.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=60
        )

        # Don't retry on client errors (4xx) - these are configuration issues
        if response.status_code >= 400 and response.status_code < 500:
            logger.error(
                f"Client error {response.status_code}: {response.text}. "
                f"Not retrying - check API key and request configuration."
            )
            response.raise_for_status()

        # Server errors (5xx) will be caught by retry decorator
        response.raise_for_status()
        return response.json()

    def _parse_response(self, response_text: str) -> Dict:
        """Parse the LLM response to extract scores."""
        try:
            text = response_text.strip()
            # Strip markdown code fences (```json ... ```) the model sometimes adds
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text).strip()
            # Greedy outer-brace match tolerates long Persian explanations
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            result = json.loads(json_match.group() if json_match else text)

            # Validate and normalize scores
            scores = {}
            for criterion in Config.EVALUATION_CRITERIA:
                score = result.get(criterion, 0)
                # Ensure score is within valid range
                scores[criterion] = max(0, min(Config.MAX_SCORE, float(score)))

            scores["explanation"] = result.get("explanation", "")
            return scores

        except (json.JSONDecodeError, ValueError) as e:
            # Return default scores if parsing fails
            logger.error(f"JSON parsing error: {str(e)}")
            return {
                "accuracy": 0,
                "completeness": 0,
                "relevance": 0,
                "faithfulness": 0,
                "explanation": "Invalid response format: پاسخ دریافted از API دارای فرمت نامعتبر است. لطفاً مدل دیگری را امتحان کنید یا با پشتیبانی تماس بگیرید.",
                "error_title": "Invalid response format",
                "error_suggestion": "فرمت پاسخ دریافتی نامعتبر است. لطفاً مدل دیگری را امتحان کنید.",
                "error_details": str(e),
                "error": True
            }

    def _get_error_message(self, error: Exception) -> tuple[str, str]:
        """Get error title and Persian suggestion based on error type.

        Returns:
            Tuple of (error_title, persian_suggestion)
        """
        # Authentication errors (401)
        if isinstance(error, requests.exceptions.HTTPError):
            if hasattr(error, 'response') and error.response is not None:
                status_code = error.response.status_code
                if status_code == 401:
                    return (
                        "API key invalid",
                        "کلید API معتبر نیست. لطفاً متغیر محیطی OPENROUTER_API_KEY را بررسی کرده و کلید معتبر وارد کنید."
                    )
                elif status_code == 429:
                    return (
                        "Rate limit exceeded",
                        "محدودیت درخواست‌ها فرارسیده است. لطفاً کمی صبر کنید و دوباره تلاش کنید، یا زمان انتظار بین درخواست‌ها را افزایش دهید."
                    )
                elif status_code >= 500:
                    return (
                        "Server error",
                        "خطای سمت سرور رخ داده است. لطفاً دوباره تلاش کنید یا با پشتیبانی OpenRouter تماس بگیرید."
                    )
                elif status_code >= 400:
                    return (
                        f"Bad request ({status_code})",
                        f"درخواست نامعتبر است. کد خطا: {status_code}. لطفاً پارامترهای درخواست را بررسی کنید."
                    )

        # Timeout errors
        if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ReadTimeout)):
            return (
                "Request timeout",
                "زمان درخواست به پایان رسید. لطفاً اتصال اینترنت خود را بررسی کرده و دوباره تلاش کنید."
            )

        # Connection errors
        if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout)):
            return (
                "Connection failed",
                "اتصال به سرور برقرار نشد. لطفاً اتصال اینترنت خود را بررسی کرده و از در دسترس بودن سرویس OpenRouter اطمینان حاصل کنید."
            )

        # Generic request exception
        if isinstance(error, requests.exceptions.RequestException):
            return (
                "API request failed",
                f"خطا در ارتباط با API: {type(error).__name__}. لطفاً دوباره تلاش کنید."
            )

        # Unknown error
        return (
            "Unknown error",
            f"خطای ناشناخته رخ داده است: {type(error).__name__}. لطفاً جزئیات را بررسی کنید."
        )

    def evaluate_single(self, question: str, ground_truth: str, agent_response: str) -> Dict:
        """Evaluate a single question-answer pair.

        Args:
            question: The question to evaluate
            ground_truth: The reference/expected answer
            agent_response: The agent's response to evaluate

        Returns:
            Dict: Scores and evaluation data, or error dict if evaluation fails
        """
        prompt = get_evaluation_prompt(question, ground_truth, agent_response)

        try:
            response = self._make_request(prompt)
            content = response["choices"][0]["message"]["content"]
            scores = self._parse_response(content)
            scores["raw_response"] = content
            return scores

        except requests.exceptions.HTTPError as e:
            # Client errors (4xx) - no retries occurred
            error_title, persian_suggestion = self._get_error_message(e)
            error_details = str(e)

            logger.error(f"HTTP Error {e.response.status_code}: {error_title}")

            return {
                "accuracy": 0,
                "completeness": 0,
                "relevance": 0,
                "faithfulness": 0,
                "explanation": f"{error_title}: {persian_suggestion}",
                "error_title": error_title,
                "error_suggestion": persian_suggestion,
                "error_details": error_details,
                "error": True
            }

        except requests.exceptions.RequestException as e:
            # Network errors - retries were attempted
            error_title, persian_suggestion = self._get_error_message(e)
            error_details = str(e)

            logger.warning(
                f"Request failed after 3 retry attempts: {error_title}"
            )

            return {
                "accuracy": 0,
                "completeness": 0,
                "relevance": 0,
                "faithfulness": 0,
                "explanation": f"{error_title}: {persian_suggestion}",
                "error_title": error_title,
                "error_suggestion": persian_suggestion,
                "error_details": error_details,
                "error": True,
                "retries_exhausted": True
            }

        except Exception as e:
            # Handle any other unexpected errors
            error_title = "Unexpected error"
            persian_suggestion = "خطای غیرمنتظره رخ داده است. لطفاً لاگ‌ها را بررسی کنید."
            error_details = str(e)

            logger.error(f"Unexpected error: {error_details}")

            return {
                "accuracy": 0,
                "completeness": 0,
                "relevance": 0,
                "faithfulness": 0,
                "explanation": f"{error_title}: {persian_suggestion}",
                "error_title": error_title,
                "error_suggestion": persian_suggestion,
                "error_details": error_details,
                "error": True
            }

    def evaluate_batch(self, questions: List[Dict], progress_callback=None, save_callback=None) -> List[Dict]:
        """Evaluate a batch of questions with concurrent API calls.

        Uses ThreadPoolExecutor (JUDGE_MAX_WORKERS, default 8) for parallel
        evaluation while respecting rate limits with a small delay between
        submissions.

        Args:
            questions: List of question dicts to evaluate
            progress_callback: Called with (current, total) after each question completes
            save_callback: Called with (results_so_far) after each question for incremental saving
        """
        results = [None] * len(questions)
        total = len(questions)
        completed = 0

        def evaluate_one(index, question):
            return index, self.evaluate_single(
                question=question["question"],
                ground_truth=question["ground_truth"],
                agent_response=question["agent_response"]
            )

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for i, q in enumerate(questions):
                future = executor.submit(evaluate_one, i, q)
                futures[future] = i
                # Small delay between submissions to respect rate limits
                if i < total - 1 and self.submit_delay > 0:
                    time.sleep(self.submit_delay)

            for future in as_completed(futures):
                idx, scores = future.result()
                q = questions[idx]
                scores["id"] = q["id"]
                scores["question"] = q["question"][:100] + "..." if len(q["question"]) > 100 else q["question"]
                results[idx] = scores
                completed += 1

                if progress_callback:
                    progress_callback(completed, total)
                if save_callback:
                    save_callback([r for r in results if r is not None])

        return [r for r in results if r is not None]

    def calculate_aggregate_scores(self, results: List[Dict]) -> Dict:
        """Calculate aggregate statistics from evaluation results."""
        if not results:
            return {}

        # Filter out error results for statistics
        valid_results = [r for r in results if not r.get("error", False)]

        if not valid_results:
            return {"error": "No valid results to aggregate"}

        aggregates = {}
        for criterion in Config.EVALUATION_CRITERIA:
            scores = [r[criterion] for r in valid_results]
            aggregates[criterion] = {
                "average": round(sum(scores) / len(scores), 2),
                "min": min(scores),
                "max": max(scores)
            }

        # Overall score (average of all criteria averages)
        overall_scores = []
        for r in valid_results:
            avg = sum(r[c] for c in Config.EVALUATION_CRITERIA) / len(Config.EVALUATION_CRITERIA)
            overall_scores.append(avg)

        aggregates["overall"] = {
            "average": round(sum(overall_scores) / len(overall_scores), 2),
            "min": round(min(overall_scores), 2),
            "max": round(max(overall_scores), 2)
        }

        aggregates["total_evaluated"] = len(valid_results)
        aggregates["total_errors"] = len(results) - len(valid_results)

        return aggregates
