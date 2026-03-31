#!/usr/bin/env python3
"""
Ubuntu Monitor - OPTIMIZED & OOP (CPU, GPU, RAM, Disk I/O, Battery)
A lightweight system monitor designed for hybrid hardware configurations.
Avoids heavy subprocesses by reading directly from /proc and /sys.
"""
import sys
import time
import shutil
import subprocess
from pathlib import Path

# --- Fallback GPU Nvidia ---
# Attempt to load NVML (Nvidia Management Library) to read Nvidia sensors natively.
# If the library is not installed, fallback to the nvidia-smi CLI command.
try:
    import pynvml
    pynvml.nvmlInit()
    HAS_NVML = True
except (ImportError, Exception):
    HAS_NVML = False

class Terminal:
    """ANSI display management to prevent screen flickering"""
    # Standard ANSI color codes
    R = "\033[91m" ; G = "\033[92m" ; Y = "\033[93m" ; B = "\033[94m" ; C_ = "\033[96m" ; W = "\033[97m"
    END = "\033[0m" ; BOLD = "\033[1m"
    
    # Cursor control sequences
    HOME = "\033[H"       # Moves the cursor to the top left (0,0) without clearing the screen
    CLR_LINE = "\033[K"   # Clears the rest of the current line
    CLR_SCR = "\033[2J\033[H" # Clears the entire screen (used only at startup)

    @staticmethod
    def color_val(val, low=50, high=80, inverse=False, unit="%"):
        """Returns a formatted string with conditional coloring (Green, Yellow, Red)."""
        if val is None: return f"{Terminal.W}--{unit}{Terminal.END}"
        col = Terminal.G
        # inverse=True for battery percentage (low = red)
        if inverse: 
            col = Terminal.R if val <= low else (Terminal.Y if val <= high else Terminal.G)
        else: 
            col = Terminal.R if val >= high else (Terminal.Y if val >= low else Terminal.G)
        v_str = f"{val}" if isinstance(val, int) else f"{val:.1f}"
        return f"{col}{v_str}{unit}{Terminal.END}"

    @staticmethod
    def fmt_bytes(n):
        """Converts byte count to human-readable format (K, M, G, T)."""
        for u in ["B","K","M","G","T"]:
            if n < 1024: return f"{n:.1f}{u}"
            n /= 1024
        return f"{n:.1f}P"


