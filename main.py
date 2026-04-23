"""
main.py
Entry point for the note clone desktop app.
Run with:  python main.py
"""

import sys
import os
import logging

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

# Logging: DEBUG shows undo/redo and element lifecycle traces in the terminal
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont

from database.db import init_db
from ui.main_window import MainWindow
from utils.theme import APP_QSS


def main():
    # HiDPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv) # Create the application instance and pass command-line arguments
    app.setApplicationName("NoteVS")
    app.setOrganizationName("Neondevpy")
    app.setApplicationVersion("1.0.0")

    # Global stylesheet
    app.setStyleSheet(APP_QSS)

    # Default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Initialise DB (creates tables on first run)
    try:
        init_db()
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return

    # Seed a default board if none exists
    from database.db import get_all_boards, create_board
    try:
        if not get_all_boards():
            create_board("My First Board")
    except Exception as e:
        print(f"Board creation failed: {e}")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
