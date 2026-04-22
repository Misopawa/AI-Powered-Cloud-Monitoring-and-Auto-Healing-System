import time
import argparse
import subprocess
from utils.config_loader import load_config
from utils.logger import get_logger
from monitoring.metrics_collector import collect_metrics
from ai.anomaly_detector import AnomalyDetector
from healing.auto_healer import PolicyEngine
from utils.data_handler import save_metrics_to_csv
from ui.dashboard_tui import HealingDashboard
from rich.live import Live

logger = get_logger("AutoHealingEngine")

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
    
    # TUI Initialization
    dashboard = None
    if args.tui:
        dashboard = HealingDashboard(config)

    if not args.tui:
        logger.info(f"System initialized. Monitoring LXC {config['proxmox']['vmid']} at {config['proxmox']['host']}")

    try:
        # Wrap the main loop in Live context if TUI is enabled
        with Live(dashboard.layout, refresh_per_second=1, screen=True) if args.tui else open(os.devnull, 'w') as live:
            while True:
                try:
                    # 1. Data Collection Layer
                    if not args.tui:
                        logger.info("--------------------------- NEW CYCLE ---------------------------")
                    metrics = collect_metrics(config)
                    connected = metrics is not None
                    
                    # Null Guard: Skip cycle if Proxmox API returns None (e.g. during reboot)
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
                        else:
                            logger.info("[DETECTION] API Gap/Reboot detected. Skipping cycle...")
                        time.sleep(interval)
                        continue

                    # Log Telemetry
                    if not args.tui:
                        load_1m = metrics.get('load-1m', 0)
                        mem_free = metrics.get('sys-mem-free', 0)
                        mem_total = metrics.get('sys-mem-total', 1)
                        mem_usage = round(((mem_total - mem_free) / mem_total) * 100, 2)
                        logger.info(f"[DETECTION] Telemetry: LOAD-1M={load_1m}, MEM={mem_usage}%")
                    
                    if monitoring_cfg.get('save_to_csv'):
                        save_metrics_to_csv(metrics)
                    
                    # 2. AI/ML Layer
                    if metrics.get('critical_data_loss', False):
                        anomaly = {"anomaly": False, "critical_data_loss": True, "features": metrics, "score": 0.0}
                    else:
                        anomaly = detector.detect_anomaly(metrics)
                    
                    # 3. Auto-Healing Layer (Policy Engine & Validation Loop)
                    action = policy_engine.evaluate_and_heal(anomaly)
                    
                    # TUI Update
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

                    if action == "admin_escalation_halt":
                        if not args.tui:
                            logger.critical("SYSTEM HALTED. Level 5 escalation reached. Manual intervention required.")
                        break
                    
                    if action != "none" and not args.tui:
                        logger.info(f"[ACTION] Hierarchical recovery '{action}' triggered. Waiting for stability...")

                    # Wait for next interval
                    time.sleep(interval)
                    
                except Exception as e:
                    if not args.tui:
                        logger.error(f"Error in main loop: {e}")
                    time.sleep(interval)
                
    except KeyboardInterrupt:
        if not args.tui:
            logger.info("Shutdown requested by user.")
        cleanup(config)
        if not args.tui:
            logger.info("Cleanup complete. Exiting.")

if __name__ == "__main__":
    import os
    main()
