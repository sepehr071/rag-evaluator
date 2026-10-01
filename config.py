import os
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    """Return env var value or raise RuntimeError if missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Set it in your .env file or system environment."
        )
    return value


class Config:
    # Authentication - required, no defaults
    SECRET_KEY = _require_env("SECRET_KEY")
    ADMIN_PASSWORD = _require_env("ADMIN_PASSWORD")
    EXPERT_PASSWORD = _require_env("EXPERT_PASSWORD")

    # OpenRouter API Configuration (internal use only)
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL_ID = os.getenv("MODEL_ID", "google/gemini-3.5-flash")

    # Judge (LLM-as-Judge) tunables — env-configurable
    JUDGE_TEMPERATURE = float(os.getenv("JUDGE_TEMPERATURE", "0.1"))
    JUDGE_MAX_TOKENS = int(os.getenv("JUDGE_MAX_TOKENS", "1000"))
    # Reasoning effort: low|medium|high — set "off"/"none"/"" to disable for speed
    JUDGE_REASONING_EFFORT = os.getenv("JUDGE_REASONING_EFFORT", "low")
    # Judge concurrency — OpenRouter handles high concurrency (not the heavy RAG backend)
    JUDGE_MAX_WORKERS = int(os.getenv("JUDGE_MAX_WORKERS", "8"))
    JUDGE_SUBMIT_DELAY = float(os.getenv("JUDGE_SUBMIT_DELAY", "0.05"))

    # File paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATASET_PATH = os.getenv("DATASET_PATH", os.path.join(BASE_DIR, "uploads", "sample_qa.csv"))
    RESULTS_DIR = os.path.join(BASE_DIR, "results")
    UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

    # Evaluation settings
    EVALUATION_CRITERIA = ["accuracy", "completeness", "relevance", "faithfulness"]
    MAX_SCORE = 10

    # Rate limiting
    REQUEST_DELAY = 1  # seconds between API calls

    # Retry configuration
    RETRY_MAX_ATTEMPTS = int(os.getenv('RETRY_MAX_ATTEMPTS', '3'))
    RETRY_MAX_WAIT_SECONDS = int(os.getenv('RETRY_MAX_WAIT_SECONDS', '60'))

    # Dify API Configuration
    DIFY_API_URL = os.getenv('DIFY_API_URL', '')
    DIFY_API_KEY = os.getenv('DIFY_API_KEY', '')
    DIFY_USER_ID = os.getenv('DIFY_USER_ID', 'rag-evaluator')

    # Data Collection Settings
    COLLECT_RATE_LIMIT_DELAY = float(os.getenv('COLLECT_RATE_LIMIT_DELAY', '0.1'))  # seconds
    COLLECT_TIMEOUT = int(os.getenv('COLLECT_TIMEOUT', '300'))  # seconds (5 min — RAG queries take 30-180s)
    COLLECT_MAX_WORKERS = int(os.getenv('COLLECT_MAX_WORKERS', '3'))  # concurrent requests
