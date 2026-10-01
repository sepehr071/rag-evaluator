"""
CSV Exporter Module

Provides utilities for exporting data to CSV with proper Persian/Farsi language support.
The key is using UTF-8-sig encoding which includes a BOM (Byte Order Mark) that helps
Excel correctly recognize and display Persian characters.
"""

import pandas as pd
from pathlib import Path
from typing import Union


def export_to_csv_with_persian_support(
    excel_path: Union[str, Path],
    csv_path: Union[str, Path]
) -> str:
    """
    Read an Excel file and export to CSV with UTF-8-sig encoding.

    This function ensures Persian/Farsi text is properly preserved when the CSV
    is opened in Excel or other spreadsheet applications. The 'utf-8-sig' encoding
    adds a BOM (Byte Order Mark) at the start of the file, which signals to Excel
    that the file is UTF-8 encoded.

    Args:
        excel_path: Path to the source Excel file (.xlsx, .xls)
        csv_path: Path where the CSV file will be saved

    Returns:
        str: The absolute path to the created CSV file

    Raises:
        FileNotFoundError: If the source Excel file doesn't exist
        ValueError: If the Excel file cannot be parsed
        IOError: If the CSV file cannot be written

    Example:
        >>> export_to_csv_with_persian_support(
        ...     "data.xlsx",
        ...     "output.csv"
        ... )
        'path/to/output.csv'
    """
    excel_path = Path(excel_path)
    csv_path = Path(csv_path)

    # Validate source file exists
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    try:
        # Read Excel file (pandas preserves Persian text)
        df = pd.read_excel(excel_path)

        # Export to CSV with UTF-8 + BOM encoding
        # This is crucial for proper Persian display in Excel
        df.to_csv(csv_path, encoding="utf-8-sig", index=False)

        return str(csv_path.resolve())

    except Exception as e:
        raise IOError(f"Failed to export CSV: {e}") from e
