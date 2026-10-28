"""Shared Excel reading helpers.

Used by every fetcher that pulls .xls/.xlsx files from the public web
(GPR, AAII, NAAIM, …). Handles the modern xlsx + legacy BIFF .xls split
that pandas itself can't navigate cleanly:

  * pandas + openpyxl  → reads .xlsx
  * pandas + xlrd ≥2   → can't read .xls (support removed)
  * xlrd <2            → reads .xls but can't be wired through pandas

So we try openpyxl first; on failure fall back to driving xlrd 1.2 directly
and reconstruct a DataFrame ourselves.
"""

from __future__ import annotations

import io

import pandas as pd

from .base import FetchError


def read_excel_any(blob: bytes, *, source: str) -> pd.DataFrame:
    """Read an Excel byte blob via openpyxl with an xlrd fallback.

    Args:
        blob: raw bytes of the file.
        source: URL or path; used in the error message only.

    Raises:
        FetchError: if neither engine can parse the blob.
    """
    try:
        return pd.read_excel(io.BytesIO(blob), engine="openpyxl")
    except Exception as openpyxl_err:  # noqa: BLE001
        try:
            return _read_xls_via_xlrd(blob)
        except Exception as xlrd_err:  # noqa: BLE001
            raise FetchError(
                f"file unreadable as xlsx ({openpyxl_err}) "
                f"or as legacy xls ({xlrd_err}) — source={source}"
            ) from xlrd_err


def _read_xls_via_xlrd(blob: bytes) -> pd.DataFrame:
    """Parse a binary .xls into a DataFrame using xlrd 1.2 directly."""
    import xlrd

    book = xlrd.open_workbook(file_contents=blob)
    sheet = book.sheet_by_index(0)
    if sheet.nrows == 0:
        return pd.DataFrame()

    header = [str(v) for v in sheet.row_values(0)]
    rows: list[list[object]] = []
    for r in range(1, sheet.nrows):
        cells = sheet.row(r)
        parsed: list[object] = []
        for cell in cells:
            if cell.ctype == xlrd.XL_CELL_DATE:
                parsed.append(
                    xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                )
            elif cell.ctype == xlrd.XL_CELL_EMPTY:
                parsed.append(None)
            else:
                parsed.append(cell.value)
        rows.append(parsed)
    return pd.DataFrame(rows, columns=header)


def first_present(columns, candidates) -> str | None:
    """Return the first column name from `candidates` that's actually in `columns`."""
    cols = set(columns)
    for c in candidates:
        if c in cols:
            return c
    return None


# Magic-byte signatures for the two Excel container formats we accept.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # legacy .xls (BIFF / compound doc)
_ZIP_MAGIC = b"PK\x03\x04"                           # .xlsx (zip-based)


def is_excel_blob(blob: bytes) -> bool:
    """True iff `blob` starts with an Excel-format magic byte sequence.

    Useful to defend against sites that occasionally serve HTML
    maintenance / rate-limit pages with a 200 status code in place of the
    real spreadsheet — those would otherwise reach the Excel parser and
    surface a confusing 'Expected BOF record' error.
    """
    if len(blob) < 8:
        return False
    return blob.startswith(_OLE_MAGIC) or blob.startswith(_ZIP_MAGIC)
