import sys
import json
import os
import subprocess
import threading
import time
import psutil
from datetime import datetime
from pathlib import Path
from collections import deque

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QFormLayout,
    QTextEdit, QComboBox, QCheckBox, QMessageBox, QFrame, QSplitter,
    QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QPalette, QColor, QTextCursor

class LogManager:
    
    def __init__(self, log_file: str = "forwarder.log"):
        self.log_file = log_file
        
    def read_recent_logs(self, count: int = 100):
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    return lines[-count:] if len(lines) > count else lines
            else:
                return []
        except Exception as e:
            print(f"读取日志文件错误: {e}")
            return []
    
    def clear_log_file(self):
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write('')
        except Exception as e:
            print(f"清空日志文件错误: {e}")
    
    def get_log_file_size(self):
        try:
            if os.path.exists(self.log_file):
                return os.path.getsize(self.log_file)
            return 0
        except:
            return 0

class ForwarderThread(QThread):
    
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.forwarder = None
        
    def run(self):
        try:
            from data_forwarding_tool import SimpleDataForwarder
            
            self.running = True
            self.status_signal.emit("运行中")
            self.log_signal.emit(f"数据转发器启动")
            self.log_signal.emit(f"监听端口: {self.config['listen_port']}")
            self.log_signal.emit(f"目标服务器: {self.config['target_host']}:{self.config['target_port']}")
            
            self.forwarder = SimpleDataForwarder(self.config)
            
            forwarder_thread = threading.Thread(target=self.forwarder.start)
            forwarder_thread.daemon = True
            forwarder_thread.start()
            
            self.log_signal.emit("转发器已启动")
            
            while self.running:
                time.sleep(0.1)
                
        except Exception as e:
            self.log_signal.emit(f"错误: {str(e)}")
            self.status_signal.emit("错误")
        finally:
            self.running = False
            self.status_signal.emit("已停止")
            self.log_signal.emit(f"数据转发器已停止")
    
    
    def stop(self):
        self.running = False
        
        self.terminate()
        
        if self.forwarder:
            try:
                self.forwarder.running = False
            except:
                pass

class ConfigManager:
    
    def __init__(self, config_file: str = "forwarder_config.json"):
        self.config_file = config_file
        self.default_config = {
            "listen_port": 8070,
            "target_host": "127.0.0.1",
            "target_port": 114514,
            "auto_start": False,
            "log_level": "INFO",
            "max_connections": 100,
            "auto_open_ports": False,
            "clear_log_on_start": False
        }
    
    def load_config(self) -> dict:
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    for key in self.default_config:
                        if key not in config:
                            config[key] = self.default_config[key]
                    return config
            else:
                self.save_config(self.default_config)
                return self.default_config.copy()
        except Exception as e:
            print(f"加载配置文件错误: {e}")
            return self.default_config.copy()
    
    def save_config(self, config: dict) -> bool:
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存配置文件错误: {e}")
            return False

