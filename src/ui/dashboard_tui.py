import os
import time
import pandas as pd
from datetime import datetime
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
        self.layout = Layout()
        self.forensics_file = "anomalies_forensics.csv"
        self._setup_layout()

    def _setup_layout(self):
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=10)
        )
        self.layout["body"].split_row(
            Layout(name="telemetry", ratio=1),
            Layout(name="ai_brain", ratio=1)
        )
        
        # Initialize with placeholder panels for a cleaner "Loading" sequence
        self.layout["header"].update(Panel(Align.center(Text("Initializing Connection...", style="bold cyan")), style="blue"))
        self.layout["telemetry"].update(Panel(Align.center(Text("Waiting for first telemetry scrape...", style="dim")), title="Telemetry", border_style="dim"))
        self.layout["ai_brain"].update(Panel(Align.center(Text("Analyzing...", style="dim")), title="AI Decision Logic", border_style="dim"))
        self.layout["footer"].update(Panel(Text("System boot sequence initiated...", style="dim"), title="Anomaly Forensics", border_style="dim"))

    def update_view(self, metrics, anomaly_score, threshold, escalation_level, action_name, stabilization_window, last_action_timestamp, is_connected=False):
        self.layout["header"].update(self._make_header(is_connected))
        self.layout["telemetry"].update(self._make_telemetry_table(metrics))
        self.layout["ai_brain"].update(self._make_ai_brain_panel(anomaly_score, threshold, escalation_level, action_name, stabilization_window, last_action_timestamp))
        self.layout["footer"].update(self._make_logs_panel())
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

    def _make_telemetry_table(self, metrics):
        table = Table(title="Live Telemetry (Normalized [0,1])", expand=True, title_style="bold blue")
        table.add_column("Feature", style="cyan")
        table.add_column("Value", justify="right")

        features = [
            ('load-1m', 'load1_norm'), ('load-5m', 'load5_norm'), ('load-15m', 'load15_norm'),
            ('mem-free', 'mem_free_ratio'), ('mem-avail', 'mem_available_ratio'), ('mem-total', 'mem_total_ratio'),
            ('mem-cache', 'mem_cache_ratio'), ('mem-buffer', 'mem_buffered_ratio'),
            ('swap-total', 'swap_total_ratio'), ('swap-free', 'swap_free_ratio'),
            ('fork-rate', 'fork_rate'), ('intr-rate', 'intr_rate')
        ]

        for label, key in features:
            val = metrics.get(key, 0.0)
            color = "green"
            if val > 0.9: color = "red"
            elif val > 0.7: color = "yellow"
            table.add_row(label, Text(f"{val:.4f}", style=color))
        
        return Panel(table, border_style="white")

    def _make_ai_brain_panel(self, score, threshold, level, action, window, last_action):
        current_time = time.time()
        time_diff = current_time - last_action
        remaining = max(0, int(window - time_diff)) if last_action > 0 else 0
        
        score_color = "red" if score < threshold else "green"
        score_text = Text(f"Anomaly Score S(x): {score:.4f}", style=f"bold {score_color}")
        
        state_text = Text(f"\nEscalation State: Level {level}\nAction: {action}", style="bold white")
        
        stab_style = "bold yellow" if remaining > 0 else "dim green"
        stab_text = Text(f"\n\nStabilization Window: {remaining}s remaining", style=stab_style)
        
        if remaining > 0:
            status_note = Text("\n[Waiting for Prometheus Sync...]", style="italic yellow")
        else:
            status_note = Text("\n[System Ready/Monitoring]", style="italic green")

        content = score_text + state_text + stab_text + status_note
        return Panel(Align.center(content, vertical="middle"), title="AI Brain Decision Matrix", border_style="white")

    def _make_logs_panel(self):
        logs_text = Text()
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
