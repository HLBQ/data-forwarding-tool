import socket
import threading
import datetime
import json
import os
import time
import queue
from typing import Tuple, Dict, Any
from pathlib import Path

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
            "site_mapping": {
                "github.com": "Github"
            }
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

class AsyncLogger:  
    def __init__(self, log_file: str = "forwarder.log"):
        self.log_file = log_file
        self.log_queue = queue.Queue()
        self.running = True
        self.log_thread = threading.Thread(target=self._log_worker, daemon=True)
        self.log_thread.start()
    
    def _log_worker(self):
        while self.running:
            try:
                log_entry = self.log_queue.get(timeout=1)
                if log_entry is None:
                    break
                    
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(log_entry + '\n')
                except Exception as e:
                    print(f"写入日志文件错误: {e}")
                    
                self.log_queue.task_done()
            except queue.Empty:
                continue
    
    def log(self, message: str):
        if self.running:
            self.log_queue.put(message)
    
    def stop(self):
        self.running = False
        self.log_queue.put(None)
        self.log_thread.join(timeout=2)

class IPLogger:
    
    def __init__(self, ip_log_file: str = "forwarder_ips.log"):
        self.ip_log_file = ip_log_file
        self.ip_queue = queue.Queue()
        self.running = True
        
        self.ip_stats = {}  # ip -> {"count": 次数, "last_seen": 时间戳, "sites": set()}
        
        self.ip_thread = threading.Thread(target=self._ip_worker, daemon=True)
        self.ip_thread.start()
    
    def _ip_worker(self):
        while self.running:
            try:
                ip_entry = self.ip_queue.get(timeout=1)
                if ip_entry is None:
                    break
                
                ip_address, site_name = ip_entry
                
                if ip_address not in self.ip_stats:
                    self.ip_stats[ip_address] = {
                        "count": 1,
                        "last_seen": time.time(),
                        "sites": {site_name} if site_name else set()
                    }
                else:
                    self.ip_stats[ip_address]["count"] += 1
                    self.ip_stats[ip_address]["last_seen"] = time.time()
                    if site_name:
                        self.ip_stats[ip_address]["sites"].add(site_name)
                
                try:
                    with open(self.ip_log_file, 'a', encoding='utf-8') as f:
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if site_name:
                            f.write(f"{timestamp}|{ip_address}|{site_name}\n")
                        else:
                            f.write(f"{timestamp}|{ip_address}|unknown\n")
                except Exception as e:
                    print(f"写入IP日志文件错误: {e}")
                
                self.ip_queue.task_done()
            except queue.Empty:
                continue
    
    def log_ip(self, ip_address: str, site_name: str = None):
        if self.running:
            self.ip_queue.put((ip_address, site_name))
    
    def get_ip_stats(self) -> dict:
        return self.ip_stats.copy()
    
    def stop(self):
        self.running = False
        self.ip_queue.put(None)
        self.ip_thread.join(timeout=2)

class StatsCollector:
    
    def __init__(self, status_file: str = "forwarder_status.log"):
        self.status_file = status_file
        self.stats_queue = queue.Queue()
        self.running = True
        
        self.stats = {
            "total_upload_bytes": 0,
            "total_download_bytes": 0,
            "total_connections": 0,
            "current_upload_speed": 0,
            "current_download_speed": 0,
            "active_connections": 0,
            "start_time": time.time(),
            "last_update_time": time.time()
        }
        
        self.last_upload_bytes = 0
        self.last_download_bytes = 0
        self.last_speed_update = time.time()
        
        self.stats_thread = threading.Thread(target=self._stats_worker, daemon=True)
        self.stats_thread.start()
    
    def _write_status_log(self):
        try:
            with open(self.status_file, 'a', encoding='utf-8') as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                status_line = f"STATUS|{timestamp}"
                
                for key, value in self.stats.items():
                    status_line += f"|{key}={value}"
                
                f.write(status_line + '\n')
        except Exception as e:
            print(f"写入状态日志错误: {e}")
    
    def _stats_worker(self):
        while self.running:
            try:
                while not self.stats_queue.empty():
                    try:
                        stat_update = self.stats_queue.get_nowait()
                        if stat_update is None:
                            break
                            
                        for key, value in stat_update.items():
                            if key in self.stats:
                                if key in ["total_upload_bytes", "total_download_bytes"]:
                                    self.stats[key] += value
                                elif key == "active_connections":
                                    self.stats[key] = value
                                elif key == "total_connections":
                                    self.stats[key] = max(self.stats[key], value)
                                    
                        self.stats_queue.task_done()
                    except queue.Empty:
                        break
                
                current_time = time.time()
                time_diff = current_time - self.last_speed_update
                
                if time_diff >= 1.0:  
                    upload_diff = self.stats["total_upload_bytes"] - self.last_upload_bytes
                    download_diff = self.stats["total_download_bytes"] - self.last_download_bytes
                    
                    self.stats["current_upload_speed"] = upload_diff / time_diff
                    self.stats["current_download_speed"] = download_diff / time_diff
                    self.stats["last_update_time"] = current_time
                    
                    self.last_upload_bytes = self.stats["total_upload_bytes"]
                    self.last_download_bytes = self.stats["total_download_bytes"]
                    self.last_speed_update = current_time
                    
                    self._write_status_log()
                
                time.sleep(0.1) 
                
            except Exception as e:
                print(f"统计处理错误: {e}")
                time.sleep(1)
    
    def update_stats(self, stats_update: Dict[str, Any]):
        if self.running:
            self.stats_queue.put(stats_update)
    
    def get_stats(self) -> Dict[str, Any]:
        return self.stats.copy()
    
    def stop(self):
        self.running = False
        self.stats_queue.put(None)
        self.stats_thread.join(timeout=2)
        self._write_status_log()

