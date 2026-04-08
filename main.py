import sys
import os

from app.startup_timing import mark, write_log

mark("python_import_complete")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase

mark("qt_imported")

from app.main_window import MainWindow
from app.paths import resource_path
from app.settings import SIGNATURE_FONTS

mark("app_modules_imported")

FONTS_DIR = resource_path("assets", "fonts")


def register_fonts() -> None:
    for font_meta in SIGNATURE_FONTS:
        path = os.path.join(FONTS_DIR, font_meta["file"])
        if os.path.isfile(path):
            QFontDatabase.addApplicationFont(path)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDF eSign")
    app.setOrganizationName("PDF eSign")
    mark("qapp_created")

    register_fonts()
    mark("fonts_registered")

    window = MainWindow(fonts_dir=FONTS_DIR)
    mark("main_window_constructed")

    window.show()
    mark("window_shown")

    # Flush telemetry after the event loop yields for the first time
    app.processEvents()
    write_log()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
