import csv
import io
from uuid import uuid4

from docparse.domain.ir import Cell, DocumentIR, Sheet


def parse_excel(data: bytes, *, file_id: str, filename: str) -> DocumentIR:
    if filename.lower().endswith(".csv"):
        return _parse_csv(data, file_id=file_id, filename=filename)
    try:
        from openpyxl import load_workbook
    except ImportError:
        return DocumentIR(
            document_id=uuid4().hex,
            file_id=file_id,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            warnings=["未安装 openpyxl，Excel 仅登记未解析。pip install 'docparse[excel]'"],
        )

    workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sheets: list[Sheet] = []
    parts: list[str] = []
    for sheet in workbook.worksheets:
        cells: list[Cell] = []
        for row in sheet.iter_rows():
            for item in row:
                if item.value is None:
                    continue
                value = str(item.value).strip()
                if not value:
                    continue
                address = item.coordinate
                cells.append(
                    Cell(
                        address=address,
                        value=value,
                        raw_value=value,
                        row=item.row,
                        column=item.column,
                    )
                )
                parts.append(f"{sheet.title}!{address}:{value}")
        sheets.append(Sheet(name=sheet.title, cells=cells))
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheets=sheets,
        raw_text="\n".join(parts),
    )


def _parse_csv(data: bytes, *, file_id: str, filename: str) -> DocumentIR:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    cells: list[Cell] = []
    parts: list[str] = []
    for r_idx, row in enumerate(reader, start=1):
        for c_idx, value in enumerate(row, start=1):
            cleaned = value.strip()
            if not cleaned:
                continue
            address = f"R{r_idx}C{c_idx}"
            cells.append(Cell(address=address, value=cleaned, row=r_idx, column=c_idx))
            parts.append(f"{address}:{cleaned}")
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="text/csv",
        sheets=[Sheet(name="Sheet1", cells=cells)],
        raw_text="\n".join(parts),
    )
