import os
import sys
import glob
import shutil
import subprocess
import socket
import struct
import time
import psutil
from PyQt6.QtCore import QThread, pyqtSignal


class NtpSyncWorker(QThread):
    sync_ready = pyqtSignal(float, float)
    sync_failed = pyqtSignal()
    NTP_UNIX_OFFSET = 2208988800
    SERVERS = ("time.cloudflare.com", "pool.ntp.org", "time.google.com")

    @staticmethod
    def _read_timestamp(packet, offset):
        seconds, fraction = struct.unpack_from("!II", packet, offset)
        return seconds - NtpSyncWorker.NTP_UNIX_OFFSET + fraction / 2**32

    def run(self):
        for server in self.SERVERS:
            if self.isInterruptionRequested():
                return
            try:
                address = socket.getaddrinfo(server, 123, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
                packet = bytearray(48)
                packet[0] = 0x23

                sent_at = time.time()
                ntp_sent_at = sent_at + self.NTP_UNIX_OFFSET
                seconds = int(ntp_sent_at)
                fraction = int((ntp_sent_at - seconds) * 2**32)
                transmit_timestamp = struct.pack("!II", seconds, fraction)
                packet[40:48] = transmit_timestamp

                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(1.5)
                    client.sendto(packet, address)
                    response, _ = client.recvfrom(512)
                    received_at = time.time()
                    received_monotonic = time.monotonic()

                if len(response) < 48 or response[24:32] != transmit_timestamp:
                    continue
                if response[1] == 0 or response[1] > 15 or response[0] >> 6 == 3:
                    continue
                if (response[0] & 0x07) != 4:
                    continue

                server_received_at = self._read_timestamp(response, 32)
                server_sent_at = self._read_timestamp(response, 40)
                offset = (
                    (server_received_at - sent_at)
                    + (server_sent_at - received_at)
                ) / 2
                self.sync_ready.emit(received_at + offset, received_monotonic)
                return
            except (OSError, IndexError, struct.error):
                continue

        if not self.isInterruptionRequested():
            self.sync_failed.emit()


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

    def _get_subprocess_kwargs(self):
        """Zwraca flagi ukrywające okno konsoli tylko na systemie Windows."""
        kwargs = {}
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs['startupinfo'] = startupinfo
        return kwargs

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
            partitions = psutil.disk_partitions(all=False)
            disk_texts = []
            for p in partitions:
                if os.name == 'nt':
                    if 'fixed' not in p.opts.lower():
                        continue
                    label = p.device
                else:
                    # Pomijamy wirtualne obrazy (np. pakiety snap) i tymczasowe systemy plików na Linuksie
                    if p.device.startswith('/dev/loop') or p.fstype in ('squashfs', 'tmpfs', 'devtmpfs'):
                        continue
                    label = p.mountpoint

                try:
                    u = psutil.disk_usage(p.mountpoint)
                    disk_texts.append(f"[{label}] {u.percent}%")
                except PermissionError:
                    continue

            self.disks_data_ready.emit(" | ".join(disk_texts[:3]) if disk_texts else "Brak danych")
        except Exception as e:
            print(f"Błąd odczytu dysków: {e}")

    def _scan_processes(self):
        try:
            procs_ram = []
            procs_cpu = []
            num_cpus = psutil.cpu_count() or 1
            for p in psutil.process_iter(['name', 'memory_info', 'cpu_percent']):
                try:
                    name = p.info.get('name', '')
                    if not name or 'idle' in name.lower() or name.lower() == 'system':
                        continue
                    
                    mem_rss = p.info.get('memory_info')
                    if mem_rss:
                        mem_mb = mem_rss.rss / (1024 * 1024)
                        procs_ram.append((name, mem_mb))
                        
                    raw_cpu = p.info.get('cpu_percent', 0.0)
                    cpu_usage = (raw_cpu / num_cpus) if raw_cpu is not None else 0.0
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
            nvsmi_path = shutil.which("nvidia-smi")
            
            if not nvsmi_path and os.name == 'nt':
                for fallback in [
                    r"C:\Windows\System32\nvidia-smi.exe",
                    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
                ]:
                    if os.path.exists(fallback):
                        nvsmi_path = fallback
                        break

            if not nvsmi_path:
                self.gpu_data_ready.emit([])
                return

            result = subprocess.run(
                [nvsmi_path, "pmon", "-c", "1"],
                capture_output=True,
                text=True,
                errors='ignore',
                **self._get_subprocess_kwargs()
            )
            
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
            devices = []
            if os.name == 'nt':
                cmd = (
                    'powershell "Get-PnpDevice -PresentOnly | '
                    'Where-Object {$_.InstanceId -match \'^USB\' -and $_.FriendlyName -notmatch \'Hub|Composite|Root|Kontroler\'} | '
                    'Select-Object -ExpandProperty FriendlyName -Unique"'
                )
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    shell=True,
                    encoding='cp850',
                    errors='ignore',
                    **self._get_subprocess_kwargs()
                )
                for line in result.stdout.split('\n'):
                    name = line.strip()
                    if name and name not in devices:
                        devices.append(name)
            else:
                # Skanowanie USB na systemie Linux (lsusb lub /sys/bus/usb/devices)
                if shutil.which("lsusb"):
                    result = subprocess.run(
                        ["lsusb"],
                        capture_output=True,
                        text=True,
                        errors='ignore'
                    )
                    for line in result.stdout.split('\n'):
                        # Przykładowy format: Bus 001 Device 002: ID 1234:5678 Nazwa Urządzenia
                        parts = line.split("ID ")
                        if len(parts) > 1:
                            id_and_name = parts[1].strip().split(" ", 1)
                            if len(id_and_name) > 1:
                                name = id_and_name[1].strip()
                                if not any(ignore in name.lower() for ignore in ("root hub", "linux foundation", "hub")):
                                    if name and name not in devices:
                                        devices.append(name)
                else:
                    for prod_file in glob.glob("/sys/bus/usb/devices/*/product"):
                        try:
                            with open(prod_file, "r", encoding="utf-8", errors="ignore") as f:
                                name = f.read().strip()
                                if name and not any(ignore in name.lower() for ignore in ("host controller", "root hub", "hub")):
                                    if name not in devices:
                                        devices.append(name)
                        except OSError:
                            continue

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