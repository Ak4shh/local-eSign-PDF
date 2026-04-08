import sys
import os
import time

# Record process start as early as possible so startup_timing._T0 is accurate.
os.environ.setdefault("_PDF_ESIGN_T0", str(time.perf_counter()))

if getattr(sys, "frozen", False):
    # Write errors to a log file next to the exe so crashes are diagnosable
    # without a console window (windowed mode silently swallows exceptions).
    log_path = os.path.join(os.path.dirname(sys.executable), "pdf_esign_error.log")
    try:
        sys.stderr = open(log_path, "w", buffering=1)
    except Exception:
        pass

    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            sys.stderr.write(msg)
            sys.stderr.flush()
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "PDF eSign \u2014 Startup Error", msg)
        except Exception:
            pass

    sys.excepthook = _excepthook