class SystemMonitor:
    def __init__(self):
        # Internal state to compute deltas between T and T-1
        self.sysfs_cache = {"hwmon_nvme": None, "hwmon_cpu": {}, "drm_cards": []}
        self.prev_cores = {}
        self.prev_disks = {}
        self.prev_gpu_state = {}
        
        self.prev_time = time.time()
        self.tick_counter = 0
        self.cached_parts = []

        # Hardware discovery and baseline values initialization (T-1)
        self._init_sysfs_cache()
        self._prime_sensors()

    def _read_text(self, path):
        """Optimized reading of a sysfs pseudo-file as raw text."""
        try:
            with open(path, "r") as f: return f.read().strip()
        except (FileNotFoundError, PermissionError): return ""

    def _read_int(self, path):
        """Reads a pseudo-file containing an integer value."""
        try: return int(self._read_text(path))
        except (ValueError, TypeError): return None

    def _init_sysfs_cache(self):
        """
        Discovers hardware at startup (I/O Optimization).
        Scanning /sys on every tick is expensive. We cache the paths for 
        thermal sensors and GPUs once.
        """
        hw = Path("/sys/class/hwmon")
        if hw.exists():
            for h in hw.iterdir():
                name = self._read_text(h/"name")
                # Detect NVMe thermal sensor
                if name == "nvme":
                    self.sysfs_cache["hwmon_nvme"] = h/"temp1_input"
                # Detect CPU core thermal sensors (Intel/AMD)
                elif name == "coretemp":
                    for lbl in h.glob("temp*_label"):
                        try:
                            idx = int(self._read_text(lbl).split()[-1])
                            self.sysfs_cache["hwmon_cpu"][idx] = lbl.with_name(lbl.name.replace("label","input"))
                        except (ValueError, IndexError): pass
        
        # Detect integrated GPUs via Direct Rendering Manager (DRM) API
        drm = Path("/sys/class/drm")
        if drm.exists():
            for c in drm.glob("card[0-9]*"):
                vid = self._read_text(c/"device/vendor")
                # 0x8086 = Intel, 0x1002 = AMD
                if vid in ["0x8086", "0x1002"]:
                    self.sysfs_cache["drm_cards"].append({"path": c, "vid": vid})

    def _prime_sensors(self):
        """
        Populates initial states (T-1).
        Required because Linux only exposes cumulative counters (ticks/sectors).
        Actual usage is the delta between two reads.
        """
        for k, v in self.get_cpu_cores(dt=1.0).items():
            self.prev_cores[k] = {"raw": v["raw"]}
        for k, v in self.get_disk_stats(dt=1.0).items():
            self.prev_disks[k] = {"r_sect": v["r_sect"], "w_sect": v["w_sect"]}
        for g in self.get_gpu(dt=1.0):
            if "raw_rc6" in g:
                self.prev_gpu_state[g["id"]] = {"rc6": g["raw_rc6"]}
        
        self.cached_parts = self.get_partitions()
        time.sleep(0.5) # Allow system time to increment counters
        self.prev_time = time.time()

    def get_mem(self):
        """Reads available RAM from /proc/meminfo."""
        mem = {}
        try:
            for l in self._read_text("/proc/meminfo").splitlines():
                if ":" in l:
                    k, v = l.split(":", 1)
                    # The value is in kB, convert it to bytes
                    mem[k] = int(v.split()[0]) * 1024
        except Exception: pass
        return mem

    def get_partitions(self):
        """Uses shutil to get disk space for main partitions."""
        parts = []
        try:
            root = shutil.disk_usage("/")
            parts.append({"m": "/", "u": root.used, "t": root.total})
            home = shutil.disk_usage("/home")
            # If /home is on a separate partition from root
            if home.total != root.total:
                parts.append({"m": "/home", "u": home.used, "t": home.total})
        except Exception: pass
        return parts

    def get_battery(self):
        """Reads battery state from the power_supply subsystem."""
        bats = []
        ps = Path("/sys/class/power_supply")
        if ps.exists():
            for b in ps.iterdir():
                if b.name.startswith("BAT"):
                    bats.append({
                        "pct": self._read_int(b/"capacity"),
                        "status": self._read_text(b/"status"),
                        "watts": (self._read_int(b/"power_now") or 0) / 1e6 # power_now is in microwatts
                    })
        return bats

    def get_cpu_cores(self, dt):
        """
        Calculates per-core CPU load by reading /proc/stat.
        Logic: (Delta Total Time - Delta Idle Time) / Delta Total Time
        """
        cores = {}
        try:
            for l in self._read_text("/proc/stat").splitlines():
                p = l.split()
                if p and p[0].startswith("cpu") and p[0] != "cpu":
                    cid = int(p[0][3:])
                    v = list(map(int, p[1:]))
                    usage = 0.0

                    if cid in self.prev_cores:
                        # sum(v[:8]) = sum of all time modes (user, nice, system, idle, iowait, irq, softirq, steal)
                        d_total = sum(v[:8]) - self.prev_cores[cid]["raw"][0]
                        # v[3] = idle, v[4] = iowait
                        d_idle = (v[3]+v[4]) - self.prev_cores[cid]["raw"][1]
                        if d_total > 0: usage = 100.0 * (d_total - d_idle) / d_total

                    # Read current frequency
                    f = self._read_int(f"/sys/devices/system/cpu/cpu{cid}/cpufreq/scaling_cur_freq")
                    
                    # Read temperature from sysfs cache (in millidegrees Celsius)
                    t = None
                    if cid in self.sysfs_cache["hwmon_cpu"]:
                        raw_t = self._read_int(self.sysfs_cache["hwmon_cpu"][cid])
                        if raw_t: t = raw_t / 1000.0

                    cores[cid] = {"usage": usage, "freq": (f/1e6 if f else 0), "raw": (sum(v[:8]), v[3]+v[4]), "temp": t}
        except Exception: pass
        return cores

    def get_disk_stats(self, dt):
        """
        Calculates disk I/O speed by reading /proc/diskstats.
        Converts read/written sectors (1 sector = 512 bytes on Linux) to bytes/sec.
        """
        disks = {}
        try:
            for l in self._read_text("/proc/diskstats").splitlines():
                p = l.split()
                if len(p) < 14: continue
                name = p[2]
                
                # Ignore partitions (e.g., sda1) to keep only the physical disk (sda, nvme0n1)
                if name.startswith("sd") and name[-1].isdigit(): continue
                if name.startswith("nvme") and "p" in name: continue
                if not (name.startswith("sd") or name.startswith("nvme")): continue

                # Index 5: read sectors, Index 9: written sectors
                sec_r, sec_w = int(p[5]), int(p[9])
                rs, ws, temp = 0.0, 0.0, None

                # Calculate speeds relative to T-1 (dt = time delta)
                if name in self.prev_disks and dt > 0:
                    rs = ((sec_r - self.prev_disks[name]["r_sect"]) * 512) / dt
                    ws = ((sec_w - self.prev_disks[name]["w_sect"]) * 512) / dt

                # Get temperature if it's an NVMe drive
                if name.startswith("nvme") and self.sysfs_cache["hwmon_nvme"]:
                    t = self._read_int(self.sysfs_cache["hwmon_nvme"])
                    if t: temp = t / 1000.0

                disks[name] = {"r_sect": sec_r, "w_sect": sec_w, "rs": rs, "ws": ws, "temp": temp}
        except Exception: pass
        return disks

    def get_gpu(self, dt):
        """Retrieves GPU metrics (Dedicated Nvidia and Intel/AMD iGPUs)."""
        gpus = []
        
        # --- NVIDIA Management ---
        if HAS_NVML:
            try:
                # Native C API usage for near-zero CPU cost
                for i in range(pynvml.nvmlDeviceGetCount()):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    gpus.append({
                        "name": name, "temp": float(temp), "load": float(util.gpu),
                        "mem": f"{mem.used//1024**2}/{mem.total//1024**2}M", "id": f"nvidia_{i}"
                    })
            except Exception: pass
        else:
            try:
                # CLI fallback if pynvml library is not installed
                o = subprocess.run("nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits", shell=True, capture_output=True, text=True, timeout=0.2).stdout
                for l in o.splitlines():
                    p = l.split(",")
                    gpus.append({"name": p[0], "temp": float(p[1]), "load": float(p[2]), "mem": f"{float(p[3]):.0f}/{float(p[4]):.0f}M", "id":"nvidia"})
            except Exception: pass

        # --- INTEL / AMD (iGPU) Management ---
        for card in self.sysfs_cache["drm_cards"]:
            try:
                c = card["path"]
                name = "Intel (iGPU)" if card["vid"]=="0x8086" else "AMD GPU"
                card_id = c.name

                # DRM chip specific thermal sensors
                t = None
                if (c/"gt/gt0/temp_act").exists(): t = self._read_int(c/"gt/gt0/temp_act")
                elif (c/"device/hwmon").exists():
                    for h in (c/"device/hwmon").iterdir():
                        if (h/"temp1_input").exists(): t = self._read_int(h/"temp1_input"); break

                freq = self._read_int(c/"gt_act_freq_mhz")
                load = None

                # rc6 is the Intel GPU "deep sleep" state. The inverse of deep sleep gives us the load (busy).
                rc6_path = c/"gt/gt0/rc6_residency_ms" if (c/"gt/gt0/rc6_residency_ms").exists() else c/"power/rc6_residency_ms"
                raw_rc6 = self._read_int(rc6_path) if rc6_path.exists() else None

                if card_id in self.prev_gpu_state and raw_rc6 is not None and dt > 0:
                    delta_rc6 = raw_rc6 - self.prev_gpu_state[card_id]["rc6"]
                    pct_idle = (delta_rc6 / (dt*1000.0)) * 100.0
                    load = max(0.0, min(100.0, 100.0 - pct_idle))

                # More modern alternative method for % busy
                if load is None and (c/"device/gpu_busy_percent").exists():
                    load = self._read_int(c/"device/gpu_busy_percent")

                gpus.append({"name": name, "temp": t/1000.0 if t else None, "load": load, "freq": freq, "id": card_id, "raw_rc6": raw_rc6})
            except Exception: pass
        return gpus

    def render(self):
        """Gathers metrics and generates the full flicker-free display"""
        cur_time = time.time()
        dt = cur_time - self.prev_time
        self.prev_time = cur_time

        # Update states (save for T+1)
        cores = self.get_cpu_cores(dt)
        for k, v in cores.items(): self.prev_cores[k] = {"raw": v["raw"]}

        disks = self.get_disk_stats(dt)
        for k, v in disks.items(): self.prev_disks[k] = {"r_sect": v["r_sect"], "w_sect": v["w_sect"]}

        gpus = self.get_gpu(dt)
        for g in gpus:
            if "raw_rc6" in g: self.prev_gpu_state[g["id"]] = {"rc6": g["raw_rc6"]}

        # Optimization: Only read partitions every 30 seconds as I/O is heavy and space varies slowly
        if self.tick_counter % 30 == 0:
            self.cached_parts = self.get_partitions()

        mem = self.get_mem()
        bats = self.get_battery()

        # UI rendering construction in an array to print only once. 
        # Terminal.HOME resets cursor to (0,0). Terminal.CLR_LINE overwrites ghost characters.
        out = [Terminal.HOME]
        out.append(f"{Terminal.B}╔{'═'*60}╗{Terminal.END}{Terminal.CLR_LINE}")
        out.append(f"{Terminal.B}║{Terminal.END} {Terminal.BOLD}SYSTEM MONITOR OOP{Terminal.END} {Terminal.W}{time.strftime('%H:%M:%S')}{Terminal.END}{Terminal.CLR_LINE}")

        # --- RAM ---
        m_tot = mem.get("MemTotal", 1)
        m_used = m_tot - mem.get("MemAvailable", 0)
        m_pct = (m_used / m_tot * 100) if m_tot else 0
        bar = "█"*int(m_pct/5) + "░"*(20-int(m_pct/5))
        out.append(f"{Terminal.B}╠{'─'*60}╣{Terminal.END}{Terminal.CLR_LINE}")
        out.append(f" {Terminal.BOLD}RAM{Terminal.END} {Terminal.color_val(m_pct,70,90)} {Terminal.B}[{bar}]{Terminal.END} {Terminal.fmt_bytes(m_used)}/{Terminal.fmt_bytes(m_tot)}{Terminal.CLR_LINE}")

        # --- DISK I/O ---
        out.append(f"{Terminal.B}╠{'─'*60}╣{Terminal.END}{Terminal.CLR_LINE}")
        out.append(f" {Terminal.BOLD}DISK I/O{Terminal.END}{Terminal.CLR_LINE}")
        for name, d in disks.items():
            t_str = f"{d['temp']:.0f}°C" if d['temp'] else "--°C"
            rc = Terminal.W if d['rs'] < 1024 else (Terminal.Y if d['rs'] < 100e6 else Terminal.R)
            wc = Terminal.W if d['ws'] < 1024 else (Terminal.Y if d['ws'] < 100e6 else Terminal.R)
            out.append(f" {name:<7} {t_str} R: {rc}{Terminal.fmt_bytes(d['rs'])}/s{Terminal.END} W: {wc}{Terminal.fmt_bytes(d['ws'])}/s{Terminal.END}{Terminal.CLR_LINE}")

        for p in self.cached_parts:
            pct = (p['u']/p['t']*100) if p['t'] else 0
            bar = "█"*int(pct/5) + "░"*(20-int(pct/5))
            out.append(f" {p['m']:<7} {Terminal.color_val(pct,60,85)} {Terminal.B}[{bar}]{Terminal.END} {Terminal.fmt_bytes(p['u'])}/{Terminal.fmt_bytes(p['t'])}{Terminal.CLR_LINE}")

        # --- BATTERY ---
        if bats:
            out.append(f"{Terminal.B}╠{'─'*60}╣{Terminal.END}{Terminal.CLR_LINE}")
            for b in bats:
                ic = "⚡" if b['status']=="Charging" else "🔋"
                out.append(f" {ic} {Terminal.color_val(b['pct'],20,50,True)} [{b['status']}] {b['watts']:.1f}W{Terminal.CLR_LINE}")

        # --- GPU ---
        out.append(f"{Terminal.B}╠{'─'*60}╣{Terminal.END}{Terminal.CLR_LINE}")
        for g in gpus:
            ld = Terminal.color_val(g['load'],50,80) if g['load'] is not None else f"{Terminal.W}--%{Terminal.END}"
            tp = Terminal.color_val(g['temp'],60,80,unit="°C")
            xtra = f"Mem:{g['mem']}" if 'mem' in g else f"{g.get('freq')}MHz"
            out.append(f" {Terminal.C_}{g['name']:<15}{Terminal.END} {tp} Load: {ld} {xtra}{Terminal.CLR_LINE}")

        # --- CPU ---
        out.append(f"{Terminal.B}╠{'─'*60}╣{Terminal.END}{Terminal.CLR_LINE}")
        c_ids = sorted(cores.keys())
        # Display in 2 columns to save vertical space
        for i in range(0, len(c_ids), 2):
            c1 = cores[c_ids[i]]
            s1 = f"#{c_ids[i]:<2} {Terminal.color_val(c1['usage'],50,85)} {c1['freq']:.1f}G {Terminal.color_val(c1['temp'],60,85,unit='°C')}"
            s2 = ""
            if i+1 < len(c_ids):
                c2 = cores[c_ids[i+1]]
                s2 = f"│ #{c_ids[i+1]:<2} {Terminal.color_val(c2['usage'],50,85)} {c2['freq']:.1f}G {Terminal.color_val(c2['temp'],60,85,unit='°C')}"
            out.append(f" {s1:<35} {s2}{Terminal.CLR_LINE}")

        out.append(f"{Terminal.B}╚{'═'*60}╝{Terminal.END}{Terminal.CLR_LINE}")

        # Write the entire block at once and flush the buffer
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()

    def run(self):
        """Main execution loop"""
        sys.stdout.write(Terminal.CLR_SCR)
        try:
            while True:
                self.render()
                self.tick_counter += 1
                time.sleep(1)
        except KeyboardInterrupt:
            # Clean exit on Ctrl+C
            sys.stdout.write(f"\n{Terminal.W}Stopping monitor.{Terminal.END}\n")
            if HAS_NVML: pynvml.nvmlShutdown()

if __name__ == "__main__":
    monitor = SystemMonitor()
    monitor.run()
