import math
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QPointF, QMargins
from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis


class TacticalNetChart(QChartView):
    MAX_POINTS_HISTORY = 60

    def __init__(self, title, color_hex, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        self.series = QLineSeries()
        pen = QPen(QColor(color_hex))
        pen.setWidth(2)
        self.series.setPen(pen)
        
        self.chart = QChart()
        self.chart.addSeries(self.series)
        self.chart.legend().hide()
        self.chart.setBackgroundVisible(False)
        self.chart.setMargins(QMargins(0, 30, 0, 0))
        
        self.axis_x = QValueAxis()
        self.axis_x.setRange(0, self.MAX_POINTS_HISTORY)
        self.axis_x.setLabelFormat(" ") 
        self.axis_x.setTickCount(7)
        self.axis_x.setGridLineColor(QColor("#1a331a"))
        self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
        self.series.attachAxis(self.axis_x)
        
        self.axis_y = QValueAxis()
        self.axis_y.setRange(0, 100) 
        self.axis_y.setLabelFormat("%.1f")
        self.axis_y.setTickCount(5)
        self.axis_y.setGridLineColor(QColor("#1a331a"))
        self.axis_y.setLabelsColor(QColor("#00FF66"))
        self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
        self.series.attachAxis(self.axis_y)
        
        self.setChart(self.chart)
        self.setStyleSheet("background: transparent; border: 1px solid #1f331f; border-radius: 4px;")
        
        self.overlay_widget = QWidget(self)
        self.overlay_layout = QHBoxLayout(self.overlay_widget)
        self.overlay_layout.setContentsMargins(10, 5, 10, 0)
        
        self.lbl_title = QLabel()
        self.lbl_title.setText(f"<b>{title}</b>")
        self.lbl_title.setStyleSheet(f"color: {color_hex}; font-family: 'Consolas', 'Courier New', monospace; font-size: 9pt; border: none;")
        
        self.lbl_counter = QLabel("0.0 KB/s")
        self.lbl_counter.setStyleSheet(f"color: {color_hex}; font-family: 'Consolas', 'Courier New', monospace; font-size: 11pt; font-weight: bold; border: none;")
        self.lbl_counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.overlay_layout.addWidget(self.lbl_title)
        self.overlay_layout.addStretch()
        self.overlay_layout.addWidget(self.lbl_counter)
        
        self.overlay_widget.resize(self.width(), 30)
        
        self.data_points = []
        self.max_seen_speed = 10.0 

    def resizeEvent(self, event):
        self.overlay_widget.resize(self.width(), 30)
        super().resizeEvent(event)

    def format_speed(self, speed_kbs):
        if speed_kbs >= 1024:
            return f"{speed_kbs / 1024.0:.1f} MB/s"
        return f"{speed_kbs:.1f} KB/s"

    def update_data(self, speed_kbs):
        self.lbl_counter.setText(self.format_speed(speed_kbs))
        
        self.data_points.append(speed_kbs)
        
        if len(self.data_points) > self.MAX_POINTS_HISTORY + 1: 
            self.data_points.pop(0)
            
        new_points = []
        for i, point in enumerate(self.data_points):
            new_points.append(QPointF(i, point))
            
        self.series.replace(new_points)
            
        if speed_kbs > self.max_seen_speed:
            self.max_seen_speed = speed_kbs
            if self.max_seen_speed < 100:
                new_max = math.ceil(self.max_seen_speed / 10.0) * 10.0
            else:
                new_max = math.ceil(self.max_seen_speed / 100.0) * 100.0
            self.axis_y.setRange(0, new_max)
        elif self.max_seen_speed > 100 and max(self.data_points, default=0) < self.max_seen_speed * 0.5:
            self.max_seen_speed = max(max(self.data_points, default=0), 100.0)
            self.axis_y.setRange(0, self.max_seen_speed)