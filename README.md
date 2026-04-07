# PDF eSign (Visual PDF Signature Tool)

## Description
PDF eSign is a local desktop application for placing visual signature overlays on PDF files and exporting a flattened output document.

This project is a **visual PDF signature/annotation tool**, not a certified digital-signature platform. It is designed for speed, simplicity, and offline/local workflows.

## Features
- Open and preview PDF documents locally
- Add and edit overlays:
  - Typed Signature
  - Signature Image
  - Name
  - Date
- Drag, resize, move, edit, and delete overlays before export
- Save a flattened PDF output with overlays applied
- Local-first workflow (no cloud dependency)

## Screenshots
- Main window and overlay tools: *(add screenshot)*
- Overlay placement and editing: *(add screenshot)*
- Exported output example: *(add screenshot)*

## Installation
### Requirements
- Python 3.11+
- Windows desktop environment (primary target)

### Setup
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Usage
1. Run the app:
```bash
python main.py
```
2. Open a PDF using **Open PDF**.
3. Choose an overlay type in **Overlay Tools**.
4. Enter text or select a signature image.
5. Click **Place eSign** (or the relevant Place button), then draw on the page.
6. Adjust overlay position/size as needed.
7. Export using **Save Document**.

## How It Works
- The app uses overlay objects for signature/name/date/image elements.
- Overlay geometry is stored in **PDF point coordinates** (not screen pixels), so zooming does not change saved positions.
- On export, overlays are flattened into the output PDF.

### Signature Rendering Behavior
- **Typed Signature** overlays are rendered as **visual graphics (image content)** in the output PDF.
  - They are intentionally non-selectable as text.
- **Name** and **Date** overlays are saved as regular PDF text.
- **Signature Image** overlays are embedded as image content.

## Limitations
- No built-in signer identity verification
- No cryptographic digital-signature certificate workflow
- No tamper-evident audit trail
- No legal compliance engine for ESIGN/UETA/eIDAS
- No guarantee that generated documents meet jurisdiction-specific e-sign requirements

## Disclaimer
This software is provided for visual PDF signing/annotation workflows only.

It is **not** a certified digital-signature solution and does **not** provide:
- cryptographic signing certificates,
- signer identity proofing,
- audit trail or non-repudiation controls,
- legal enforceability guarantees.

You are solely responsible for legal, regulatory, and policy compliance in your jurisdiction and use case, including (where applicable) ESIGN, UETA, eIDAS, and record-retention requirements.

The software is provided **"AS IS"**, without warranties of any kind.

## Tech Stack
- Python
- PySide6 (desktop UI)
- PyMuPDF / `fitz` (PDF rendering and output)

## Contributing
Contributions are welcome.

If you plan to contribute:
1. Open an issue describing the problem or proposal.
2. Keep changes focused and testable.
3. Submit a pull request with a clear summary of behavior changes.

## Future Improvements
- Optional audit trail metadata
- Optional cryptographic digital-signature integration
- Optional signer verification integrations
- Batch and template workflows

## License
See [LICENSE](LICENSE).
