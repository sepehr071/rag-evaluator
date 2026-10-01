import pandas as pd
from typing import List, Dict, Optional
import os


class DataLoader:
    """Handles loading and parsing of the evaluation dataset."""

    COLUMN_QUESTION = "سوال"
    COLUMN_GROUND_TRUTH = "جواب مرجع"
    COLUMN_AGENT_RESPONSE = "Agent Response"

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.data: Optional[pd.DataFrame] = None

    def load(self) -> bool:
        """Load the CSV dataset."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Dataset not found: {self.file_path}")

        # Handle both CSV and Excel files
        if self.file_path.endswith('.csv'):
            self.data = pd.read_csv(self.file_path, encoding='utf-8-sig')
        elif self.file_path.endswith(('.xlsx', '.xls')):
            self.data = pd.read_excel(self.file_path)
        else:
            raise ValueError("Unsupported file format. Use CSV or Excel.")

        # Validate required columns
        required_columns = [
            self.COLUMN_QUESTION,
            self.COLUMN_GROUND_TRUTH,
            self.COLUMN_AGENT_RESPONSE
        ]
        missing = [col for col in required_columns if col not in self.data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Clean data - remove rows with empty values
        self.data = self.data.dropna(subset=required_columns)
        self.data = self.data.reset_index(drop=True)

        return True

    def get_total_count(self) -> int:
        """Get total number of questions."""
        if self.data is None:
            return 0
        return len(self.data)

    def get_question(self, index: int) -> Dict:
        """Get a single question by index."""
        if self.data is None or index >= len(self.data):
            return {}

        row = self.data.iloc[index]
        return {
            "id": index,
            "question": str(row[self.COLUMN_QUESTION]),
            "ground_truth": str(row[self.COLUMN_GROUND_TRUTH]),
            "agent_response": str(row[self.COLUMN_AGENT_RESPONSE])
        }

    def get_all_questions(self) -> List[Dict]:
        """Get all questions as a list of dictionaries."""
        if self.data is None:
            return []

        return [self.get_question(i) for i in range(len(self.data))]

    def get_questions_batch(self, start: int, batch_size: int) -> List[Dict]:
        """Get a batch of questions."""
        if self.data is None:
            return []

        end = min(start + batch_size, len(self.data))
        return [self.get_question(i) for i in range(start, end)]
