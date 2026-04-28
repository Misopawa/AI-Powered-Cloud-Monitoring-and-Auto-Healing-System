import os
import time
import pandas as pd
from datetime import datetime
from collections import deque
import sys
import select
import termios
import tty
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.text import Text
from rich.align import Align
from rich.live import Live

class HealingDashboard:
    def __init__(self, config):
        self.config = config
        self.console = Console()
        self.layout = Layout(name="root")
        self.forensics_file = "anomalies_forensics.csv"
        self.is_connected = True
        self.waiting_for_data = False
        self.ui_messages = deque(maxlen=50)
        self.resume_requested = False
        self.telegram_active = False
        self.source_label = "UNKNOWN"
        self.net_label = None
        self.stg_label = None
        self._stdin_fd = None
        self._stdin_old_settings = None
        self._setup_layout()

    def set_telegram_active(self, active: bool):
        self.telegram_active = bool(active)

    def set_source_label(self, label: str):
        self.source_label = str(label or "UNKNOWN")

    def set_prometheus_labels(self, network_device: str = None, storage_label: str = None):
        self.net_label = str(network_device) if network_device else None
        self.stg_label = str(storage_label) if storage_label else None

    def enable_key_listener(self):
        try:
            if not sys.stdin.isatty():
                return
            self._stdin_fd = sys.stdin.fileno()
            self._stdin_old_settings = termios.tcgetattr(self._stdin_fd)
            tty.setcbreak(self._stdin_fd)
        except Exception:
            self._stdin_fd = None
            self._stdin_old_settings = None

    def disable_key_listener(self):
        try:
            if self._stdin_fd is None or self._stdin_old_settings is None:
                return
            termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._stdin_old_settings)
        except Exception:
            pass
        finally:
            self._stdin_fd = None
            self._stdin_old_settings = None

    def poll_keys(self):
        try:
            if self._stdin_fd is None:
                return
            ready, _, _ = select.select([self._stdin_fd], [], [], 0)
            if not ready:
                return
            ch = os.read(self._stdin_fd, 1).decode(errors="ignore")
            if ch in ("r", "R"):
                self.resume_requested = True
        except Exception:
            return

    def _setup_layout(self):
        self.layout.split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=2),
        )

        self.layout["left"].split(
            Layout(name="header", size=3),
            Layout(name="ai_brain", ratio=6),
            Layout(name="forensics", ratio=2),
            Layout(name="footer", size=3),
        )

        self.layout["header"].update(self._make_header(True))
        self.layout["ai_brain"].update(Panel(Align.center(Text("Analyzing...", style="dim")), title="AI Decision Logic", border_style="dim"))
        self.layout["forensics"].update(Panel(Text("System boot sequence initiated...", style="dim"), title="Anomaly Forensics (Last 10)", border_style="dim"))
        self.layout["right"].update(self._make_background_panel())
        self.layout["footer"].update(self._make_footer())

    def generate_layout(self):
        return self.layout

    def update_view(self, metrics, anomaly_score, threshold, escalation_level, action_name, stabilization_window, last_action_timestamp, is_connected=False, ui_messages=None, raw_score=None, decision_heads=None):
        if ui_messages:
            self.ui_messages.extend(list(ui_messages))
        self.layout["header"].update(self._make_header(True))
        self.layout["ai_brain"].update(self._make_ai_brain_panel(decision_heads, escalation_level, action_name, stabilization_window, last_action_timestamp))
        self.layout["forensics"].update(self._make_logs_panel())
        self.layout["right"].update(self._make_background_panel())
        self.layout["footer"].update(self._make_footer())
        return self.layout

    def _make_header(self, is_connected=False):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        node = self.config.get('proxmox', {}).get('node', 'pve')
        vmid = self.config.get('proxmox', {}).get('vmid', '101')
        
        if is_connected:
            status_text = Text(" [CONNECTED] ✔", style="bold green")
            title_style = "bold cyan"
        else:
            status_text = Text(" Initializing Connection...", style="bold cyan")
            title_style = "bold cyan"
            
        title = Text("AI-Powered Cloud Monitoring & Auto-Healing System", style=title_style)
        info = Text(f" [Time: {current_time}] [Node: {node}] [VMID: {vmid}]", style="white")
        
        header_content = title + status_text + info
        return Panel(Align.center(header_content), style="blue")

    def _make_ai_brain_panel(self, decision_heads, level, action, window, last_action):
        current_time = time.time()
        time_diff = current_time - last_action
        remaining = max(0, int(window - time_diff)) if last_action > 0 else 0

        if level >= 5:
            content = Text("!!! MANUAL INTERVENTION REQUIRED: PRESS 'R' TO RESUME !!!", style="bold white on bright_red blink")
            return Panel(Align.center(content, vertical="middle"), title="System Status", border_style="bright_red")

        heads = decision_heads or {}
        table = Table(title="Health Grid", expand=True, title_style="bold blue")
        table.add_column("Component", style="cyan")
        table.add_column("Status")
        table.add_column("Current", justify="right")
        table.add_column("Baseline", justify="right")
        table.add_column("Deviation", justify="right")

        def row_for(name, label, formatter):
            info = heads.get(name) or {}
            is_anomaly = bool(info.get("anomaly", False))
            value = info.get("value", 0.0)
            baseline = info.get("baseline", 0.0)
            deviation = info.get("deviation", 0.0)
            site_down = bool(info.get("site_down", False)) if name == "NETWORK" else False
            try:
                value = float(value)
            except Exception:
                value = 0.0
            try:
                baseline = float(baseline)
            except Exception:
                baseline = 0.0
            try:
                deviation = float(deviation)
            except Exception:
                deviation = abs(value - baseline)
            if name == "NETWORK":
                latency_ms = 0.0
                retrans = 0.0
                try:
                    latency_ms = float(info.get("latency_ms", 0.0) or 0.0)
                except Exception:
                    latency_ms = 0.0
                try:
                    retrans = float(info.get("retrans_per_sec", 0.0) or 0.0)
                except Exception:
                    retrans = 0.0
                if site_down:
                    row_style = "bold white on bright_red blink"
                    status = Text("[ SITE DOWN ]", style=row_style)
                    current_text = Text("Unreachable", style=row_style)
                    baseline_text = Text("-", style=row_style)
                    deviation_text = Text("-", style=row_style)
                    comp = Text(f"[{label}]", style=row_style)
                else:
                    status = Text("[ ANOMALY ]" if is_anomaly else "[ NORMAL ]", style="bold red" if is_anomaly else "bold green")
                    current_text = Text(f"Lat: {latency_ms:.0f}ms | Ret: {retrans:.2f}/s", style="bold red" if is_anomaly else "green")
                    baseline_text = Text(f"{baseline:.0f}ms", style="bold red" if is_anomaly else "dim")
                    deviation_text = Text(f"{deviation:.0f}ms", style="bold red" if is_anomaly else "yellow")
                    comp = Text(f"[{label}]", style="bold red" if is_anomaly else "cyan")
            else:
                status = Text("[ ANOMALY ]" if is_anomaly else "[ NORMAL ]", style="bold red" if is_anomaly else "bold green")
                current_text = Text(formatter(value), style="bold red" if is_anomaly else "green")
                baseline_text = Text(formatter(baseline), style="bold red" if is_anomaly else "dim")
                deviation_text = Text(formatter(deviation), style="bold red" if is_anomaly else "yellow")
                comp = Text(f"[{label}]", style="bold red" if is_anomaly else "cyan")
            table.add_row(comp, status, current_text, baseline_text, deviation_text)

        row_for("CPU", "CPU", lambda v: f"{v * 100:.1f}%")
        row_for("MEMORY", "MEM", lambda v: f"{v * 100:.1f}%")
        row_for("STORAGE", "STG", lambda v: f"{v * 100:.1f}%")
        row_for("NETWORK", "NET", lambda v: f"{v * 100:.1f}%")

        state_style = "bold white"
        if "VERIFYING" in str(action):
            state_style = "bold yellow"
        if "WARMING UP" in str(action):
            state_style = "bold cyan"
        state_text = Text(f"\nEscalation State: Level {level}\nAction: {action}", style=state_style)

        stab_style = "bold yellow" if remaining > 0 else "dim green"
        stab_text = Text(f"\nStabilization Window: {remaining}s remaining", style=stab_style)

        panel_content = Table.grid(expand=True)
        panel_content.add_row(table)
        panel_content.add_row(Align.center(state_text))
        panel_content.add_row(Align.center(stab_text))

        return Panel(panel_content, title="Decision Heads", border_style="white")

    def _make_logs_panel(self):
        logs_text = Text()
        if self.ui_messages:
            for msg in list(self.ui_messages)[-10:]:
                logs_text.append(str(msg) + "\n", style="dim white")
            logs_text.append("\n")
        if os.path.exists(self.forensics_file):
            try:
                df = pd.read_csv(self.forensics_file).tail(10)
                for _, row in df.iterrows():
                    ts = row['timestamp']
                    score = row['anomaly_score']
                    level = int(row['executed_level'])
                    line = f"[{ts}] Score: {score:.4f} | Executed Level {level}\n"
                    logs_text.append(line, style="dim white")
            except Exception:
                logs_text = Text("Waiting for forensic data...", style="dim")
        else:
            logs_text = Text("No anomalies recorded yet.", style="dim")
            
        return Panel(logs_text, title="Anomaly Forensics (Last 10)", border_style="white")

    def _make_background_panel(self):
        logs = "\n".join(list(self.ui_messages))
        logs_text = Text(logs if logs else "No background operations yet.", style="dim green")
        return Panel(logs_text, title="Background Operations", border_style="green")

    def _make_footer(self):
        content = Text()
        content.append(f"[ SOURCE: {self.source_label} ]", style="bold cyan")
        if self.net_label:
            content.append("  ")
            content.append(f"[ NET: {self.net_label} ]", style="cyan")
        if self.stg_label:
            content.append("  ")
            content.append(f"[ STG: {self.stg_label} ]", style="cyan")
        content.append("  ")
        if self.telegram_active:
            content.append("[ TELEGRAM: ACTIVE ]", style="bold green")
        else:
            content.append("[ TELEGRAM: INACTIVE ]", style="dim")
        return Panel(Align.center(content), border_style="dim")
