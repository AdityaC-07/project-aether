# Table Parsing Implementation

## Summary

Added basic table parsing to the PDF parsing logic using Camelot library. Tables are automatically extracted from PDFs and numeric values are converted to metrics.

## Changes Made

### 1. Dependencies ([requirements.txt](requirements.txt))

- Added `camelot-py[cv]==0.10.1` - Table extraction library
- Added `opencv-python==4.11.0.86` - Required by Camelot for CV operations

### 2. PDF Parser ([app/utils/pdf_parser.py](app/utils/pdf_parser.py))

#### New Import

```python
import camelot
from app.schemas.context import Metric
```

#### New Function: `extract_tables_from_pdf()`

- Extracts tables from all PDF pages using Camelot
- Converts table data to metrics:
  - **Header Row**: Column names become metric names
  - **First Column**: Row label becomes region (if exists)
  - **Numeric Cells**: Converted to float values
  - Non-numeric cells are skipped
- Returns `List[Metric]` objects
- Errors are caught and logged; parsing never crashes the request
- Temporary files are cleaned up

#### Updated Function: `extract_metadata_and_text()`

- Now also calls `extract_tables_from_pdf()`
- Returns metrics in the response dict under `"metrics"` key
- Existing text and metadata extraction unchanged

### 3. Main API ([app/main.py](app/main.py))

#### Updated Endpoints

- `/analyze-pdf` - Now uses `extract_metadata_and_text()` to get metrics
- `/analyze-pdf-report` - Now uses `extract_metadata_and_text()` to get metrics

#### Changes

- Read file bytes using `await file.read()`
- Call `extract_metadata_and_text()` to get PDF data including metrics
- Pass extracted metrics to `ReasoningContext`

## Behavior

### When Tables are Found

- Numeric values from all table cells are extracted as metrics
- Metric structure: `{name: column_header, region: first_column_value, value: numeric}`
- Metrics are appended to existing metrics list (if any from manual input)

### When No Tables are Found

- Returns empty metrics list
- Processing continues normally with text extraction

### Error Handling

- Camelot errors are caught and logged
- PDF processing never crashes due to table parsing
- Request completes with whatever data was successfully extracted

## System Requirements

- Camelot requires `graphviz` for some PDF types (optional, PDFs work without it)
- OpenCV is used by Camelot for image processing

## Usage Example

```bash
# POST request to /analyze-pdf with PDF file
curl -X POST -F "file=@report.pdf" http://localhost:8000/analyze-pdf

# Returns ReasoningContext with:
# - narrative: extracted text
# - metrics: [
#     {name: "Revenue", region: "Q1", value: 10000},
#     {name: "Revenue", region: "Q2", value: 12000},
#     ...
#   ]
```

## Testing

To test with a PDF containing tables:

1. Create a PDF with a simple table (header row + numeric data)
2. Upload to `/analyze-pdf` or `/analyze-pdf-report`
3. Check response for extracted metrics in the context