class ForwarderGUI(QMainWindow):
    
    def __init__(self):
        super().__init__()
        
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load_config()
        
        self.log_manager = LogManager()
        
        self.forwarder_thread = None
        
        self.stats = {
            "total_upload": 0,
            "total_download": 0,
            "current_speed_up": 0,
            "current_speed_down": 0,
            "active_connections": 0,
            "last_update_time": 0
        }
        
        self.init_ui()
        self.load_config_to_ui()
        self.setup_auto_save() 
        self.setWindowTitle("数据转发器")
        self.resize(1400, 1000)  
        self.setWindowState(Qt.WindowMaximized)  
        self.apply_gray_theme()
        self.load_recent_logs()
        if self.config.get("auto_start", False):
            QTimer.singleShot(2000, self.auto_start_forwarder)
        

        self.log_monitor_timer = QTimer()
        self.log_monitor_timer.timeout.connect(self.check_log_file_changes)
        self.log_monitor_timer.start(1000)  
        
        self.ip_stats_timer = QTimer()
        self.ip_stats_timer.timeout.connect(self.update_ip_stats)
        self.ip_stats_timer.start(2000)  
        
        self.system_stats_timer = QTimer()
        self.system_stats_timer.timeout.connect(self.update_system_stats)
        self.system_stats_timer.start(3000)  
        
        self.last_log_file_size = self.log_manager.get_log_file_size()
        
        self.ip_stats = {}
        self.update_ip_stats() 
        
        self.last_net_io = None
        self.last_net_time = time.time()
        self.update_system_stats()  
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        splitter = QSplitter(Qt.Horizontal)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        title_label = QLabel("操作")
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont("Arial", 18, QFont.Bold)
        title_label.setFont(title_font)
        left_layout.addWidget(title_label)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        left_layout.addWidget(separator)
        
        config_group = QGroupBox("转发配置")
        config_group.setFont(QFont("Arial", 10, QFont.Bold))
        config_layout = QFormLayout()
        config_layout.setSpacing(10)
        
        self.listen_port_input = QLineEdit()
        self.listen_port_input.setPlaceholderText("例如: 8070")
        config_layout.addRow("监听端口:", self.listen_port_input)
        
        self.target_host_input = QLineEdit()
        self.target_host_input.setPlaceholderText("例如: 127.0.0.1 或 example.com")
        config_layout.addRow("目标主机:", self.target_host_input)
        
        self.target_port_input = QLineEdit()
        self.target_port_input.setPlaceholderText("例如: 80, 443, 3306")
        config_layout.addRow("目标端口:", self.target_port_input)
        
        self.max_connections_input = QLineEdit()
        self.max_connections_input.setPlaceholderText("例如: 100")
        config_layout.addRow("最大连接数:", self.max_connections_input)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["ALL", "INFO", "WARNING", "ERROR"])
        config_layout.addRow("日志级别:", self.log_level_combo)
        
        self.auto_start_check = QCheckBox("启动时自动运行转发器")
        config_layout.addRow("", self.auto_start_check)
        
        self.auto_open_ports_check = QCheckBox("开启转发器时自动开放端口")
        config_layout.addRow("", self.auto_open_ports_check)
        
        self.clear_log_on_start_check = QCheckBox("每次启动转发器时清空日志")
        config_layout.addRow("", self.clear_log_on_start_check)
        
        config_group.setLayout(config_layout)
        left_layout.addWidget(config_group)

        control_group = QGroupBox("控制面板")
        control_group.setFont(QFont("Arial", 10, QFont.Bold))
        control_layout = QHBoxLayout()

        self.start_btn = QPushButton("启动转发器")
        self.start_btn.clicked.connect(self.start_forwarder)
        self.start_btn.setFixedHeight(40)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止转发器")
        self.stop_btn.clicked.connect(self.stop_forwarder)
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)
        
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        status_group = QGroupBox("系统状态")
        status_group.setFont(QFont("Arial", 10, QFont.Bold))
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setFont(QFont("Arial", 10))
        status_layout.addWidget(self.status_label)
        
        status_group.setLayout(status_layout)
        left_layout.addWidget(status_group)

        log_group = QGroupBox("系统日志")
        log_group.setFont(QFont("Arial", 10, QFont.Bold))
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setMinimumHeight(300) 
        log_layout.addWidget(self.log_text)

        log_control_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_control_layout.addWidget(self.clear_log_btn)
        
        self.reload_log_btn = QPushButton("重新加载日志")
        self.reload_log_btn.clicked.connect(self.load_recent_logs)
        log_control_layout.addWidget(self.reload_log_btn)
        
        log_control_layout.addStretch()
        log_layout.addLayout(log_control_layout)
        
        log_group.setLayout(log_layout)
        left_layout.addWidget(log_group)
        
        left_layout.addStretch()
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(15)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        right_title = QLabel("数据统计")
        right_title.setAlignment(Qt.AlignCenter)
        right_title_font = QFont("Arial", 16, QFont.Bold)
        right_title.setFont(right_title_font)
        right_layout.addWidget(right_title)
        
        right_separator = QFrame()
        right_separator.setFrameShape(QFrame.HLine)
        right_separator.setFrameShadow(QFrame.Sunken)
        right_layout.addWidget(right_separator)

        stats_group = QGroupBox("实时统计")
        stats_group.setFont(QFont("Arial", 10, QFont.Bold))
        stats_layout = QFormLayout()
        stats_layout.setSpacing(15)

        self.active_connections_label = QLabel("0")
        self.active_connections_label.setFont(QFont("Arial", 12, QFont.Bold))
        stats_layout.addRow("活跃连接数:", self.active_connections_label)

        self.total_upload_label = QLabel("0 字节")
        self.total_upload_label.setFont(QFont("Arial", 12))
        stats_layout.addRow("总上传数据:", self.total_upload_label)

        self.total_download_label = QLabel("0 字节")
        self.total_download_label.setFont(QFont("Arial", 12))
        stats_layout.addRow("总下载数据:", self.total_download_label)

        self.speed_up_label = QLabel("0 字节/秒")
        self.speed_up_label.setFont(QFont("Arial", 12))
        stats_layout.addRow("当前上传速度:", self.speed_up_label)

        self.speed_down_label = QLabel("0 字节/秒")
        self.speed_down_label.setFont(QFont("Arial", 12))
        stats_layout.addRow("当前下载速度:", self.speed_down_label)

        units_group = QGroupBox("数据单位")
        units_layout = QHBoxLayout()
        
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["字节", "KB", "MB", "GB"])
        self.unit_combo.currentTextChanged.connect(self.update_stats_display)
        units_layout.addWidget(QLabel("显示单位:"))
        units_layout.addWidget(self.unit_combo)
        units_layout.addStretch()
        
        units_group.setLayout(units_layout)
        stats_layout.addRow(units_group)

        update_time_group = QGroupBox("状态信息")
        update_time_layout = QFormLayout()
        
        self.update_time_label = QLabel("从未更新")
        self.update_time_label.setFont(QFont("Arial", 10))
        update_time_layout.addRow("最后更新时间:", self.update_time_label)
        
        update_time_group.setLayout(update_time_layout)
        stats_layout.addRow(update_time_group)
        
        stats_group.setLayout(stats_layout)
        right_layout.addWidget(stats_group)

        stats_control_group = QGroupBox("统计控制")
        stats_control_layout = QHBoxLayout()
        
        self.reset_stats_btn = QPushButton("重置统计")
        self.reset_stats_btn.clicked.connect(self.reset_stats)
        stats_control_layout.addWidget(self.reset_stats_btn)
        
        stats_control_group.setLayout(stats_control_layout)
        right_layout.addWidget(stats_control_group)

        ip_stats_group = QGroupBox("IP地址统计")
        ip_stats_group.setFont(QFont("Arial", 10, QFont.Bold))
        ip_stats_layout = QFormLayout()
        ip_stats_layout.setSpacing(10)

        self.total_ips_label = QLabel("0")
        self.total_ips_label.setFont(QFont("Arial", 12, QFont.Bold))
        ip_stats_layout.addRow("累计IP数量:", self.total_ips_label)

        self.today_ips_label = QLabel("0")
        self.today_ips_label.setFont(QFont("Arial", 12))
        ip_stats_layout.addRow("今日新增IP:", self.today_ips_label)

        self.recent_ips_label = QLabel("无")
        self.recent_ips_label.setFont(QFont("Arial", 10))
        self.recent_ips_label.setWordWrap(True)
        ip_stats_layout.addRow("最近连接IP:", self.recent_ips_label)

        ip_control_layout = QHBoxLayout()
        self.view_ip_log_btn = QPushButton("查看IP日志")
        self.view_ip_log_btn.clicked.connect(self.view_ip_log)
        ip_control_layout.addWidget(self.view_ip_log_btn)
        
        self.clear_ip_log_btn = QPushButton("清空IP日志")
        self.clear_ip_log_btn.clicked.connect(self.clear_ip_log)
        ip_control_layout.addWidget(self.clear_ip_log_btn)
        
        ip_stats_layout.addRow(ip_control_layout)
        
        ip_stats_group.setLayout(ip_stats_layout)
        right_layout.addWidget(ip_stats_group)

        system_stats_group = QGroupBox("系统状态监控")
        system_stats_group.setFont(QFont("Arial", 10, QFont.Bold))
        system_stats_layout = QFormLayout()
        system_stats_layout.setSpacing(12)

        cpu_layout = QHBoxLayout()
        self.cpu_label = QLabel("CPU使用率:")
        self.cpu_label.setFont(QFont("Arial", 11))
        cpu_layout.addWidget(self.cpu_label)
        
        self.cpu_percent_label = QLabel("0%")
        self.cpu_percent_label.setFont(QFont("Arial", 11, QFont.Bold))
        cpu_layout.addWidget(self.cpu_percent_label)
        cpu_layout.addStretch()
        
        self.cpu_progress = QProgressBar()
        self.cpu_progress.setRange(0, 100)
        self.cpu_progress.setValue(0)
        self.cpu_progress.setTextVisible(True)
        self.cpu_progress.setFixedHeight(20)
        system_stats_layout.addRow(cpu_layout)
        system_stats_layout.addRow(self.cpu_progress)

        memory_layout = QHBoxLayout()
        self.memory_label = QLabel("内存使用率:")
        self.memory_label.setFont(QFont("Arial", 11))
        memory_layout.addWidget(self.memory_label)
        
        self.memory_percent_label = QLabel("0%")
        self.memory_percent_label.setFont(QFont("Arial", 11, QFont.Bold))
        memory_layout.addWidget(self.memory_percent_label)
        memory_layout.addStretch()
        
        self.memory_progress = QProgressBar()
        self.memory_progress.setRange(0, 100)
        self.memory_progress.setValue(0)
        self.memory_progress.setTextVisible(True)
        self.memory_progress.setFixedHeight(20)
        system_stats_layout.addRow(memory_layout)
        system_stats_layout.addRow(self.memory_progress)

        network_layout = QHBoxLayout()
        self.network_label = QLabel("网络速度:")
        self.network_label.setFont(QFont("Arial", 11))
        network_layout.addWidget(self.network_label)
        
        self.network_speed_label = QLabel("上传: 0 KB/s | 下载: 0 KB/s")
        self.network_speed_label.setFont(QFont("Arial", 10))
        network_layout.addWidget(self.network_speed_label)
        network_layout.addStretch()
        
        system_stats_layout.addRow(network_layout)

        bandwidth_layout = QHBoxLayout()
        self.bandwidth_label = QLabel("带宽占用率:")
        self.bandwidth_label.setFont(QFont("Arial", 11))
        bandwidth_layout.addWidget(self.bandwidth_label)
        
        self.bandwidth_percent_label = QLabel("0%")
        self.bandwidth_percent_label.setFont(QFont("Arial", 11, QFont.Bold))
        bandwidth_layout.addWidget(self.bandwidth_percent_label)
        bandwidth_layout.addStretch()
        
        self.bandwidth_progress = QProgressBar()
        self.bandwidth_progress.setRange(0, 100)
        self.bandwidth_progress.setValue(0)
        self.bandwidth_progress.setTextVisible(True)
        self.bandwidth_progress.setFixedHeight(20)
        system_stats_layout.addRow(bandwidth_layout)
        system_stats_layout.addRow(self.bandwidth_progress)
        
        system_stats_group.setLayout(system_stats_layout)
        right_layout.addWidget(system_stats_group)
        
        right_layout.addStretch()
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([800, 400])  

        main_layout.addWidget(splitter)
    
    def apply_gray_theme(self):

        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(240, 240, 240))
        palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.Button, QColor(220, 220, 220))
        palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
        palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)
        

        button_style = """
            QPushButton {
                background-color: #E0E0E0;
                color: #000000;
                border: 1px solid #B0B0B0;
                border-radius: 0px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D0D0D0;
                border: 1px solid #909090;
            }
            QPushButton:pressed {
                background-color: #C0C0C0;
            }
            QPushButton:disabled {
                background-color: #F0F0F0;
                color: #808080;
            }
        """
        
        line_edit_style = """
            QLineEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #B0B0B0;
                border-radius: 0px;
                padding: 5px;
            }
            QLineEdit:focus {
                border: 1px solid #0078D7;
            }
        """
        
        text_edit_style = """
            QTextEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #B0B0B0;
                border-radius: 0px;
                font-family: Consolas, monospace;
            }
        """
        
        combo_box_style = """
            QComboBox {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #B0B0B0;
                border-radius: 0px;
                padding: 5px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #B0B0B0;
                selection-background-color: #0078D7;
                selection-color: #FFFFFF;
            }
        """
        
        group_box_style = """
            QGroupBox {
                color: #000000;
                border: 2px solid #B0B0B0;
                border-radius: 0px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                background-color: #FFFFFF;
            }
        """
        self.setStyleSheet(f"""
            {button_style}
            {line_edit_style}
            {text_edit_style}
            {combo_box_style}
            {group_box_style}
            
            QLabel {{
                color: #000000;
            }}
            
            QCheckBox {{
                color: #000000;
            }}
            
            QCheckBox::indicator {{
                width: 13px;
                height: 13px;
                border: 1px solid #B0B0B0;
                border-radius: 0px;
            }}
            
            QCheckBox::indicator:checked {{
                background-color: #0078D7;
                image: url(:/images/checkmark.png);
            }}
            
            QFrame {{
                color: #000000;
            }}
        """)
    
    def load_config_to_ui(self):
        self.listen_port_input.setText(str(self.config.get("listen_port", 8070)))
        self.target_host_input.setText(self.config.get("target_host", "127.0.0.1"))
        self.target_port_input.setText(str(self.config.get("target_port", 114514)))
        self.max_connections_input.setText(str(self.config.get("max_connections", 100)))
        
        log_level = self.config.get("log_level", "INFO")
        index = self.log_level_combo.findText(log_level)
        if index >= 0:
            self.log_level_combo.setCurrentIndex(index)
        
        self.auto_start_check.setChecked(self.config.get("auto_start", False))
        self.auto_open_ports_check.setChecked(self.config.get("auto_open_ports", False))
        self.clear_log_on_start_check.setChecked(self.config.get("clear_log_on_start", False))
    
    def setup_auto_save(self):
        self.listen_port_input.textChanged.connect(self.auto_save_config)
        self.target_host_input.textChanged.connect(self.auto_save_config)
        self.target_port_input.textChanged.connect(self.auto_save_config)
        self.max_connections_input.textChanged.connect(self.auto_save_config)
        self.log_level_combo.currentTextChanged.connect(self.auto_save_config)
        self.auto_start_check.stateChanged.connect(self.auto_save_config)
        self.auto_open_ports_check.stateChanged.connect(self.auto_save_config)
        self.clear_log_on_start_check.stateChanged.connect(self.auto_save_config)
    
    def auto_save_config(self):
        try:
            config = {
                "listen_port": int(self.listen_port_input.text()) if self.listen_port_input.text() else 8070,
                "target_host": self.target_host_input.text() if self.target_host_input.text() else "127.0.0.1",
                "target_port": int(self.target_port_input.text()) if self.target_port_input.text() else 114514,
                "max_connections": int(self.max_connections_input.text()) if self.max_connections_input.text() else 100,
                "log_level": self.log_level_combo.currentText(),
                "auto_start": self.auto_start_check.isChecked(),
                "auto_open_ports": self.auto_open_ports_check.isChecked(),
                "clear_log_on_start": self.clear_log_on_start_check.isChecked()
            }
            
            if config["listen_port"] < 1 or config["listen_port"] > 65535:
                return  
            
            if config["target_port"] < 1 or config["target_port"] > 65535:
                return 
            
            if config["max_connections"] < 1 or config["max_connections"] > 1000:
                return  
            
            if self.config_manager.save_config(config):
                self.config = config
            else:
                pass
                
        except ValueError:
            pass
        except Exception:
            pass
    
    def save_config(self):
        try:
            config = {
                "listen_port": int(self.listen_port_input.text()),
                "target_host": self.target_host_input.text(),
                "target_port": int(self.target_port_input.text()),
                "max_connections": int(self.max_connections_input.text()),
                "log_level": self.log_level_combo.currentText(),
                "auto_start": self.auto_start_check.isChecked(),
                "auto_open_ports": self.auto_open_ports_check.isChecked(),
                "clear_log_on_start": self.clear_log_on_start_check.isChecked()
            }
            
            if config["listen_port"] < 1 or config["listen_port"] > 65535:
                self.log_message("配置错误: 监听端口必须在1-65535之间")
                return
            
            if config["target_port"] < 1 or config["target_port"] > 65535:
                self.log_message("配置错误: 目标端口必须在1-65535之间")
                return
            
            if config["max_connections"] < 1 or config["max_connections"] > 1000:
                self.log_message("配置错误: 最大连接数必须在1-1000之间")
                return
            
            if self.config_manager.save_config(config):
                self.config = config
                self.log_message("配置已保存")
            else:
                self.log_message("保存配置失败")
                
        except ValueError as e:
            self.log_message("配置错误: 请输入有效的数字")
        except Exception as e:
            self.log_message(f"保存配置时发生错误: {str(e)}")
    
    def check_port_rule_exists(self, port):
        try:
            check_cmd = f'netsh advfirewall firewall show rule name="Forwarder Port {port}"'
            result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            
            if "没有规则" in result.stdout or "No rules" in result.stdout:
                return False
            else:
                if f"Forwarder Port {port}" in result.stdout:
                    return True
                else:
                    return "other_rule"
        except Exception as e:
            self.log_message(f"检查端口规则失败: {str(e)}")
            return False
    
    def open_port_in_firewall(self, port, protocol="TCP"):
        try:
            rule_status = self.check_port_rule_exists(port)
            
            if rule_status is False:
                rule_cmd = f'netsh advfirewall firewall add rule name="Forwarder Port {port}" dir=in action=allow protocol={protocol} localport={port}'
                result = subprocess.run(rule_cmd, shell=True, capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.log_message(f"已在防火墙中开放端口 {port}/{protocol}")
                    return True  
                else:
                    self.log_message(f"开放端口 {port} 失败: {result.stderr}")
                    return False
            elif rule_status is True:
                self.log_message(f"端口 {port} 的防火墙规则已存在")
                return False  
            else:
                self.log_message(f"端口 {port} 已有其他防火墙规则，跳过创建")
                return False 
        except Exception as e:
            self.log_message(f"开放端口 {port} 失败: {str(e)}")
            return False
    
    def close_port_in_firewall(self, port):
        try:
            rule_status = self.check_port_rule_exists(port)
            
            if rule_status is True:
                delete_cmd = f'netsh advfirewall firewall delete rule name="Forwarder Port {port}"'
                result = subprocess.run(delete_cmd, shell=True, capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.log_message(f"已从防火墙中删除端口 {port} 的规则")
                    return True
                else:
                    self.log_message(f"删除端口 {port} 规则失败: {result.stderr}")
                    return False
            else:
                if rule_status is False:
                    self.log_message(f"端口 {port} 的防火墙规则不存在，无需删除")
                else:
                    self.log_message(f"端口 {port} 的防火墙规则不是由本程序创建，保留原规则")
                return False
        except Exception as e:
            self.log_message(f"关闭端口 {port} 失败: {str(e)}")
            return False
    
    def start_forwarder(self):
        if self.forwarder_thread and self.forwarder_thread.isRunning():
            self.log_message("警告: 转发器已在运行中")
            return
        
        try:
            self.save_config()
            if self.config.get("clear_log_on_start", False):
                self.log_manager.clear_log_file()
                self.log_text.clear()
                self.last_log_file_size = 0
                self.log_message("已清空日志文件")
            
            port_opened = False
            if self.config.get("auto_open_ports", False):
                listen_port = self.config.get("listen_port", 8070)
                self.log_message(f"正在尝试自动开放端口 {listen_port}...")
                port_opened = self.open_port_in_firewall(listen_port)
                if port_opened:
                    self.log_message(f"端口 {listen_port} 已成功开放（创建了新规则）")
                else:
                    self.log_message(f"端口 {listen_port} 开放失败或规则已存在，转发器将继续运行")
            
            self.forwarder_thread = ForwarderThread(self.config)
            self.forwarder_thread.log_signal.connect(self.log_message)
            self.forwarder_thread.status_signal.connect(self.update_status)
            self.forwarder_thread.start()
            
            self.port_was_opened = port_opened
            self.current_listen_port = self.config.get("listen_port", 8070)

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)

            self.log_message("正在启动数据转发器...")
            
        except Exception as e:
            self.log_message(f"启动转发器时发生错误: {str(e)}")
    
    def stop_forwarder(self):
        if self.forwarder_thread and self.forwarder_thread.isRunning():
            self.forwarder_thread.stop()
            self.forwarder_thread.wait()

            if hasattr(self, 'port_was_opened') and self.port_was_opened:
                if hasattr(self, 'current_listen_port'):
                    self.log_message(f"正在关闭端口 {self.current_listen_port}（删除防火墙规则）...")
                    if self.close_port_in_firewall(self.current_listen_port):
                        self.log_message(f"端口 {self.current_listen_port} 已成功关闭")
                    else:
                        self.log_message(f"端口 {self.current_listen_port} 关闭失败")
            
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

            self.log_message("数据转发器已停止")
    
    def update_status(self, status):
        self.status_label.setText(f"状态: {status}")
    
    def update_stats(self, stats):
        self.stats = stats
        self.update_stats_display()

    def update_stats_display(self):
        unit = self.unit_combo.currentText()
        
        if unit == "字节":
            upload = self.stats["total_upload"]
            download = self.stats["total_download"]
            speed_up = self.stats["current_speed_up"]
            speed_down = self.stats["current_speed_down"]
            upload_text = f"{upload:,} 字节"
            download_text = f"{download:,} 字节"
            speed_up_text = f"{speed_up:,} 字节/秒"
            speed_down_text = f"{speed_down:,} 字节/秒"
        elif unit == "KB":
            upload = self.stats["total_upload"] / 1024
            download = self.stats["total_download"] / 1024
            speed_up = self.stats["current_speed_up"] / 1024
            speed_down = self.stats["current_speed_down"] / 1024
            upload_text = f"{upload:,.2f} KB"
            download_text = f"{download:,.2f} KB"
            speed_up_text = f"{speed_up:,.2f} KB/秒"
            speed_down_text = f"{speed_down:,.2f} KB/秒"
        elif unit == "MB":
            upload = self.stats["total_upload"] / (1024 * 1024)
            download = self.stats["total_download"] / (1024 * 1024)
            speed_up = self.stats["current_speed_up"] / (1024 * 1024)
            speed_down = self.stats["current_speed_down"] / (1024 * 1024)
            upload_text = f"{upload:,.2f} MB"
            download_text = f"{download:,.2f} MB"
            speed_up_text = f"{speed_up:,.2f} MB/秒"
            speed_down_text = f"{speed_down:,.2f} MB/秒"
        else:  
            upload = self.stats["total_upload"] / (1024 * 1024 * 1024)
            download = self.stats["total_download"] / (1024 * 1024 * 1024)
            speed_up = self.stats["current_speed_up"] / (1024 * 1024 * 1024)
            speed_down = self.stats["current_speed_down"] / (1024 * 1024 * 1024)
            upload_text = f"{upload:,.3f} GB"
            download_text = f"{download:,.3f} GB"
            speed_up_text = f"{speed_up:,.3f} GB/秒"
            speed_down_text = f"{speed_down:,.3f} GB/秒"
        
        self.active_connections_label.setText(str(self.stats["active_connections"]))
        self.total_upload_label.setText(upload_text)
        self.total_download_label.setText(download_text)
        self.speed_up_label.setText(speed_up_text)
        self.speed_down_label.setText(speed_down_text)

        last_update_time = self.stats.get("last_update_time", 0)
        if last_update_time > 0:
            try:
                update_time = datetime.fromtimestamp(last_update_time)
                time_str = update_time.strftime("%Y-%m-%d %H:%M:%S")
                self.update_time_label.setText(time_str)
            except Exception as e:
                self.update_time_label.setText(f"时间格式错误: {last_update_time}")
        else:
            self.update_time_label.setText("从未更新")
    
    def reset_stats(self):
        self.stats = {
            "total_upload": 0,
            "total_download": 0,
            "current_speed_up": 0,
            "current_speed_down": 0,
            "active_connections": 0
        }
        self.update_stats_display()
        self.log_message("统计数据已重置")
    
    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_text.append(log_entry)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()

        try:
            with open("forwarder.log", 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [GUI] {message}\n")
        except Exception as e:
            print(f"写入GUI日志错误: {e}")
    
    def load_recent_logs(self):
        self.log_text.clear()
        recent_logs = self.log_manager.read_recent_logs(100)
        for log in recent_logs:
            self.log_text.append(log)
        self.log_message("已加载最近日志")
    
    def auto_start_forwarder(self):
        if self.config.get("auto_start", False):
            self.log_message("检测到自动启动配置，正在启动转发器...")
            self.start_forwarder()
    
    def update_stats_from_file(self):
        status_file = "forwarder_status.log"
        
        try:
            if not os.path.exists(status_file):
                self.stats = {
                    "total_upload": 0,
                    "total_download": 0,
                    "current_speed_up": 0,
                    "current_speed_down": 0,
                    "active_connections": 0,
                    "last_update_time": 0
                }
                self.update_stats_display()
                return
            
            lines = []
            try:
                with open(status_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except IOError as e:
                time.sleep(0.01)
                try:
                    with open(status_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                except:
                    self.stats = {
                        "total_upload": 0,
                        "total_download": 0,
                        "current_speed_up": 0,
                        "current_speed_down": 0,
                        "active_connections": 0,
                        "last_update_time": 0
                    }
                    self.update_stats_display()
                    return
            
            latest_status_line = None
            for line in reversed(lines):
                if line.startswith("STATUS|"):
                    latest_status_line = line.strip()
                    break
            
            if not latest_status_line:
                self.stats = {
                    "total_upload": 0,
                    "total_download": 0,
                    "current_speed_up": 0,
                    "current_speed_down": 0,
                    "active_connections": 0,
                    "last_update_time": 0
                }
                self.update_stats_display()
                return
            
            parts = latest_status_line.split('|')
            if len(parts) < 3:
                self.stats = {
                    "total_upload": 0,
                    "total_download": 0,
                    "current_speed_up": 0,
                    "current_speed_down": 0,
                    "active_connections": 0,
                    "last_update_time": 0
                }
                self.update_stats_display()
                return
            
            stats = {}
            for part in parts[2:]: 
                if '=' in part:
                    key, value = part.split('=', 1)
                    try:
                        if '.' in value:
                            stats[key] = float(value)
                        else:
                            stats[key] = int(value)
                    except ValueError:
                        stats[key] = value
            
            self.stats = {
                "total_upload": stats.get("total_upload_bytes", 0),
                "total_download": stats.get("total_download_bytes", 0),
                "current_speed_up": stats.get("current_upload_speed", 0),
                "current_speed_down": stats.get("current_download_speed", 0),
                "active_connections": stats.get("active_connections", 0),
                "last_update_time": stats.get("last_update_time", 0)
            }
            
            self.update_stats_display()
            
        except Exception as e:
            self.stats = {
                "total_upload": 0,
                "total_download": 0,
                "current_speed_up": 0,
                "current_speed_down": 0,
                "active_connections": 0,
                "last_update_time": 0
            }
            self.update_stats_display()
    
    def check_log_file_changes(self):
        try:
            self.update_stats_from_file()
            
            current_size = self.log_manager.get_log_file_size()
            if current_size != self.last_log_file_size:
                new_bytes = current_size - self.last_log_file_size
                if new_bytes < 0:
                    self.load_recent_logs()
                else:
                    try:
                        if os.path.exists("forwarder.log"):
                            with open("forwarder.log", 'r', encoding='utf-8') as f:
                                if self.last_log_file_size > 0:
                                    f.seek(self.last_log_file_size)
                                
                                new_content = f.read(new_bytes)
                                if new_content:
                                    lines = new_content.strip().split('\n')
                                    for line in lines:
                                        if line.strip():  
                                            self.log_text.append(line)
                                    
                                    cursor = self.log_text.textCursor()
                                    cursor.movePosition(QTextCursor.End)
                                    self.log_text.setTextCursor(cursor)
                                    self.log_text.ensureCursorVisible()
                    except Exception as e:
                        print(f"读取新增日志错误: {e}")
                
                self.last_log_file_size = current_size
        except Exception as e:
            print(f"检查日志文件变化错误: {e}")
    
    def clear_log(self):
        self.log_manager.clear_log_file()
        self.log_text.clear()
        self.last_log_file_size = 0 
        self.log_message("日志已清空")
    
    def update_ip_stats(self):
        try:
            ip_log_file = "forwarder_ips.log"
            if not os.path.exists(ip_log_file):
                self.ip_stats = {}
                self.total_ips_label.setText("0")
                self.today_ips_label.setText("0")
                self.recent_ips_label.setText("无")
                return
            
            with open(ip_log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            ip_stats = {}
            today = datetime.now().strftime("%Y-%m-%d")
            today_ips = set()
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('|')
                if len(parts) >= 3:
                    timestamp_str, ip_address, site_name = parts[0], parts[1], parts[2]
                    
                    if ip_address not in ip_stats:
                        ip_stats[ip_address] = {
                            "count": 1,
                            "last_seen": timestamp_str,
                            "sites": {site_name}
                        }
                    else:
                        ip_stats[ip_address]["count"] += 1
                        ip_stats[ip_address]["last_seen"] = timestamp_str
                        ip_stats[ip_address]["sites"].add(site_name)
                    
                    if timestamp_str.startswith(today):
                        today_ips.add(ip_address)
            
            self.ip_stats = ip_stats

            total_ips = len(ip_stats)
            today_ip_count = len(today_ips)
            
            self.total_ips_label.setText(str(total_ips))
            self.today_ips_label.setText(str(today_ip_count))
            
            if ip_stats:
                sorted_ips = sorted(ip_stats.items(), 
                                  key=lambda x: x[1]["last_seen"], 
                                  reverse=True)
                
                recent_text = ""
                for i, (ip, stats) in enumerate(sorted_ips[:1]):
                    sites = ", ".join(stats["sites"])
                    recent_text += f"{ip} (访问{stats['count']}次, 站点: {sites})\n"
                
                self.recent_ips_label.setText(recent_text.strip())
            else:
                self.recent_ips_label.setText("无")
                
        except Exception as e:
            print(f"更新IP统计错误: {e}")
            self.total_ips_label.setText("0")
            self.today_ips_label.setText("0")
            self.recent_ips_label.setText("无")
    
    def view_ip_log(self):
        try:
            ip_log_file = "forwarder_ips.log"
            if not os.path.exists(ip_log_file):
                self.log_message("IP日志文件不存在")
                return
            
            with open(ip_log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            recent_lines = lines[-50:] if len(lines) > 50 else lines
            
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
            
            dialog = QDialog(self)
            dialog.setWindowTitle("IP日志查看器")
            dialog.resize(800, 600)
            
            layout = QVBoxLayout(dialog)
            
            log_text = QTextEdit()
            log_text.setReadOnly(True)
            log_text.setFont(QFont("Consolas", 9))
            
            for line in recent_lines:
                log_text.append(line.strip())
            
            layout.addWidget(log_text)
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.close)
            layout.addWidget(close_btn)
            
            dialog.exec_()
            
        except Exception as e:
            self.log_message(f"查看IP日志错误: {str(e)}")
    
    def clear_ip_log(self):
        try:
            ip_log_file = "forwarder_ips.log"
            if os.path.exists(ip_log_file):
                with open(ip_log_file, 'w', encoding='utf-8') as f:
                    f.write('')
                
                self.ip_stats = {}
                self.total_ips_label.setText("0")
                self.today_ips_label.setText("0")
                self.recent_ips_label.setText("无")
                
                self.log_message("IP日志已清空")
            else:
                self.log_message("IP日志文件不存在")
                
        except Exception as e:
            self.log_message(f"清空IP日志错误: {str(e)}")
    
    def update_system_stats(self):
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_percent_label.setText(f"{cpu_percent:.1f}%")
            self.cpu_progress.setValue(int(cpu_percent))
            
            if cpu_percent < 50:
                self.cpu_progress.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")  # 绿色
            elif cpu_percent < 80:
                self.cpu_progress.setStyleSheet("QProgressBar::chunk { background-color: #FFC107; }")  # 黄色
            else:
                self.cpu_progress.setStyleSheet("QProgressBar::chunk { background-color: #F44336; }")  # 红色
            
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_gb = memory.used / (1024**3)
            memory_total_gb = memory.total / (1024**3)
            
            self.memory_percent_label.setText(f"{memory_percent:.1f}% ({memory_used_gb:.1f} GB / {memory_total_gb:.1f} GB)")
            self.memory_progress.setValue(int(memory_percent))

            if memory_percent < 70:
                self.memory_progress.setStyleSheet("QProgressBar::chunk { background-color: #2196F3; }")  # 蓝色
            elif memory_percent < 85:
                self.memory_progress.setStyleSheet("QProgressBar::chunk { background-color: #FFC107; }")  # 黄色
            else:
                self.memory_progress.setStyleSheet("QProgressBar::chunk { background-color: #F44336; }")  # 红色

            current_time = time.time()
            current_net_io = psutil.net_io_counters()
            
            if self.last_net_io is not None:
                time_diff = current_time - self.last_net_time
                if time_diff > 0:
                    system_upload_speed = (current_net_io.bytes_sent - self.last_net_io.bytes_sent) / time_diff
                    system_download_speed = (current_net_io.bytes_recv - self.last_net_io.bytes_recv) / time_diff
                    
                    system_upload_speed_kb = system_upload_speed / 1024
                    system_download_speed_kb = system_download_speed / 1024
                    
                    self.network_speed_label.setText(f"上传: {system_upload_speed_kb:.1f} KB/s | 下载: {system_download_speed_kb:.1f} KB/s")

                    system_total_speed = system_upload_speed + system_download_speed

                    program_upload_speed = self.stats.get("current_speed_up", 0)
                    program_download_speed = self.stats.get("current_speed_down", 0)
                    program_total_speed = program_upload_speed + program_download_speed

                    if system_total_speed > 0:
                        bandwidth_percent = (program_total_speed / system_total_speed) * 100
                    else:
                        bandwidth_percent = 0

                    bandwidth_percent = max(0, min(100, bandwidth_percent))

                    self.bandwidth_percent_label.setText(f"{bandwidth_percent:.1f}%")
                    self.bandwidth_progress.setValue(int(bandwidth_percent))

                    if bandwidth_percent < 30:
                        self.bandwidth_progress.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")  # 绿色
                    elif bandwidth_percent < 70:
                        self.bandwidth_progress.setStyleSheet("QProgressBar::chunk { background-color: #FFC107; }")  # 黄色
                    else:
                        self.bandwidth_progress.setStyleSheet("QProgressBar::chunk { background-color: #F44336; }")  # 红色
                else:
                    self.network_speed_label.setText("上传: 0 KB/s | 下载: 0 KB/s")
                    self.bandwidth_percent_label.setText("0%")
                    self.bandwidth_progress.setValue(0)
                    self.bandwidth_progress.setStyleSheet("QProgressBar::chunk { background-color: #9E9E9E; }")  # 灰色
            else:
                self.network_speed_label.setText("上传: 0 KB/s | 下载: 0 KB/s")
                self.bandwidth_percent_label.setText("0%")
                self.bandwidth_progress.setValue(0)
                self.bandwidth_progress.setStyleSheet("QProgressBar::chunk { background-color: #9E9E9E; }")  # 灰色

            self.last_net_io = current_net_io
            self.last_net_time = current_time
                
        except Exception as e:
            self.cpu_percent_label.setText("错误")
            self.memory_percent_label.setText("错误")
            self.network_speed_label.setText("上传: 错误 | 下载: 错误")
            self.bandwidth_percent_label.setText("错误")

            self.cpu_progress.setStyleSheet("QProgressBar::chunk { background-color: #9E9E9E; }")
            self.memory_progress.setStyleSheet("QProgressBar::chunk { background-color: #9E9E9E; }")
            self.bandwidth_progress.setStyleSheet("QProgressBar::chunk { background-color: #9E9E9E; }")

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ForwarderGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
