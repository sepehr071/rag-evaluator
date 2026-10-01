"""
Dify API Client for RAG Evaluation

A reusable client for collecting responses from Dify API
and storing them in Excel files with Persian text support.
"""

import requests
import json
import time
import asyncio
import logging
import threading
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
import aiohttp
import pandas as pd


# Module-level logger for retry events (visible outside class instances)
_retry_logger = logging.getLogger("DifyClient.retry")
if not _retry_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    _retry_logger.addHandler(_handler)
    _retry_logger.setLevel(logging.INFO)


def _log_retry_async(retry_state):
    """Log each retry attempt with error details."""
    exc = retry_state.outcome.exception()
    _retry_logger.warning(
        f"Retry attempt {retry_state.attempt_number} after error: {exc}"
    )


def _should_retry_async(retry_state) -> bool:
    """Custom retry predicate: retry on connection/timeout/5xx, not on 4xx."""
    exc = retry_state.outcome.exception()
    if exc is None:
        return False
    if isinstance(exc, (
        aiohttp.ClientConnectionError,
        aiohttp.ServerDisconnectedError,
        asyncio.TimeoutError,
    )):
        return True
    if isinstance(exc, aiohttp.ClientResponseError) and exc.status >= 500:
        return True
    return False


class DifyClient:
    """Client for interacting with Dify API to collect chatbot responses."""

    # Default event handlers for streaming response
    EVENT_MESSAGE = "message"
    EVENT_ERROR = "error"
    EVENT_MESSAGE_END = "message_end"

    # Connection timeout (separate from read timeout)
    CONNECT_TIMEOUT = 30

    # Use browser-like User-Agent to avoid Cloudflare/bot detection
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        api_url: str,
        api_key: str,
        user_id: str = "rag-evaluator",
        timeout: int = 300,
        rate_limit_delay: float = 1
    ):
        """
        Initialize the Dify client.

        Args:
            api_url: Dify API endpoint URL (e.g., https://dify.example.com/v1/chat-messages)
            api_key: Bearer token for authentication
            user_id: User identifier for API requests
            timeout: Read timeout in seconds (connection timeout is separate)
            rate_limit_delay: Delay between requests in seconds
        """
        self.api_url = api_url
        self.api_key = api_key
        self.user_id = user_id
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Configure and return a logger instance."""
        logger = logging.getLogger(f"DifyClient.{id(self)}")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def _get_headers(self) -> dict:
        """Get request headers with browser-like User-Agent."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
            "Accept": "text/event-stream",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=60),
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            http.client.RemoteDisconnected
        )),
        reraise=True
    )
    def _make_streaming_request(self, payload: dict) -> requests.Response:
        """Make a streaming request to Dify API with retry logic.

        Uses direct requests.post (no session) to avoid connection issues
        with certain servers that don't handle connection pooling well.

        Retries are performed for network-related errors (connection issues,
        timeouts, RemoteDisconnected). Does NOT retry for client errors (4xx).

        Args:
            payload: The request payload to send

        Returns:
            Response object with streaming enabled

        Raises:
            HTTPError: For 4xx/5xx responses
            RequestException: For network errors after retries are exhausted
        """
        response = requests.post(
            self.api_url,
            json=payload,
            headers=self._get_headers(),
            stream=True,
            timeout=(self.CONNECT_TIMEOUT, self.timeout)  # (connect, read) timeout
        )

        # Don't retry on client errors (4xx) - these are configuration issues
        if response.status_code >= 400 and response.status_code < 500:
            self.logger.error(
                f"Client error {response.status_code}: {response.text}. "
                f"Not retrying - check API key and request configuration."
            )
            response.raise_for_status()

        # Server errors (5xx) will be caught by retry decorator
        response.raise_for_status()
        return response

    def get_response(self, question: str, conversation_id: str = "", use_streaming: bool = False) -> str:
        """
        Send a single query to Dify API and return the response.

        Uses retry logic for transient network failures (RemoteDisconnected,
        connection errors, timeouts). Up to 3 retries with exponential backoff.

        Args:
            question: The question/query to send
            conversation_id: Optional conversation ID for context
            use_streaming: Use streaming mode (default: False, use blocking)

        Returns:
            The full response text from Dify, or error message if failed
        """
        # Use blocking mode by default - more reliable for batch processing
        response_mode = "streaming" if use_streaming else "blocking"

        payload = {
            "query": question,
            "inputs": {},
            "response_mode": response_mode,
            "user": self.user_id,
            "conversation_id": conversation_id
        }

        full_answer = ""

        try:
            if use_streaming:
                # Use the retry-enabled streaming request method
                with self._make_streaming_request(payload) as response:
                    for line in response.iter_lines():
                        if not line:
                            continue

                        line = line.decode("utf-8").strip()
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event = data.get("event")

                        if event == self.EVENT_MESSAGE:
                            full_answer += data.get("answer", "")

                        elif event == self.EVENT_ERROR:
                            error_msg = data.get("message", "Unknown error")
                            full_answer = f"Error: {error_msg}"
                            self.logger.error(f"API Error - {error_msg}")
                            break

                        elif event == self.EVENT_MESSAGE_END:
                            break

                    if not full_answer:
                        full_answer = "No response received"
                        self.logger.warning("Empty response received from API")
            else:
                # Use blocking mode - simpler and more reliable
                with self._make_blocking_request(payload) as response:
                    data = response.json()
                    full_answer = data.get("answer", "")

        except requests.exceptions.HTTPError as e:
            # Client errors (4xx) - no retries occurred
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else "Unknown"
            if status_code == 401:
                full_answer = "Error: Invalid API key. Please check DIFY_API_KEY in .env file."
            elif status_code == 404:
                full_answer = "Error: API endpoint not found. Check DIFY_API_URL."
            else:
                full_answer = f"Request Error: HTTP {status_code}"
            self.logger.error(f"{full_answer} - {e.response.text if hasattr(e, 'response') and e.response else ''}")

        except requests.exceptions.RequestException as e:
            # Network errors - retries were attempted
            full_answer = f"Request Error: {str(e)}"
            self.logger.warning(f"Request failed after 3 retry attempts: {str(e)}")

        except Exception as e:
            full_answer = f"Unexpected Error: {str(e)}"
            self.logger.error(full_answer)

        return full_answer

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=60),
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            http.client.RemoteDisconnected
        )),
        reraise=True
    )
    def _make_blocking_request(self, payload: dict) -> requests.Response:
        """Make a blocking request to Dify API with retry logic.

        Blocking mode waits for the complete response before returning.
        More reliable for batch processing than streaming.

        Args:
            payload: The request payload to send

        Returns:
            Response object

        Raises:
            HTTPError: For 4xx/5xx responses
            RequestException: For network errors after retries are exhausted
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT
        }

        response = requests.post(
            self.api_url,
            json=payload,
            headers=headers,
            timeout=(self.CONNECT_TIMEOUT, self.timeout)  # (connect, read) timeout
        )

        # Don't retry on client errors (4xx) - these are configuration issues
        if response.status_code >= 400 and response.status_code < 500:
            self.logger.error(
                f"Client error {response.status_code}: {response.text}. "
                f"Not retrying - check API key and request configuration."
            )
            response.raise_for_status()

        # Server errors (5xx) will be caught by retry decorator
        response.raise_for_status()
        return response

    def collect_responses(
        self,
        excel_path: str,
        output_path: str,
        question_column: str = "سوال",
        response_column: str = "Agent Response",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        """
        Read an Excel file, query Dify API for each question, and save results.

        Args:
            excel_path: Path to input Excel file
            output_path: Path to save output Excel file
            question_column: Column name containing questions (default: Persian 'سوال')
            response_column: Column name for agent responses
            progress_callback: Optional callback function(current, total, status)

        Returns:
            Summary dict with total, success, failed, and error details
        """
        try:
            df = pd.read_excel(excel_path, sheet_name=0)
        except Exception as e:
            self.logger.error(f"Failed to read Excel file: {e}")
            return {"error": str(e)}

        if question_column not in df.columns:
            self.logger.error(f"Column '{question_column}' not found in Excel file")
            return {"error": f"Column '{question_column}' not found"}

        # Initialize response column if not exists
        if response_column not in df.columns:
            df[response_column] = ""

        total_rows = len(df)
        success_count = 0
        failed_count = 0
        errors = []

        self.logger.info(f"Starting collection for {total_rows} questions")

        for idx, row in df.iterrows():
            question = str(row[question_column])
            current_num = idx + 1

            if progress_callback:
                progress_callback(current_num, total_rows, f"Processing question {current_num}/{total_rows}")

            # Skip if already has a response (not empty/error prefixed)
            existing_response = str(row.get(response_column, ""))
            if existing_response and existing_response.strip() and not existing_response.startswith("Error"):
                self.logger.info(f"Row {current_num}: Skipping - existing response found")
                success_count += 1
                continue

            response = self.get_response(question)

            df.at[idx, response_column] = response

            if response.startswith("Error") or response.startswith("Request Error"):
                failed_count += 1
                errors.append({"row": current_num, "question": question[:100], "error": response})
                self.logger.info(f"Row {current_num}: Failed - {response[:50]}")
            else:
                success_count += 1
                self.logger.info(f"Row {current_num}: Success - Response length: {len(response)}")

            # Rate limit delay between requests
            time.sleep(self.rate_limit_delay)

        # Save results
        try:
            df.to_excel(output_path, index=False)
            self.logger.info(f"Results saved to {output_path}")
        except Exception as e:
            self.logger.error(f"Failed to save Excel file: {e}")
            return {"error": f"Failed to save output: {str(e)}"}

        if progress_callback:
            progress_callback(total_rows, total_rows, "Completed")

        return {
            "total": total_rows,
            "success": success_count,
            "failed": failed_count,
            "output_path": output_path,
            "errors": errors
        }

    def collect_responses_parallel(
        self,
        excel_path: str,
        output_path: str,
        question_column: str = "سوال",
        response_column: str = "Agent Response",
        max_workers: int = 3,
        progress_callback: Optional[Callable[[int, int, int, int], None]] = None
    ) -> dict:
        """
        Parallel version of collect_responses using ThreadPoolExecutor.

        Args:
            excel_path: Path to input Excel file
            output_path: Path to save output Excel file
            question_column: Column name containing questions
            response_column: Column name for agent responses
            max_workers: Number of concurrent API requests (1-10)
            progress_callback: callback(completed, total, success_count, failed_count)

        Returns:
            Summary dict with total, success, failed, and error details
        """
        try:
            df = pd.read_excel(excel_path, sheet_name=0)
        except Exception as e:
            self.logger.error(f"Failed to read Excel file: {e}")
            return {"error": str(e)}

        if question_column not in df.columns:
            self.logger.error(f"Column '{question_column}' not found in Excel file")
            return {"error": f"Column '{question_column}' not found"}

        if response_column not in df.columns:
            df[response_column] = ""

        total_rows = len(df)
        max_workers = max(1, min(10, max_workers))

        # Thread-safe counters
        lock = threading.Lock()
        counters = {"completed": 0, "success": 0, "failed": 0}
        errors = []

        # Identify rows that need processing
        tasks = []
        for idx, row in df.iterrows():
            existing = str(row.get(response_column, ""))
            if existing and existing.strip() and not existing.startswith("Error"):
                # Already has valid response, count as success
                with lock:
                    counters["completed"] += 1
                    counters["success"] += 1
                continue
            tasks.append((idx, str(row[question_column])))

        skipped = counters["completed"]
        self.logger.info(
            f"Starting parallel collection: {len(tasks)} to process, "
            f"{skipped} skipped (existing), {max_workers} workers"
        )

        # Report initial progress (skipped items)
        if progress_callback and skipped > 0:
            progress_callback(skipped, total_rows, skipped, 0)

        # Incremental save interval
        save_every = max(1, min(5, len(tasks) // 10)) if tasks else 1
        unsaved_count = 0

        def process_one(idx: int, question: str) -> tuple:
            """Process a single question. Returns (idx, response)."""
            response = self.get_response(question)
            return idx, response

        if tasks:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for i, (idx, question) in enumerate(tasks):
                    future = executor.submit(process_one, idx, question)
                    futures[future] = (idx, question)
                    # Small delay between submissions to avoid burst
                    if i < len(tasks) - 1:
                        time.sleep(self.rate_limit_delay / max_workers)

                for future in as_completed(futures):
                    idx, question = futures[future]
                    try:
                        idx, response = future.result()
                    except Exception as e:
                        response = f"Error: {str(e)}"
                        self.logger.error(f"Row {idx + 1}: Exception - {e}")

                    df.at[idx, response_column] = response

                    with lock:
                        counters["completed"] += 1
                        if response.startswith("Error") or response.startswith("Request Error"):
                            counters["failed"] += 1
                            errors.append({
                                "row": idx + 1,
                                "question": question[:100],
                                "error": response
                            })
                            self.logger.info(f"Row {idx + 1}: Failed - {response[:50]}")
                        else:
                            counters["success"] += 1
                            self.logger.info(f"Row {idx + 1}: Success - {len(response)} chars")

                        unsaved_count += 1
                        c = counters.copy()

                    if progress_callback:
                        progress_callback(c["completed"], total_rows, c["success"], c["failed"])

                    # Incremental save to survive crashes
                    if unsaved_count >= save_every:
                        try:
                            with lock:
                                unsaved_count = 0
                            df.to_excel(output_path, index=False)
                        except Exception as e:
                            self.logger.warning(f"Incremental save failed: {e}")

        # Final save
        try:
            df.to_excel(output_path, index=False)
            self.logger.info(f"Results saved to {output_path}")
        except Exception as e:
            self.logger.error(f"Failed to save Excel file: {e}")
            return {"error": f"Failed to save output: {str(e)}"}

        if progress_callback:
            progress_callback(total_rows, total_rows, counters["success"], counters["failed"])

        return {
            "total": total_rows,
            "success": counters["success"],
            "failed": counters["failed"],
            "output_path": output_path,
            "errors": errors
        }

    # =========================================================================
    # Async methods (aiohttp) — high-throughput parallel collection
    # =========================================================================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=60),
        retry=_should_retry_async,
        reraise=True,
        before_sleep=_log_retry_async,
    )
    async def _async_blocking_request(
        self, session: aiohttp.ClientSession, payload: dict
    ) -> dict:
        """Make a blocking-mode request to Dify API via aiohttp with retry.

        Returns parsed JSON response dict.
        Retries on connection errors, timeouts, and 5xx server errors.
        Does NOT retry 4xx client errors.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        async with session.post(
            self.api_url, json=payload, headers=headers
        ) as resp:
            if 400 <= resp.status < 500:
                body = await resp.text()
                self.logger.error(
                    f"Client error {resp.status}: {body}. "
                    f"Not retrying - check API key and request configuration."
                )
            resp.raise_for_status()
            return await resp.json()

    async def get_response_async(
        self,
        session: aiohttp.ClientSession,
        question: str,
        conversation_id: str = "",
    ) -> str:
        """Async version of get_response(). Uses blocking mode for simplicity."""
        payload = {
            "query": question,
            "inputs": {},
            "response_mode": "blocking",
            "user": self.user_id,
            "conversation_id": conversation_id,
        }
        try:
            data = await self._async_blocking_request(session, payload)
            answer = data.get("answer", "")
            return answer if answer else "No response received"

        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                return "Error: Invalid API key. Please check DIFY_API_KEY in .env file."
            elif e.status == 404:
                return "Error: API endpoint not found. Check DIFY_API_URL."
            else:
                return f"Request Error: HTTP {e.status}"

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return f"Request Error: {str(e)}"

        except Exception as e:
            return f"Unexpected Error: {str(e)}"

    async def collect_responses_async(
        self,
        excel_path: str,
        output_path: str,
        question_column: str = "سوال",
        response_column: str = "Agent Response",
        max_workers: int = 10,
        progress_callback: Optional[Callable[[int, int, int, int], None]] = None,
    ) -> dict:
        """Async parallel collection using aiohttp with connection pooling.

        Args:
            excel_path: Path to input Excel file
            output_path: Path to save output Excel file
            question_column: Column name containing questions
            response_column: Column name for agent responses
            max_workers: Concurrent requests (1-30, default 10)
            progress_callback: callback(completed, total, success_count, failed_count)

        Returns:
            Summary dict with total, success, failed, and error details
        """
        try:
            df = pd.read_excel(excel_path, sheet_name=0)
        except Exception as e:
            self.logger.error(f"Failed to read Excel file: {e}")
            return {"error": str(e)}

        if question_column not in df.columns:
            self.logger.error(f"Column '{question_column}' not found in Excel file")
            return {"error": f"Column '{question_column}' not found"}

        if response_column not in df.columns:
            df[response_column] = ""

        total_rows = len(df)
        max_workers = max(1, min(30, max_workers))

        counters = {"completed": 0, "success": 0, "failed": 0}
        errors: list[dict] = []

        # Identify rows that need processing
        tasks = []
        for idx, row in df.iterrows():
            # str(NaN) == "nan"; NaN/"nan"/empty/error all mean "needs processing"
            existing = str(row.get(response_column, "")).strip()
            if existing and existing.lower() != "nan" and not existing.startswith("Error"):
                counters["completed"] += 1
                counters["success"] += 1
                continue
            tasks.append((idx, str(row[question_column])))

        skipped = counters["completed"]
        self.logger.info(
            f"Starting async collection: {len(tasks)} to process, "
            f"{skipped} skipped (existing), {max_workers} concurrent"
        )

        if progress_callback and skipped > 0:
            progress_callback(skipped, total_rows, skipped, 0)

        save_every = max(1, min(25, len(tasks) // 10)) if tasks else 1
        unsaved_count = 0
        partial_csv_path = output_path.rsplit(".", 1)[0] + ".partial.csv"

        if tasks:
            timeout = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=self.CONNECT_TIMEOUT,
            )
            connector = aiohttp.TCPConnector(limit=max_workers)
            semaphore = asyncio.Semaphore(max_workers)

            active_count = 0
            active_lock = asyncio.Lock()
            backpressure_delay = 0.0  # seconds to wait before each request

            async def process_one(
                session: aiohttp.ClientSession, idx: int, question: str
            ) -> tuple[int, str]:
                nonlocal active_count
                async with semaphore:
                    # Apply backpressure delay inside semaphore to avoid thundering herd
                    if backpressure_delay > 0:
                        await asyncio.sleep(backpressure_delay)
                    async with active_lock:
                        active_count += 1
                        current = active_count
                    self.logger.info(
                        f"Row {idx + 1}: Starting request ({current} active)"
                    )
                    response = await self.get_response_async(session, question)
                    async with active_lock:
                        active_count -= 1
                    return idx, response

            async with aiohttp.ClientSession(
                timeout=timeout, connector=connector
            ) as session:
                # Launch all tasks — semaphore controls concurrency
                pending = [
                    asyncio.create_task(process_one(session, idx, q))
                    for idx, q in tasks
                ]

                consecutive_failures = 0

                for coro in asyncio.as_completed(pending):
                    idx, response = await coro

                    df.at[idx, response_column] = response

                    counters["completed"] += 1
                    is_error = any(response.startswith(p) for p in (
                        "Error", "Request Error", "Unexpected Error",
                        "No response received",
                    ))
                    if is_error:
                        counters["failed"] += 1
                        question_text = str(df.at[idx, question_column])
                        errors.append({
                            "row": idx + 1,
                            "question": question_text[:100],
                            "error": response,
                        })
                        self.logger.info(f"Row {idx + 1}: Failed - {response[:50]}")

                        # Backpressure: increase delay on consecutive failures
                        consecutive_failures += 1
                        if consecutive_failures >= 2:
                            backpressure_delay = min(10, consecutive_failures * 3)
                            self.logger.warning(
                                f"Backpressure: {consecutive_failures} consecutive failures, "
                                f"adding {backpressure_delay}s delay between requests"
                            )
                    else:
                        counters["success"] += 1
                        self.logger.info(f"Row {idx + 1}: Success - {len(response)} chars")
                        # Reset backpressure on success
                        if consecutive_failures > 0:
                            consecutive_failures = 0
                            backpressure_delay = 0.0
                            self.logger.info("Backpressure released — server responding normally")

                    unsaved_count += 1

                    if progress_callback:
                        progress_callback(
                            counters["completed"], total_rows,
                            counters["success"], counters["failed"]
                        )

                    # Incremental save to survive crashes — CSV is ~10x faster
                    # than xlsx, and to_thread keeps the event loop unblocked.
                    if unsaved_count >= save_every:
                        try:
                            await asyncio.to_thread(
                                df.to_csv, partial_csv_path,
                                index=False, encoding="utf-8-sig",
                            )
                            unsaved_count = 0
                        except Exception as e:
                            self.logger.warning(f"Incremental save failed: {e}")

        # Second pass: retry failed rows sequentially
        error_prefixes = ("Error", "Request Error", "Unexpected Error", "No response received")
        failed_rows = [
            (idx, str(df.at[idx, question_column]))
            for idx in range(len(df))
            if any(str(df.at[idx, response_column]).startswith(p) for p in error_prefixes)
        ]

        if failed_rows:
            self.logger.info(
                f"Retry pass: {len(failed_rows)} failed rows, processing sequentially"
            )
            retry_timeout = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=self.CONNECT_TIMEOUT,
            )
            async with aiohttp.ClientSession(
                timeout=retry_timeout,
                connector=aiohttp.TCPConnector(limit=1),
            ) as retry_session:
                for idx, question in failed_rows:
                    self.logger.info(f"Retry row {idx + 1}: Starting request")
                    response = await self.get_response_async(retry_session, question)
                    df.at[idx, response_column] = response

                    is_error = any(response.startswith(p) for p in error_prefixes)
                    if is_error:
                        self.logger.info(f"Retry row {idx + 1}: Still failed - {response[:50]}")
                    else:
                        # Flip from failed to success
                        counters["success"] += 1
                        counters["failed"] = max(0, counters["failed"] - 1)
                        self.logger.info(
                            f"Retry row {idx + 1}: Recovered - {len(response)} chars"
                        )

                    if progress_callback:
                        progress_callback(
                            counters["completed"], total_rows,
                            counters["success"], counters["failed"]
                        )

                    # Brief delay between sequential retries
                    await asyncio.sleep(self.rate_limit_delay)

        # Final save (xlsx is the contract app.py expects) — off the event loop
        try:
            await asyncio.to_thread(df.to_excel, output_path, index=False)
            self.logger.info(f"Results saved to {output_path}")
            # Drop the partial CSV now that the full xlsx is written
            import os
            if os.path.exists(partial_csv_path):
                os.remove(partial_csv_path)
        except Exception as e:
            self.logger.error(f"Failed to save Excel file: {e}")
            return {"error": f"Failed to save output: {str(e)}"}

        if progress_callback:
            progress_callback(total_rows, total_rows, counters["success"], counters["failed"])

        return {
            "total": total_rows,
            "success": counters["success"],
            "failed": counters["failed"],
            "output_path": output_path,
            "errors": errors,
        }
