import sys
import os
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainAppWindow

def load_stylesheet(app_instance, filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as file:
            app_instance.setStyleSheet(file.read())
    else:
        print(f"Ostrzeżenie: Nie znaleziono pliku stylów '{filepath}'")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    load_stylesheet(app, "styles.qss")
    
    window = MainAppWindow()
    window.show()
    
    sys.exit(app.exec())