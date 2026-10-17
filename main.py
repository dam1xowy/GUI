import sys
import os
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainAppWindow

def load_stylesheet(app_instance, filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as file:
            app_instance.setStyleSheet(file.read())
    else:
        print(f"Stylesheet file not found: '{filepath}'")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    stylesheet_path = os.path.join(base_dir, "styles.qss")
    
    load_stylesheet(app, stylesheet_path)
    
    window = MainAppWindow()
    window.show()
    
    sys.exit(app.exec())