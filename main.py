import sys
import os
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainAppWindow

def load_stylesheet(app_instance, filepath):
    """Pomocnicza funkcja do wczytywania stylów z pliku QSS."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as file:
            app_instance.setStyleSheet(file.read())
    else:
        print(f"Ostrzeżenie: Nie znaleziono pliku stylów '{filepath}'. Uruchamiam z domyślnym motywem.")

if __name__ == '__main__':
    # 1. Inicjalizacja aplikacji Qt
    app = QApplication(sys.argv)
    
    # 2. Wczytanie zewnętrznego arkusza stylów
    load_stylesheet(app, "styles.qss")
    
    # 3. Utworzenie i wyświetlenie głównego okna programu
    window = MainAppWindow()
    window.show()
    
    # 4. Uruchomienie głównej pętli zdarzeń
    sys.exit(app.exec())