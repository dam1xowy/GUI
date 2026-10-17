import os
import re
import shutil
import socket
import psutil
import subprocess
import time
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, 
    QHBoxLayout, QGridLayout, QProgressBar, QFrame, QScrollArea, 
    QTableWidget, QTableWidgetItem, QHeaderView, QSlider, QTreeView, 
    QTabWidget, QLineEdit, QTextEdit, QInputDialog, QMessageBox, QApplication
)
from PyQt6.QtGui import QFileSystemModel, QCursor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QEvent, QModelIndex, QTimer, Qt, QUrl, QProcess

from widgets.net_chart import TacticalNetChart
from core.workers import SystemMonitorWorker, HeavyTasksWorker, NtpSyncWorker


class DeselectableFileTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_selected_path = ""

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            current = self.currentIndex()
            if current.isValid():
                self.last_selected_path = self.model().filePath(current)
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())

        super().mousePressEvent(event)

        current = self.currentIndex()
        if current.isValid():
            self.last_selected_path = self.model().filePath(current)


class MainAppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nitro GUI")
        self.resize(1350, 880)
        
        self.base_root_path = "/"
        self.term_encoding = "utf-8"
        
        self.last_pos = QCursor.pos()
        self.last_time = datetime.now()
        self.total_distance = 0.0
        self.click_count = 0
        self.key_count = 0
        self.current_speed = 0.0
        self.click_timestamps = []
        
        net_io = psutil.net_io_counters()
        self.last_net_sent = net_io.bytes_sent
        self.last_net_recv = net_io.bytes_recv
        self.ntp_time_epoch = None
        self.ntp_sync_monotonic = None

        self.init_ui()
        QApplication.instance().installEventFilter(self)
        self.start_background_workers()
        self.ntp_worker = NtpSyncWorker(self)
        self.ntp_worker.sync_ready.connect(self.handle_ntp_sync)
        self.ntp_worker.sync_failed.connect(self.handle_ntp_sync_failure)
        self.ntp_timer = QTimer(self)
        self.ntp_timer.timeout.connect(self.sync_ntp_time)
        self.ntp_timer.start(10 * 60 * 1000)
        self.sync_ntp_time()
        self.fast_timer = QTimer(self)
        self.fast_timer.timeout.connect(self.update_fast_ui_elements)
        self.fast_timer.start(100)

    def _make_process_table_read_only(self, table):
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        top_bar_layout = QHBoxLayout()
        top_title = QLabel("<b>[ Nitro GUI ]</b>")
        top_title.setStyleSheet("color: #00FF66; font-size: 10pt; font-weight: bold;") 
        top_bar_layout.addWidget(top_title)
        top_bar_layout.addStretch()
        main_layout.addLayout(top_bar_layout)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        self._setup_telemetry_tab()
        self._setup_files_tab()
        self._setup_terminal_tab()
        self._setup_browser_tab()

    def _setup_telemetry_tab(self):
        tab1 = QWidget()
        tab1_layout = QGridLayout(tab1)
        tab1_layout.setContentsMargins(6, 6, 6, 6)
        tab1_layout.setSpacing(12)
        
        cpu_frame = QFrame()
        cpu_layout = QVBoxLayout(cpu_frame)
        cpu_layout.setContentsMargins(12, 12, 12, 12)
        
        cpu_top_layout = QHBoxLayout()
        cpu_top_layout.addWidget(QLabel("<b>[ CPU THREADS & TEMPERATURE ]</b>"))
        self.temp_label = QLabel("CPU Temperature: reading...")
        self.temp_label.setStyleSheet("color: #FFB300; font-weight: bold;")
        cpu_top_layout.addWidget(self.temp_label, alignment=Qt.AlignmentFlag.AlignRight)
        cpu_layout.addLayout(cpu_top_layout)
        
        cpu_scroll = QScrollArea()
        cpu_scroll.setWidgetResizable(True)
        cpu_scroll.setStyleSheet("background: transparent; border: none;")
        
        cpu_widget = QWidget()
        self.cpu_threads_layout = QVBoxLayout(cpu_widget)
        self.cpu_bars = []
        num_cores = psutil.cpu_count(logical=True) or 1
        for i in range(num_cores):
            bar_layout = QHBoxLayout()
            lbl = QLabel(f"Thread {i}:")
            lbl.setFixedWidth(65)
            pbar = QProgressBar()
            pbar.setRange(0, 100)
            bar_layout.addWidget(lbl)
            bar_layout.addWidget(pbar)
            self.cpu_threads_layout.addLayout(bar_layout)
            self.cpu_bars.append(pbar)
            
        cpu_widget.setLayout(self.cpu_threads_layout)
        cpu_scroll.setWidget(cpu_widget)
        cpu_layout.addWidget(cpu_scroll)
        tab1_layout.addWidget(cpu_frame, 0, 0)

        ram_frame = QFrame()
        ram_layout = QVBoxLayout(ram_frame)
        ram_layout.setContentsMargins(12, 12, 12, 12)
        ram_layout.setSpacing(10)
        
        ram_layout.addWidget(QLabel("<b>[ RAM & PROCESSES ]</b>"))
        self.ram_info_label = QLabel("RAM Usage: 0%")
        ram_layout.addWidget(self.ram_info_label)
        
        ram_grid_widget = QWidget()
        self.ram_grid_layout = QGridLayout(ram_grid_widget)
        self.ram_grid_layout.setContentsMargins(0, 2, 0, 4)
        self.ram_grid_layout.setSpacing(5)
        self.ram_blocks = []
        for r in range(4):
            for c in range(8):
                block = QLabel()
                block.setFixedSize(28, 15)
                block.setStyleSheet("background-color: #121e12; border: 1px solid #1f331f; border-radius: 2px;")
                self.ram_grid_layout.addWidget(block, r, c)
                self.ram_blocks.append(block)
        ram_layout.addWidget(ram_grid_widget)
        
        ram_layout.addSpacing(5)
        ram_layout.addWidget(QLabel("Top 3 Processes (RAM):"))
        self.proc_table = QTableWidget(3, 2)
        self.proc_table.setHorizontalHeaderLabels(["Process", "RAM (MB)"])
        self.proc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.proc_table.setFixedHeight(150)
        self._make_process_table_read_only(self.proc_table)
        ram_layout.addWidget(self.proc_table)

        ram_layout.addSpacing(5)
        ram_layout.addWidget(QLabel("Top 3 Processes (CPU):"))
        self.proc_cpu_table = QTableWidget(3, 2)
        self.proc_cpu_table.setHorizontalHeaderLabels(["Process", "CPU (%)"])
        self.proc_cpu_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.proc_cpu_table.setFixedHeight(150)
        self._make_process_table_read_only(self.proc_cpu_table)
        ram_layout.addWidget(self.proc_cpu_table)

        ram_layout.addSpacing(5)
        ram_layout.addWidget(QLabel("Top 3 Processes (GPU):"))
        self.proc_gpu_table = QTableWidget(3, 2)
        self.proc_gpu_table.setHorizontalHeaderLabels(["Process", "GPU (%)"])
        self.proc_gpu_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.proc_gpu_table.setFixedHeight(150)
        self._make_process_table_read_only(self.proc_gpu_table)
        ram_layout.addWidget(self.proc_gpu_table)
        
        ram_layout.addStretch()
        tab1_layout.addWidget(ram_frame, 0, 1)

        tele_frame = QFrame()
        tele_layout = QVBoxLayout(tele_frame)
        tele_layout.setContentsMargins(12, 12, 12, 12)
        tele_layout.setSpacing(8)
        
        title_lbl = QLabel("<b>[ USER & SYSTEM TELEMETRY ]</b>")
        title_lbl.setFixedHeight(15) 
        tele_layout.addWidget(title_lbl)
        
        self.uptime_label = QLabel("System Uptime: --")
        self.dist_label = QLabel("Mouse Distance: 0.00 m")
        self.speed_label = QLabel("Cursor Speed: 0 px/s")
        self.cps_label = QLabel("Click Rate (CPS): 0.0")
        self.click_label = QLabel("Total Mouse Clicks: 0")
        self.key_label = QLabel("Key Presses: 0")
        self.clipboard_label = QLabel("Clipboard: [empty]")
        self.clipboard_label.setWordWrap(True)

        stats_container = QWidget()
        stats_layout = QVBoxLayout(stats_container)
        stats_layout.setContentsMargins(10, 10, 10, 10)
        stats_layout.setSpacing(6)
        stats_container.setStyleSheet("background-color: #040704; border: 1px solid #142214; border-radius: 4px;")
        
        for lbl in [self.uptime_label, self.dist_label, self.speed_label, self.cps_label, self.click_label, self.key_label, self.clipboard_label]:
            stats_layout.addWidget(lbl)
            
        tele_layout.addWidget(stats_container)
        
        tele_layout.addSpacing(15)
        self.vol_label = QLabel("System Volume: --%")
        self.vol_label.setFixedHeight(25) 
        tele_layout.addWidget(self.vol_label)
        
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        
        initial_vol = self._get_initial_volume()
        if initial_vol is not None:
            self.vol_slider.setValue(initial_vol)
            self.vol_label.setText(f"System Volume: {initial_vol}%")

        self.vol_slider.valueChanged.connect(self.change_volume)
        tele_layout.addWidget(self.vol_slider)

        tele_layout.addSpacing(10)
        self.panic_btn = QPushButton("OS Shutdown")
        self.panic_btn.setObjectName("panicBtn")
        self.panic_btn.clicked.connect(self.trigger_shutdown)
        tele_layout.addWidget(self.panic_btn)
        
        tab1_layout.addWidget(tele_frame, 0, 2)
        
        tab1_layout.addWidget(tele_frame, 0, 2)
        tab1_layout.setColumnStretch(0, 3)
        tab1_layout.setColumnStretch(1, 3)
        tab1_layout.setColumnStretch(2, 4)
        self.tabs.addTab(tab1, "HARDWARE & TELEMETRY")

    def _setup_files_tab(self):
        tab2 = QWidget()
        tab2_layout = QGridLayout(tab2)
        tab2_layout.setContentsMargins(6, 6, 6, 6)
        
        file_frame = QFrame()
        file_layout = QVBoxLayout(file_frame)
        file_layout.addWidget(QLabel("<b>[ FILE ANALYSIS & MANAGEMENT ]</b>"))
        
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath(self.base_root_path)
        self.file_tree = DeselectableFileTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(self.base_root_path))
        self.file_tree.setColumnHidden(1, False)
        self.file_tree.setColumnHidden(2, True)
        self.file_tree.setColumnHidden(3, True)
        self.file_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        file_layout.addWidget(self.file_tree)

        file_btn_layout = QHBoxLayout()
        btn_new_file = QPushButton("New File")
        btn_new_file.clicked.connect(self.create_new_file)
        btn_new_dir = QPushButton("New Folder")
        btn_new_dir.clicked.connect(self.create_new_folder)
        
        btn_delete = QPushButton("Delete Selected")
        btn_delete.setStyleSheet("background-color: #2b0f0f; color: #ff5555; border: 1px solid #ff5555;")
        btn_delete.clicked.connect(self.delete_selected_item)
        
        file_btn_layout.addWidget(btn_new_file)
        file_btn_layout.addWidget(btn_new_dir)
        file_btn_layout.addWidget(btn_delete)
        file_layout.addLayout(file_btn_layout)
        tab2_layout.addWidget(file_frame, 0, 0)

        net_disk_frame = QFrame()
        net_disk_frame.setMaximumWidth(460)
        nd_layout = QVBoxLayout(net_disk_frame)
        nd_layout.setContentsMargins(12, 12, 12, 12)
        nd_layout.setSpacing(10)
        nd_layout.addWidget(QLabel("<b>[ NETWORK & STORAGE DIAGNOSTICS ]</b>"))
        
        self.disk_label = QLabel("System Disk: Scanning...")
        self.disk_label.setWordWrap(True)
        nd_layout.addWidget(self.disk_label)
        
        nd_layout.addSpacing(5)
        nd_layout.addWidget(QLabel("<b>[ LIVE NETWORK TRAFFIC MONITORS ]</b>"))
        self.dl_chart = TacticalNetChart("Download:", "#00FF66")
        nd_layout.addWidget(self.dl_chart)
        self.ul_chart = TacticalNetChart("Upload:", "#33FF88")
        nd_layout.addWidget(self.ul_chart)

        nd_layout.addSpacing(5)
        self.ip_ping_label = QLabel("Local IP: -- | Status: Active")
        self.ip_ping_label.setWordWrap(True)
        nd_layout.addWidget(self.ip_ping_label)
        
        self.usb_label = QLabel("USB: Scanning for devices...")
        self.usb_label.setWordWrap(True)
        nd_layout.addWidget(self.usb_label)
        
        self.atomic_clock_label = QLabel("Clock: Waiting for NTP synchronization...")
        self.atomic_clock_label.setWordWrap(True)
        self.atomic_clock_label.setStyleSheet("color: #00FF66; font-weight: bold; font-size: 10pt; margin-top: 5px;")
        nd_layout.addWidget(self.atomic_clock_label)

        tab2_layout.addWidget(net_disk_frame, 0, 1)
        self.tabs.addTab(tab2, "FILES, DRIVES & NETWORK")
        
        self.cached_ip = self.get_local_ip()

    def _setup_terminal_tab(self):
        tab3 = QWidget()
        tab3_layout = QVBoxLayout(tab3)
        tab3_layout.setContentsMargins(6, 6, 6, 6)
        
        cmd_frame = QFrame()
        cmd_layout = QVBoxLayout(cmd_frame)
        cmd_layout.addWidget(QLabel("<b>[ SYSTEM SHELL - INTERACTIVE TERMINAL ]</b>"))
        
        self.cmd_output = QTextEdit()
        self.cmd_output.setReadOnly(True)
        cmd_layout.addWidget(self.cmd_output)
        
        cmd_input_layout = QHBoxLayout()
        self.prompt_label = QLabel("$ ")
        self.prompt_label.setStyleSheet("color: #00FF66; font-weight: bold;")
        
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter a command...")
        self.cmd_input.returnPressed.connect(self.run_cmd_command)
        
        cmd_input_layout.addWidget(self.prompt_label)
        cmd_input_layout.addWidget(self.cmd_input)
        cmd_layout.addLayout(cmd_input_layout)
        
        tab3_layout.addWidget(cmd_frame)
        self.tabs.addTab(tab3, "TERMINAL")

        self.cmd_process = QProcess(self)
        self.cmd_process.readyReadStandardOutput.connect(self.handle_cmd_stdout)
        self.cmd_process.readyReadStandardError.connect(self.handle_cmd_stderr)
        
        shell_bin = os.environ.get("SHELL", "/bin/bash")
        if not os.path.exists(shell_bin):
            shell_bin = "/bin/bash"
        self.terminal_output_buffer = ""
        self.cmd_process.started.connect(self._request_terminal_directory)
        self.cmd_process.start(shell_bin)

    def _request_terminal_directory(self):
        self.cmd_process.write(b'printf "\\036GUI_CWD:%s\\037" "$PWD"\n')

    def _show_terminal_output(self, text):
        start_marker = "\x1eGUI_CWD:"
        end_marker = "\x1f"
        self.terminal_output_buffer += text

        while True:
            marker_start = self.terminal_output_buffer.find(start_marker)
            if marker_start == -1:
                keep = 0
                for length in range(1, len(start_marker)):
                    if self.terminal_output_buffer.endswith(start_marker[:length]):
                        keep = length
                if keep:
                    self.cmd_output.insertPlainText(self.terminal_output_buffer[:-keep])
                    self.terminal_output_buffer = self.terminal_output_buffer[-keep:]
                else:
                    self.cmd_output.insertPlainText(self.terminal_output_buffer)
                    self.terminal_output_buffer = ""
                return

            self.cmd_output.insertPlainText(self.terminal_output_buffer[:marker_start])
            marker_end = self.terminal_output_buffer.find(end_marker, marker_start + len(start_marker))
            if marker_end == -1:
                self.terminal_output_buffer = self.terminal_output_buffer[marker_start:]
                return

            directory = self.terminal_output_buffer[marker_start + len(start_marker):marker_end]
            self.prompt_label.setText(f"{directory} $ ")
            self.terminal_output_buffer = self.terminal_output_buffer[marker_end + len(end_marker):]

    def _setup_browser_tab(self):
        tab4 = QWidget()
        tab4_layout = QVBoxLayout(tab4)
        tab4_layout.setContentsMargins(6, 6, 6, 6)
        
        browser_frame = QFrame()
        browser_layout = QVBoxLayout(browser_frame)
        
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setText("https://www.google.com/")
        self.url_input.returnPressed.connect(self.navigate_to_url)
        
        go_btn = QPushButton("GO")
        go_btn.clicked.connect(self.navigate_to_url)
        
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(go_btn)
        browser_layout.addLayout(url_layout)
        
        self.browser_view = QWebEngineView()
        self.browser_view.setUrl(QUrl("https://www.google.com/"))
        self.browser_view.urlChanged.connect(lambda qurl: self.url_input.setText(qurl.toString()))
        browser_layout.addWidget(self.browser_view)
        
        tab4_layout.addWidget(browser_frame)
        self.tabs.addTab(tab4, "BROWSER")

    def start_background_workers(self):
        self.sys_worker = SystemMonitorWorker(self)
        self.sys_worker.cpu_data_ready.connect(self.update_cpu_ui)
        self.sys_worker.cpu_temperature_ready.connect(self.update_cpu_temperature_ui)
        self.sys_worker.ram_data_ready.connect(self.update_ram_ui)
        self.sys_worker.start()

        self.heavy_worker = HeavyTasksWorker(self)
        self.heavy_worker.disks_data_ready.connect(self.update_disks_ui)
        self.heavy_worker.processes_data_ready.connect(self.update_processes_ui)
        self.heavy_worker.gpu_data_ready.connect(self.update_gpu_ui)
        self.heavy_worker.usb_data_ready.connect(self.update_usb_ui) 
        self.heavy_worker.start()

    def update_cpu_temperature_ui(self, temperature):
        if temperature is None:
            self.temp_label.setText("CPU Temperature: unavailable")
        else:
            self.temp_label.setText(f"CPU Temperature: {temperature:.1f} °C")

    def update_cpu_ui(self, cpu_usages):
        for i, usage in enumerate(cpu_usages):
            if i < len(self.cpu_bars):
                self.cpu_bars[i].setValue(int(usage))
                self.cpu_bars[i].setFormat(f"{usage}%")

    def update_ram_ui(self, ram):
        self.ram_info_label.setText(f"RAM Usage: {ram.percent}% ({ram.used // (1024*1024)} MB)")
        active_blocks = int((ram.percent / 100.0) * len(self.ram_blocks))
        for idx, block in enumerate(self.ram_blocks):
            if idx < active_blocks:
                block.setStyleSheet("background-color: #00FF66; border: 1px solid #00aa44; border-radius: 2px;")
            else:
                block.setStyleSheet("background-color: #121e12; border: 1px solid #1f331f; border-radius: 2px;")

    def update_disks_ui(self, disks_text):
        self.disk_label.setText(f"System Disk: {disks_text}")

    def update_processes_ui(self, procs_ram, procs_cpu):
        self.proc_table.clearContents()
        for row, (name, mem) in enumerate(procs_ram):
            self.proc_table.setItem(row, 0, QTableWidgetItem(name))
            self.proc_table.setItem(row, 1, QTableWidgetItem(f"{mem:.1f} MB"))
            
        self.proc_cpu_table.clearContents()
        for row, (name, cpu) in enumerate(procs_cpu):
            self.proc_cpu_table.setItem(row, 0, QTableWidgetItem(name))
            self.proc_cpu_table.setItem(row, 1, QTableWidgetItem(f"{cpu:.1f} %"))

    def update_gpu_ui(self, gpu_procs):
        self.proc_gpu_table.clearContents()
        if not gpu_procs:
            self.proc_gpu_table.setItem(0, 0, QTableWidgetItem("No GPU activity"))
            self.proc_gpu_table.setItem(0, 1, QTableWidgetItem("-"))
        else:
            for row, (name, usage) in enumerate(gpu_procs):
                self.proc_gpu_table.setItem(row, 0, QTableWidgetItem(name))
                self.proc_gpu_table.setItem(row, 1, QTableWidgetItem(f"{usage} %"))

    def sync_ntp_time(self):
        if not self.ntp_worker.isRunning():
            self.ntp_worker.start()

    def handle_ntp_sync(self, epoch_time, monotonic_time):
        self.ntp_time_epoch = epoch_time
        self.ntp_sync_monotonic = monotonic_time

    def handle_ntp_sync_failure(self):
        if self.ntp_time_epoch is None:
            self.atomic_clock_label.setText("Local clock: NTP unavailable (check Internet / UDP 123)")

    def update_fast_ui_elements(self):
        now = datetime.now()
        
        self.click_timestamps = [t for t in self.click_timestamps if (now - t).total_seconds() <= 1.0]
        self.cps_label.setText(f"Click Rate (CPS): {len(self.click_timestamps)}.0")

        current_pos = QCursor.pos()
        dx = current_pos.x() - self.last_pos.x()
        dy = current_pos.y() - self.last_pos.y()
        pixels = (dx**2 + dy**2)**0.5
        time_diff = (now - self.last_time).total_seconds()
        
        if time_diff > 0:
            self.current_speed = pixels / time_diff
        self.total_distance += (pixels / 3779.52)
        
        self.last_pos = current_pos
        self.last_time = now
        
        self.dist_label.setText(f"Mouse Distance: {self.total_distance:.2f} m")
        self.speed_label.setText(f"Cursor Speed: {self.current_speed:.1f} px/s")

        if now.microsecond < 150000: 
            net_io = psutil.net_io_counters()
            sent_speed = (net_io.bytes_sent - self.last_net_sent) / 1024.0 
            recv_speed = (net_io.bytes_recv - self.last_net_recv) / 1024.0 
            
            self.last_net_sent = net_io.bytes_sent
            self.last_net_recv = net_io.bytes_recv
            
            self.dl_chart.update_data(recv_speed)
            self.ul_chart.update_data(sent_speed)

        boot_timestamp = psutil.boot_time()
        uptime_seconds = int(now.timestamp() - boot_timestamp)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s" if days > 0 else f"{hours}h {minutes}m {seconds}s"
        self.uptime_label.setText(f"System Uptime: {uptime_str}")

        if self.ntp_time_epoch is None:
            clock_now = now
            clock_source = "local; NTP unavailable"
        else:
            synced_epoch = self.ntp_time_epoch + time.monotonic() - self.ntp_sync_monotonic
            clock_now = datetime.fromtimestamp(synced_epoch)
            clock_source = "NTP synchronized"
        now_str = clock_now.strftime("%H:%M:%S.%f")[:-3]
        self.atomic_clock_label.setText(f"Clock ({clock_source}): {now_str}")
        self.ip_ping_label.setText(f"Local IP: {self.cached_ip} | Status: Active (OK)")
        
        try:
            clipboard_text = QApplication.clipboard().text()
            if clipboard_text:
                clean_text = clipboard_text.replace('\n', ' ')[:35]
                if len(clipboard_text) > 35:
                    clean_text += "..."
                self.clipboard_label.setText(f"Clipboard: \"{clean_text}\"")
            else:
                self.clipboard_label.setText("Clipboard: [empty]")
        except Exception as e:
            print(f"Clipboard error: {e}")

    def get_selected_path(self):
        index = self.file_tree.currentIndex()
        if index.isValid():
            return self.file_model.filePath(index)
        return ""

    def _get_target_directory(self):
        selected = self.get_selected_path()
        if not selected:
            last_selected = self.file_tree.last_selected_path
            if last_selected:
                return os.path.dirname(last_selected) or self.base_root_path
            return self.base_root_path
        if os.path.isdir(selected):
            return selected
        return os.path.dirname(selected) or self.base_root_path

    def create_new_file(self):
        target_dir = self._get_target_directory()
        name, ok = QInputDialog.getText(self, "New File", f"Enter a name for the new file in {target_dir}:")
        if ok and name:
            full_path = os.path.join(target_dir, name)
            try:
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write("")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create the file:\n{e}")

    def create_new_folder(self):
        target_dir = self._get_target_directory()
        name, ok = QInputDialog.getText(self, "New Folder", f"Enter a name for the new folder in {target_dir}:")
        if ok and name:
            full_path = os.path.join(target_dir, name)
            try:
                os.makedirs(full_path, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create the folder:\n{e}")

    def delete_selected_item(self):
        full_path = self.get_selected_path()
        if not full_path or os.path.abspath(full_path) == os.path.abspath(self.base_root_path):
            QMessageBox.warning(self, "Warning", f"Select a file or folder in {self.base_root_path} to delete.")
            return
        
        confirm = QMessageBox.question(
            self, 
            "Confirm Deletion",
            f"Are you sure you want to permanently delete:\n{full_path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not delete the item:\n{e}")

    def run_cmd_command(self):
        command = self.cmd_input.text().strip()
        if command:
            self.cmd_output.insertPlainText(f"{self.prompt_label.text()}{command}\n")
            full_cmd = command + "\n"
            self.cmd_process.write(full_cmd.encode(self.term_encoding, errors='replace'))
            self._request_terminal_directory()
            self.cmd_input.clear()

    def handle_cmd_stdout(self):
        data = self.cmd_process.readAllStandardOutput()
        text = bytes(data).decode(self.term_encoding, errors='ignore')
        self._show_terminal_output(text)
        self.cmd_output.verticalScrollBar().setValue(self.cmd_output.verticalScrollBar().maximum())

    def handle_cmd_stderr(self):
        data = self.cmd_process.readAllStandardError()
        text = bytes(data).decode(self.term_encoding, errors='ignore')
        self.cmd_output.insertPlainText(text)
        self.cmd_output.verticalScrollBar().setValue(self.cmd_output.verticalScrollBar().maximum())

    def navigate_to_url(self):
        url_text = self.url_input.text().strip()
        if not url_text.startswith("http://") and not url_text.startswith("https://"):
            url_text = "https://" + url_text
        self.browser_view.setUrl(QUrl(url_text))

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def update_usb_ui(self, usb_text):
        self.usb_label.setText(usb_text)

    def _get_initial_volume(self):
        try:
            if shutil.which("pactl"):
                res = subprocess.run(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True, text=True, errors="ignore"
                )
                match = re.search(r'(\d+)%', res.stdout)
                if match:
                    return min(100, int(match.group(1)))
            elif shutil.which("amixer"):
                res = subprocess.run(
                    ["amixer", "get", "Master"],
                    capture_output=True, text=True, errors="ignore"
                )
                match = re.search(r'\[(\d+)%\]', res.stdout)
                if match:
                    return min(100, int(match.group(1)))
        except Exception as e:
            print(f"Linux volume read error: {e}")
        return None

    def change_volume(self, value):
        self.vol_label.setText(f"System Volume: {value}%")
        try:
            if shutil.which("pactl"):
                subprocess.Popen(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            elif shutil.which("amixer"):
                subprocess.Popen(
                    ["amixer", "set", "Master", f"{value}%"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        except Exception as e:
            print(f"Linux volume change error: {e}")

    def trigger_shutdown(self):
        os.system("systemctl poweroff || shutdown -h now")
        self.panic_btn.setText("shutting down...")
        self.panic_btn.setEnabled(False)

    def _record_key_press(self):
        self.key_count += 1
        self.key_label.setText(f"Key Presses: {self.key_count}")

    def _record_mouse_click(self):
        self.click_count += 1
        self.click_timestamps.append(datetime.now())
        self.click_label.setText(f"Total Mouse Clicks: {self.click_count}")

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
            event_type = event.type()
            process_tables = (self.proc_table, self.proc_cpu_table, self.proc_gpu_table)
            is_process_table = any(
                table is watched or table.isAncestorOf(watched)
                for table in process_tables
            )

            if event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                click_target = QApplication.widgetAt(event.globalPosition().toPoint())
                if click_target is watched:
                    self._record_mouse_click()

            if is_process_table and event_type in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.ContextMenu,
                QEvent.Type.KeyPress,
            ):
                return True

            if event_type == QEvent.Type.KeyPress:
                focus_widget = QApplication.focusWidget()
                if focus_widget is watched or focus_widget is None:
                    self._record_key_press()

        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.ntp_worker.requestInterruption()
        self.ntp_worker.wait()
        self.sys_worker.stop()
        self.heavy_worker.stop()
        if hasattr(self, 'cmd_process') and self.cmd_process.state() != QProcess.ProcessState.NotRunning:
            self.cmd_process.terminate()
            self.cmd_process.waitForFinished(1000)
        event.accept()