class SimpleDataForwarder:
    def __init__(self, config: dict = None):
        if config is None:
            config_manager = ConfigManager()
            config = config_manager.load_config()
        
        self.listen_port = config.get("listen_port", 8070)
        self.target_host = config.get("target_host", "127.0.0.1")
        self.target_port = config.get("target_port", 114514)
        self.log_level = config.get("log_level", "INFO")
        self.max_connections = config.get("max_connections", 100)
        
        self.logger = AsyncLogger()
        self.stats_collector = StatsCollector()
        self.ip_logger = IPLogger() 
        
        self.running = False
        self.connection_count = 0
        self.active_connections = 0
        
        self.site_mapping = config.get("site_mapping", {})
        
        if config.get("auto_start", False):
            print("检测到自动启动配置，将在3秒后启动转发器...")
            time.sleep(3)
            self._auto_start()
    
    def _identify_site(self, target_host: str) -> str:
        try:
            
            socket.inet_aton(target_host)
            return target_host  
        except socket.error:
            pass  
        
        if target_host in self.site_mapping:
            return self.site_mapping[target_host]
        
        for domain, site_name in self.site_mapping.items():
            if target_host.endswith('.' + domain):
                return site_name
        
        return target_host
    
    def _auto_start(self):
        auto_thread = threading.Thread(target=self.start, daemon=True)
        auto_thread.start()
    
    def log_message(self, level: str, message: str):
        level_priority = {"ALL": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
        config_priority = level_priority.get(self.log_level, 1)
        msg_priority = level_priority.get(level, 1)
        
        if self.log_level == "ALL" or msg_priority >= config_priority:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [{level}] {message}"
            
            print(log_entry)
            
            self.logger.log(log_entry)
    
    def forward_data(self, source_socket: socket.socket, target_socket: socket.socket, 
                    direction: str, connection_id: int):

        total_bytes = 0
        packet_count = 0
        
        try:
            while self.running:
                data = source_socket.recv(4096)
                if not data:
                    break
                

                packet_count += 1
                total_bytes += len(data)
                

                if direction == "client->target":
                    self.stats_collector.update_stats({"total_upload_bytes": len(data)})
                else:  # target->client
                    self.stats_collector.update_stats({"total_download_bytes": len(data)})
                
                log_message = f"连接 {connection_id} | {direction} | 数据包 {packet_count} | 大小: {len(data)} 字节"
                threading.Thread(target=self.log_message, args=("INFO", log_message), daemon=True).start()
                
                target_socket.sendall(data)
                
        except Exception as e:
            error_msg = f"连接 {connection_id} | {direction} | 数据转发错误: {e}"
            threading.Thread(target=self.log_message, args=("ERROR", error_msg), daemon=True).start()
        finally:
            source_socket.close()
            target_socket.close()
            
            complete_msg = f"连接 {connection_id} | {direction} | 传输完成 | 总数据包: {packet_count} | 总字节数: {total_bytes} 字节"
            threading.Thread(target=self.log_message, args=("INFO", complete_msg), daemon=True).start()
    
    def handle_client(self, client_socket: socket.socket, client_address: Tuple[str, int]):
        self.connection_count += 1
        self.active_connections += 1
        connection_id = self.connection_count
        
        self.stats_collector.update_stats({
            "total_connections": self.connection_count,
            "active_connections": self.active_connections
        })
        

        site_name = self._identify_site(self.target_host)
        
        ip_address = client_address[0]
        threading.Thread(target=self.ip_logger.log_ip, args=(ip_address, site_name), daemon=True).start()
        
        conn_msg = f"连接 {connection_id} | 新连接来自: {client_address} | 访问: {site_name}"
        threading.Thread(target=self.log_message, args=("INFO", conn_msg), daemon=True).start()
        
        active_msg = f"活跃连接数: {self.active_connections}/{self.max_connections}"
        threading.Thread(target=self.log_message, args=("INFO", active_msg), daemon=True).start()
        
        try:
            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_socket.connect((self.target_host, self.target_port))
            
            conn_success_msg = f"连接 {connection_id} | 已连接到目标服务器: {self.target_host}:{self.target_port}"
            threading.Thread(target=self.log_message, args=("INFO", conn_success_msg), daemon=True).start()
            
            client_to_target = threading.Thread(
                target=self.forward_data, 
                args=(client_socket, target_socket, "client->target", connection_id)
            )
            target_to_client = threading.Thread(
                target=self.forward_data, 
                args=(target_socket, client_socket, "target->client", connection_id)
            )
            
            client_to_target.daemon = True
            target_to_client.daemon = True
            
            client_to_target.start()
            target_to_client.start()
            
            client_to_target.join()
            target_to_client.join()
            
        except Exception as e:
            error_msg = f"连接 {connection_id} | 处理客户端连接错误: {e}"
            threading.Thread(target=self.log_message, args=("ERROR", error_msg), daemon=True).start()
        finally:
            client_socket.close()
            self.active_connections -= 1
            
            self.stats_collector.update_stats({"active_connections": self.active_connections})
            
            close_msg = f"连接 {connection_id} | 连接关闭: {client_address}"
            threading.Thread(target=self.log_message, args=("INFO", close_msg), daemon=True).start()
            
            active_update_msg = f"活跃连接数: {self.active_connections}/{self.max_connections}"
            threading.Thread(target=self.log_message, args=("INFO", active_update_msg), daemon=True).start()
    
    def start(self):
        """
        启动数据转发器
        """
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('0.0.0.0', self.listen_port))
            server_socket.listen(self.max_connections)
            
            self.running = True
            
            start_msgs = [
                f"数据转发器已启动，监听端口: {self.listen_port}",
                f"目标服务器: {self.target_host}:{self.target_port}",
                f"最大连接数: {self.max_connections}",
                f"日志级别: {self.log_level}",
                "按 Ctrl+C 停止服务"
            ]
            
            for msg in start_msgs:
                threading.Thread(target=self.log_message, args=("INFO", msg), daemon=True).start()
            
            while self.running:
                try:
                    client_socket, client_address = server_socket.accept()
                    
                    if self.active_connections >= self.max_connections:
                        warning_msg = f"达到最大连接数限制: {self.max_connections}"
                        threading.Thread(target=self.log_message, args=("WARNING", warning_msg), daemon=True).start()
                        client_socket.close()
                        continue
                    
                    client_thread = threading.Thread(
                        target=self.handle_client, 
                        args=(client_socket, client_address)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        error_msg = f"接受连接错误: {e}"
                        threading.Thread(target=self.log_message, args=("ERROR", error_msg), daemon=True).start()
                    
        except KeyboardInterrupt:
            stop_msg = "\n正在停止数据转发器..."
            threading.Thread(target=self.log_message, args=("INFO", stop_msg), daemon=True).start()
        except Exception as e:
            error_msg = f"启动转发器错误: {e}"
            threading.Thread(target=self.log_message, args=("ERROR", error_msg), daemon=True).start()
        finally:
            self.running = False
            server_socket.close()
            
            self.logger.stop()
            self.stats_collector.stop()
            self.ip_logger.stop()  
            
            stop_final_msg = "数据转发器已停止"
            print(stop_final_msg)
            
            try:
                with open("forwarder.log", 'a', encoding='utf-8') as f:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] [INFO] {stop_final_msg}\n")
            except:
                pass

def main():
    
    config_manager = ConfigManager()
    config = config_manager.load_config()
    
    print("=" * 50)
    print("数据转发器")
    print("=" * 50)
    print(f"监听端口: {config['listen_port']}")
    print(f"目标服务器: {config['target_host']}:{config['target_port']}")
    print(f"最大连接数: {config['max_connections']}")
    print(f"日志级别: {config['log_level']}")
    print(f"自动启动: {'是' if config['auto_start'] else '否'}")
    print("=" * 50)
    
    if config.get("auto_start", False):
        print("自动启动已启用，转发器将在后台运行")
        print("使用GUI界面控制转发器或按Ctrl+C停止")
    else:
        print("启动中...")
    
    forwarder = SimpleDataForwarder(config)
    forwarder.start()

if __name__ == "__main__":
    main()
