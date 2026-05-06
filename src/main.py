import time
import argparse
import subprocess
import os
import gc
import sys
import logging
import json
from rich.console import Console
from utils.config_loader import load_config
from utils.logger import get_logger
from data.collector import PrometheusCollector
from ai.anomaly_detector import AnomalyDetector
from healing.auto_healer import PolicyEngine
from utils.data_handler import save_metrics_to_csv, log_historical_score
from utils.notifier import TelegramNotifier
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

    try:
        metrics_path = os.path.join("data", "metrics.csv")
        if os.path.exists(metrics_path):
            os.remove(metrics_path)
    except Exception as e:
        logger.error(f"Cold start metrics cleanup failed: {e}")

    # Load configuration
    config = load_config("config/config.yaml")
    prometheus_collector = PrometheusCollector(config)
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
    if args.tui:
        interval = 5
    
    # Initialize Layers
    prometheus_collector = PrometheusCollector()
    detector = AnomalyDetector(config)
    telegram_notifier = TelegramNotifier()
    startup_notification_sent = False
    if telegram_notifier.is_active:
        startup_notification_sent = telegram_notifier.send("🚀 System Initialized: 48-hour Behavioral Study started.", min_interval_seconds=60)
    policy_engine = PolicyEngine(config, notifier=telegram_notifier if telegram_notifier.is_active else None)
    policy_engine.current_level_idx = 0
    policy_engine.current_level = 0
    policy_engine.is_halted = False
    if not os.path.exists(policy_engine.threshold_file):
        try:
            os.makedirs(os.path.dirname(policy_engine.threshold_file), exist_ok=True)
            with open(policy_engine.threshold_file, "w") as f:
                json.dump({"threshold": float(policy_engine.threshold), "updated_at": time.time()}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to initialize threshold file: {e}")
    
    # TUI Initialization
    dashboard = HealingDashboard(config, collector=prometheus_collector)
    if args.tui:
        os.makedirs("logs", exist_ok=True)
        _configure_tui_logging()
        dashboard = HealingDashboard(config, collector=prometheus_collector)
        dashboard.set_telegram_active(bool(telegram_notifier.is_active))
        prom_url = str(getattr(prometheus_collector, "url", "") or (prometheus_collector.cfg or {}).get("prometheus_url") or "").strip()
        if bool(getattr(prometheus_collector, "connection_ok", False)):
            dashboard.set_source_label(prom_url.replace("http://", "").replace("https://", ""))
        else:
            dashboard.set_source_label(prom_url.replace("http://", "").replace("https://", ""))
        net_label = None
        stg_label = None
        try:
            net_label = str((prometheus_collector.cfg or {}).get("network_device") or "") or None
            storage_device = str((prometheus_collector.cfg or {}).get("storage_device") or "") or ""
            if "pve-vm--" in storage_device and "--disk" in storage_device:
                vm_part = storage_device.split("pve-vm--", 1)[1].split("--disk", 1)[0]
                if vm_part:
                    stg_label = "pve-vm-" + vm_part.replace("--", "-")
            if not stg_label and storage_device:
                stg_label = os.path.basename(storage_device)
        except Exception:
            net_label = None
            stg_label = None
        dashboard.set_prometheus_labels(network_device=net_label, storage_label=stg_label)
        if startup_notification_sent:
            dashboard.ui_messages.append("[TELEGRAM] System Initialized notification sent.")
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
    last_threshold_check = 0.0
    last_heal_time = 0.0
    smoothed_score = 0.0
    start_time = time.time()
    warmup_finished_alert_sent = False
    last_heartbeat_time = time.time()

    if args.tui:
        from rich.live import Live
        # This starts the full-screen dashboard mode
        with Live(dashboard.layout, refresh_per_second=1, screen=True):
            while True:
                # 1. Scrape live data from 127.0.0.1:9090
                prometheus_collector.scrape()
                
                # 2. Update the TUI panels with the results
                dashboard.update_metrics()
                
                # 3. Wait 5 seconds for the next cycle
                time.sleep(5)
    else:
        # Headless mode for background monitoring
        logger.info("Starting headless monitoring mode...")
        while True:
            prometheus_collector.scrape()
            # In a real run, you'd call your anomaly detection logic here
            time.sleep(5)

    try:
        tui_console = None
        if args.tui:
            tui_console = Console(file=sys.stdout)
            sys.stdout = open("logs/stdout.log", "a", encoding="utf-8")
            sys.stderr = open("logs/stderr.log", "a", encoding="utf-8")
            tui_console.clear()
            dashboard.enable_key_listener()
        with Live(dashboard.generate_layout(), refresh_per_second=4, auto_refresh=True, screen=True, console=tui_console) if args.tui else open(os.devnull, 'w') as live:
            while True:
                try:
                    if time.time() - last_gc_time >= 3600:
                        gc.collect()
                        last_gc_time = time.time()

                    if not args.tui:
                        logger.info("--------------------------- NEW CYCLE ---------------------------")

                    if args.tui:
                        dashboard.poll_keys()

                    metrics = prometheus_collector.collect()
                    if args.tui:
                        dashboard.update_metrics()
                    connected = metrics is not None
                    if args.tui:
                        src_status = str(getattr(prometheus_collector, "source_status", "") or "").strip()
                        if src_status.startswith("CONNECTED"):
                            dashboard.set_source_label(prometheus_collector.prometheus_url.replace("http://", "").replace("https://", ""))
                        else:
                            prom_url = str(getattr(prometheus_collector, "url", "") or (prometheus_collector.cfg or {}).get("prometheus_url") or "").strip()
                            dashboard.set_source_label(prom_url.replace("http://", "").replace("https://", ""))

                    if not connected:
                        logger.warning("[DETECTOR] Empty metrics input (collector returned None). Skipping analysis.")
                        if args.tui:
                            dashboard.current_level = policy_engine.current_level
                            dashboard.update_view(
                                metrics={},
                                anomaly_score=0.0,
                                threshold=float(policy_engine.threshold),
                                escalation_level=policy_engine.current_level,
                                action_name="API Gap/Reboot",
                                stabilization_window=policy_engine.STABILIZATION_WINDOW,
                                last_action_timestamp=policy_engine.last_action_timestamp,
                                is_connected=False,
                                raw_score=0.0,
                                decision_heads={},
                                cycle_count=cycle_count,
                                culprits=[],
                                next_calibration_in=None,
                            )
                        time.sleep(interval)
                        cycle_count += 1
                        continue

                    if monitoring_cfg.get('save_to_csv'):
                        save_metrics_to_csv(metrics)

                    if metrics.get('critical_data_loss', False):
                        raw_score = 0.0
                        if cycle_count == 0:
                            smoothed_score = raw_score
                        else:
                            smoothed_score = (0.2 * raw_score) + (0.8 * smoothed_score)
                        anomaly = {
                            "anomaly": False,
                            "critical_data_loss": True,
                            "features": metrics,
                            "score": smoothed_score,
                            "raw_score": raw_score,
                        }
                    else:
                        now = time.time()
                        if now - last_threshold_check >= 60:
                            last_threshold_check = now
                            try:
                                with open(policy_engine.threshold_file, "r") as f:
                                    threshold_state = json.load(f) or {}
                                updated_at = float(threshold_state.get("updated_at", 0) or 0)
                                if now - updated_at >= 7 * 24 * 60 * 60:
                                    new_threshold = policy_engine.update_dynamic_threshold()
                                    if new_threshold is not None:
                                        policy_engine.threshold = float(new_threshold)
                            except Exception as e:
                                logger.error(f"Threshold check failed: {e}")

                        detector.ai_cfg["anomaly_threshold"] = float(policy_engine.threshold)
                        config.setdefault("ai", {})["anomaly_threshold"] = float(policy_engine.threshold)
                        try:
                            anomaly = detector.detect_anomaly(metrics)
                        except Exception as e:
                            logger.error("[DETECTOR] detect_anomaly failed: %s", str(e))
                            anomaly = None
                        if not isinstance(anomaly, dict):
                            anomaly = {"anomaly": False, "threshold": 70.0, "culprits": [], "heads": {}, "features": metrics, "status": "Initializing...", "next_calibration_in": None}
                        raw_score = float(anomaly.get("score", 0.0) or 0.0)
                        if cycle_count == 0:
                            smoothed_score = raw_score
                        else:
                            smoothed_score = (0.2 * raw_score) + (0.8 * smoothed_score)
                        anomaly["raw_score"] = raw_score
                        anomaly["score"] = float(raw_score)
                        anomaly["cycle_count"] = int(cycle_count)
                        logger.info(
                            "[ANOMALY_SCORE] %.4f culprits=%s",
                            float(raw_score),
                            ",".join(list(anomaly.get("culprits") or [])),
                        )

                        if args.tui and anomaly.get('anomaly'):
                            culprits = anomaly.get('culprits', [])
                            for culprit in culprits:
                                value_key = {"CPU": "cpu_usage_pct", "MEMORY": "mem_used_pct", "STORAGE": "storage_used_pct", "NETWORK": "network_pct"}.get(culprit, "unknown")
                                value = metrics.get(value_key, 0.0)
                                dashboard.ui_messages.append(f"[bold red]⚠️ ANOMALY: {culprit} at {value:.1f}%[/bold red]")
                            # Log to forensics
                            import csv
                            with open(dashboard.forensics_file, "a", newline="") as f:
                                writer = csv.writer(f)
                                writer.writerow([datetime.now().isoformat(), anomaly.get("score", 0.0), policy_engine.current_level])

                    current_time = time.time()
                    if args.tui and dashboard.resume_requested:
                        dashboard.resume_requested = False
                        action = policy_engine.manual_resume()
                        smoothed_score = float(raw_score)
                        last_heal_time = time.time()
                        dashboard.current_level = policy_engine.current_level
                        dashboard.update_view(
                            metrics=metrics,
                            anomaly_score=float(smoothed_score),
                            threshold=float(policy_engine.threshold),
                            escalation_level=policy_engine.current_level,
                            action_name=action,
                            stabilization_window=policy_engine.STABILIZATION_WINDOW,
                            last_action_timestamp=policy_engine.last_action_timestamp,
                            is_connected=True,
                            raw_score=float(raw_score),
                            decision_heads=anomaly.get("heads", {}) if isinstance(anomaly, dict) else {},
                            cycle_count=cycle_count,
                            culprits=anomaly.get("culprits", []) if isinstance(anomaly, dict) else [],
                            next_calibration_in=anomaly.get("next_calibration_in", None) if isinstance(anomaly, dict) else None,
                        )
                        time.sleep(interval)
                        cycle_count += 1
                        continue

                    if (current_time - start_time) < 30:
                        action = "[ INITIALIZING... ]"
                        if args.tui:
                            dashboard.current_level = policy_engine.current_level
                            dashboard.update_view(
                                metrics=metrics,
                                anomaly_score=anomaly.get('score', 0.0),
                                threshold=float(policy_engine.threshold),
                                escalation_level=policy_engine.current_level,
                                action_name=action,
                                stabilization_window=policy_engine.STABILIZATION_WINDOW,
                                last_action_timestamp=policy_engine.last_action_timestamp,
                                is_connected=True,
                                raw_score=anomaly.get("raw_score", anomaly.get("score", 0.0)),
                                decision_heads=anomaly.get("heads", {}) if isinstance(anomaly, dict) else {},
                                cycle_count=cycle_count,
                                culprits=anomaly.get("culprits", []) if isinstance(anomaly, dict) else [],
                                next_calibration_in=anomaly.get("next_calibration_in", None) if isinstance(anomaly, dict) else None,
                            )
                        time.sleep(interval)
                        cycle_count += 1
                        continue

                    log_historical_score(anomaly.get("score", 0.0))

                    if cycle_count < 20:
                        action = f"[ WARMING UP {cycle_count}/20 ]"
                    elif not warmup_finished_alert_sent:
                        warmup_finished_alert_sent = True
                        if telegram_notifier.is_active:
                            telegram_notifier.send("🚀 Monitoring Active. System stabilized at Level 0.", min_interval_seconds=60)
                        action = "none"
                    else:
                        now = time.time()
                        if (now - last_heal_time) < 60:
                            remaining = max(0, int(60 - (now - last_heal_time)))
                            action = f"[ COOLDOWN ] Healing blocked for {remaining}s"
                        else:
                            action = policy_engine.execute_remediation(anomaly)
                            if action not in ("none", "stabilization_skip", "sanity_skip") and not str(action).startswith("manual_resume_cooldown_") and not str(action).startswith("[ VERIFYING"):
                                last_heal_time = now

                    if args.tui:
                        dashboard.current_level = policy_engine.current_level
                        dashboard.update_view(
                            metrics=metrics,
                            anomaly_score=anomaly.get('score', 0.0),
                            threshold=float(policy_engine.threshold),
                            escalation_level=policy_engine.current_level,
                            action_name=action if action != "none" else "Monitoring",
                            stabilization_window=policy_engine.STABILIZATION_WINDOW,
                            last_action_timestamp=policy_engine.last_action_timestamp,
                            is_connected=True,
                            raw_score=anomaly.get("raw_score", anomaly.get("score", 0.0)),
                            decision_heads=anomaly.get("heads", {}) if isinstance(anomaly, dict) else {},
                            cycle_count=cycle_count,
                            culprits=anomaly.get("culprits", []) if isinstance(anomaly, dict) else [],
                            next_calibration_in=anomaly.get("next_calibration_in", None) if isinstance(anomaly, dict) else None,
                        )

                    if telegram_notifier.is_active and isinstance(anomaly, dict) and (anomaly.get('anomaly') or float(anomaly.get('score', 0.0) or 0.0) > float(policy_engine.threshold)):
                        alert_message = f"⚠️ Anomaly Alert: score={float(anomaly.get('score', 0.0)):.4f} threshold={float(policy_engine.threshold):.1f} action={action}"
                        alert_sent = telegram_notifier.send(alert_message, min_interval_seconds=60)
                        if alert_sent and args.tui:
                            dashboard.ui_messages.append(f"[TELEGRAM] {alert_message}")

                    if action == "[ MAINTENANCE REQUIRED ]":
                        policy_engine.current_level_idx = 4
                        policy_engine.current_level = 5

                    now = time.time()
                    if telegram_notifier.is_active and (now - last_heartbeat_time) >= (24 * 60 * 60):
                        last_heartbeat_time = now
                        heartbeat_message = f"🏠 Daily Status Summary: Score={float(smoothed_score):.4f}, Threshold={float(policy_engine.threshold):.1f}, Cycle={cycle_count}."
                        heartbeat_sent = telegram_notifier.send(heartbeat_message, min_interval_seconds=60)
                        if heartbeat_sent and args.tui:
                            dashboard.ui_messages.append(f"[TELEGRAM] {heartbeat_message}")

                    time.sleep(interval)
                    cycle_count += 1

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
    finally:
        if args.tui and dashboard is not None:
            dashboard.disable_key_listener()

if __name__ == "__main__":
    import os
    main()
