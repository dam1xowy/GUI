import os
import subprocess
import psutil
from PyQt6.QtCore import QThread, pyqtSignal

class SystemMonitorWorker(QThread):
    cpu_data_ready = pyqtSignal(list)
    ram_data_ready = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True

    def run(self):
        while self.is_running:
            cpu_usages = psutil.cpu_percent(percpu=True, interval=0.5) 
            self.cpu_data_ready.emit(cpu_usages)
            
            ram = psutil.virtual_memory()
            self.ram_data_ready.emit(ram)
            
            self.msleep(500)

    def stop(self):
        self.is_running = False
        self.wait()


class HeavyTasksWorker(QThread):
    disks_data_ready = pyqtSignal(str)
    processes_data_ready = pyqtSignal(list, list) 
    gpu_data_ready = pyqtSignal(list)
    usb_data_ready = pyqtSignal(str) 
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True
        self.loop_counter = 0

    def run(self):
        self._scan_usb()

        while self.is_running:
            self._scan_disks()
            self._scan_processes()
            self._scan_gpu()
            
            self.loop_counter += 1
            if self.loop_counter >= 3:
                self._scan_usb()
                self.loop_counter = 0
            
            self.sleep(4)

    def _scan_disks(self):
        try:
            partitions = psutil.disk_partitions()
            disk_texts = []
            for p in partitions:
                if 'fixed' in p.opts.lower():
                    try:
                        u = psutil.disk_usage(p.mountpoint)
                        disk_texts.append(f"[{p.device}] {u.percent}%")
                    except PermissionError:
                        continue
            self.disks_data_ready.emit(" | ".join(disk_texts[:3]))
        except Exception as e:
            print(f"Błąd odczytu dysków: {e}")

    def _scan_processes(self):
        try:
            procs_ram = []
            procs_cpu = []
            for p in psutil.process_iter(['name', 'memory_info', 'cpu_percent']):
                try:
                    name = p.info.get('name', '')
                    if not name or 'idle' in name.lower() or 'system' in name.lower():
                        continue
                    
                    mem_rss = p.info.get('memory_info')
                    if mem_rss:
                        mem_mb = mem_rss.rss / (1024 * 1024)
                        procs_ram.append((name, mem_mb))
                        
                    cpu_usage = p.info.get('cpu_percent', 0.0)
                    if cpu_usage is not None:
                        procs_cpu.append((name, cpu_usage))
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            procs_ram = sorted(procs_ram, key=lambda x: x[1], reverse=True)[:3]
            procs_cpu = sorted(procs_cpu, key=lambda x: x[1], reverse=True)[:3]
            self.processes_data_ready.emit(procs_ram, procs_cpu)
        except Exception as e:
             print(f"Błąd skanowania procesów: {e}")

    def _scan_gpu(self):
        try:
            gpu_procs = []
            nvsmi_path = r"C:\Windows\System32\nvidia-smi.exe"
            if not os.path.exists(nvsmi_path):
                nvsmi_path = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
            
            cmd = f'"{nvsmi_path}" pmon -c 1'
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='ignore')
            
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 8:
                        sm_usage_str = parts[3]
                        if sm_usage_str.isdigit():
                            sm_usage = int(sm_usage_str)
                            if sm_usage > 0:
                                raw_name = " ".join(parts[7:])
                                name = raw_name.lstrip("- ")
                                gpu_procs.append((name, sm_usage))
            
            aggr_procs = {}
            for name, usage in gpu_procs:
                aggr_procs[name] = aggr_procs.get(name, 0) + usage
                
            final_procs = sorted(aggr_procs.items(), key=lambda x: x[1], reverse=True)[:3]
            self.gpu_data_ready.emit(final_procs)
        except Exception as e:
            print(f"Błąd odczytu GPU: {e}")
            self.gpu_data_ready.emit([])

    def _scan_usb(self):
        try:
            cmd = "powershell \"Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match '^USB' -and $_.FriendlyName -notmatch 'Hub|Composite|Root|Kontroler'} | Select-Object -ExpandProperty FriendlyName -Unique\""
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(cmd, capture_output=True, text=True, shell=True, encoding='cp850', errors='ignore', startupinfo=startupinfo)
            
            devices = []
            for line in result.stdout.split('\n'):
                name = line.strip()
                if name and name not in devices:
                    devices.append(name)
            
            if not devices:
                self.usb_data_ready.emit("USB: Brak zewnętrznych urządzeń")
                return
                
            dev_summary = ", ".join(devices[:3])
            if len(devices) > 3:
                dev_summary += f" (+{len(devices)-3} inne)"
                
            self.usb_data_ready.emit(f"USB: {dev_summary}")
        except Exception as e:
            print(f"Błąd odczytu USB: {e}")
            self.usb_data_ready.emit("USB: Odczyt niedostępny")

    def stop(self):
        self.is_running = False
        self.wait()