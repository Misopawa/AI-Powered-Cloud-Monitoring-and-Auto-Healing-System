import time
import argparse
import subprocess
import os
import gc
import sys
import logging
from rich.console import Console
from utils.config_loader import load_config
from utils.logger import get_logger
from monitoring.metrics_collector import collect_metrics
from ai.anomaly_detector import AnomalyDetector
from healing.auto_healer import PolicyEngine
from utils.data_handler import save_metrics_to_csv
from ui.dashboard_tui import HealingDashboard
from rich.live import Live

logger = get_logger("AutoHealingEngine")

class DashboardLogHandler(logging.Handler):
    def __init__(self, ui_messages, level=logging.INFO):
        super().__init__(level=level)
        self.ui_messages = ui_messages
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record):
        try:
            self.ui_messages.append(self.format(record))
        except Exception:
            pass

def _configure_tui_logging():
    os.makedirs("logs", exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(logging.FileHandler("logs/system.log"))
    for logger_name in list(logging.root.manager.loggerDict.keys()):
        candidate = logging.getLogger(logger_name)
        candidate.propagate = False
        for handler in list(candidate.handlers):
            if isinstance(handler, logging.StreamHandler):
                candidate.removeHandler(handler)

def cleanup(config):
    """
    Shutdown Protection: Ensures all monitored services are in a Running state before exiting.
    """
    logger.info("[SHUTDOWN] Initiating Cleanup Routine...")
    policies = config.get('policies', {})
    docker_containers = policies.get('docker_containers', [])
    
    for container in docker_containers:
        try:
            # Check if running
            check = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True, text=True
            )
            if check.returncode == 0 and check.stdout.strip().lower() != "true":
                logger.warning(f"[SHUTDOWN] Service {container} is NOT running. Attempting emergency start...")
                subprocess.run(["docker", "start", container], check=True)
                logger.info(f"[SHUTDOWN] Service {container} started successfully.")
            elif check.returncode == 0:
                logger.info(f"[SHUTDOWN] Service {container} is already healthy.")
        except Exception as e:
            logger.error(f"[SHUTDOWN] Failed to verify/start {container}: {e}")

def main():
    parser = argparse.ArgumentParser(description="AI-Powered Auto-Healing Engine")
    parser.add_argument("--tui", action="store_true", help="Enable the live TUI dashboard")
    args = parser.parse_args()

    logger.info("Starting Plug & Play Auto-Healing Engine...")

    # Load configuration
    config = load_config("config/config.yaml")
    monitoring_cfg = config.get('monitoring', {})

    try:
        for file_path in ("anomalies_forensics.csv", os.path.join("data", "metrics.csv")):
            if os.path.exists(file_path):
                os.remove(file_path)
    except Exception as e:
        logger.error(f"Cold boot cleanup failed: {e}")
    
    # Demo Mode Override
    demo_mode = monitoring_cfg.get('demo_mode', False)
    if demo_mode:
        interval = monitoring_cfg.get("demo_interval", 2)
        if not args.tui:
            logger.info("[ACTION] Demo Mode active. Polling interval reduced to %ds", interval)
    else:
        interval = monitoring_cfg.get("interval", 60)
    
    # Initialize Layers
    detector = AnomalyDetector(config)
    policy_engine = PolicyEngine(config)
    policy_engine.current_level_idx = 0
    policy_engine.is_halted = False
    
    # TUI Initialization
    dashboard = None
    if args.tui:
        os.makedirs("logs", exist_ok=True)
        _configure_tui_logging()
        dashboard = HealingDashboard(config)
        dashboard_log_handler = DashboardLogHandler(dashboard.ui_messages)
        logging.getLogger().addHandler(dashboard_log_handler)
        for logger_name in list(logging.root.manager.loggerDict.keys()):
            candidate = logging.getLogger(logger_name)
            candidate.addHandler(dashboard_log_handler)
            candidate.propagate = False

    if not args.tui:
        logger.info(f"System initialized. Monitoring LXC {config['proxmox']['vmid']} at {config['proxmox']['host']}")

    cycle_count = 0
    last_gc_time = time.time()
    calibration_cycles = 15

    try:
        tui_console = None
        if args.tui:
            tui_console = Console(file=sys.stdout)
            sys.stdout = open("logs/stdout.log", "a", encoding="utf-8")
            sys.stderr = open("logs/stderr.log", "a", encoding="utf-8")
            tui_console.clear()
        with Live(dashboard.generate_layout(), refresh_per_second=4, auto_refresh=True, screen=True, console=tui_console) if args.tui else open(os.devnull, 'w') as live:
            while True:
                try:
                    cycle_count += 1
                    if time.time() - last_gc_time >= 3600:
                        gc.collect()
                        last_gc_time = time.time()

                    if not args.tui:
                        logger.info("--------------------------- NEW CYCLE ---------------------------")

                    metrics = collect_metrics(config)
                    connected = metrics is not None

                    if not connected:
                        if args.tui:
                            dashboard.update_view(
                                metrics={},
                                anomaly_score=0.0,
                                threshold=config.get('ai', {}).get('anomaly_threshold', -0.5),
                                escalation_level=policy_engine.current_level_idx + 1,
                                action_name="API Gap/Reboot",
                                stabilization_window=policy_engine.STABILIZATION_WINDOW,
                                last_action_timestamp=policy_engine.last_action_timestamp,
                                is_connected=False
                            )
                        time.sleep(interval)
                        continue

                    if monitoring_cfg.get('save_to_csv'):
                        save_metrics_to_csv(metrics)

                    if metrics.get('critical_data_loss', False):
                        anomaly = {"anomaly": False, "critical_data_loss": True, "features": metrics, "score": 0.0}
                    else:
                        anomaly = detector.detect_anomaly(metrics)

                    if calibration_cycles > 0:
                        calibration_cycles -= 1
                        policy_engine.current_level_idx = 0
                        policy_engine.is_halted = False
                        action = f"[ CALIBRATING ] {calibration_cycles} cycles remaining"
                    else:
                        action = policy_engine.evaluate_and_heal(anomaly)

                    if args.tui:
                        dashboard.update_view(
                            metrics=metrics,
                            anomaly_score=anomaly.get('score', 0.0),
                            threshold=config.get('ai', {}).get('anomaly_threshold', -0.5),
                            escalation_level=policy_engine.current_level_idx + 1,
                            action_name=action if action != "none" else "Monitoring",
                            stabilization_window=policy_engine.STABILIZATION_WINDOW,
                            last_action_timestamp=policy_engine.last_action_timestamp,
                            is_connected=True
                        )

                    if action == "[ MAINTENANCE REQUIRED ]":
                        policy_engine.current_level_idx = 4

                    time.sleep(interval)

                except Exception as e:
                    logger.error(f"Survivor Loop Error: {e}")
                    time.sleep(10)
                    continue
                
    except KeyboardInterrupt:
        if not args.tui:
            logger.info("Shutdown requested by user.")
        cleanup(config)
        if not args.tui:
            logger.info("Cleanup complete. Exiting.")

if __name__ == "__main__":
    import os
    main()
