import time
from utils.config_loader import load_config
from utils.logger import get_logger
from monitoring.metrics_collector import collect_metrics
from ai.anomaly_detector import AnomalyDetector
from healing.auto_healer import PolicyEngine
from utils.data_handler import save_metrics_to_csv

logger = get_logger("AutoHealingEngine")

def main():
    logger.info("Starting Plug & Play Auto-Healing Engine...")

    # Load configuration
    config = load_config("config/config.yaml")
    monitoring_cfg = config.get('monitoring', {})
    
    # Demo Mode Override
    demo_mode = monitoring_cfg.get('demo_mode', False)
    if demo_mode:
        interval = monitoring_cfg.get("demo_interval", 2)
        logger.info("[ACTION] Demo Mode active. Polling interval reduced to %ds", interval)
    else:
        interval = monitoring_cfg.get("interval", 60)
    
    # Initialize Layers
    detector = AnomalyDetector(config)
    policy_engine = PolicyEngine(config)

    logger.info(f"System initialized. Monitoring LXC {config['proxmox']['vmid']} at {config['proxmox']['host']}")

    try:
        while True:
            try:
                # 1. Data Collection Layer
                logger.info("--------------------------- NEW CYCLE ---------------------------")
                metrics = collect_metrics(config)
                
                # Null Guard: Skip cycle if Proxmox API returns None (e.g. during reboot)
                if metrics is None:
                    logger.info("[DETECTION] API Gap/Reboot detected. Skipping cycle...")
                    time.sleep(interval)
                    continue

                # Log Telemetry with Westermo-aligned features
                load_1m = metrics.get('load-1m', 0)
                mem_free = metrics.get('sys-mem-free', 0)
                mem_total = metrics.get('sys-mem-total', 1)
                mem_usage = round(((mem_total - mem_free) / mem_total) * 100, 2)
                
                logger.info(f"[DETECTION] Telemetry: LOAD-1M={load_1m}, MEM={mem_usage}%")
                
                if monitoring_cfg.get('save_to_csv'):
                    save_metrics_to_csv(metrics)
                
                # 2. AI/ML Layer
                anomaly = detector.detect_anomaly(metrics)
                
                # 3. Auto-Healing Layer (Policy Engine & Validation Loop)
                action = policy_engine.evaluate_and_heal(anomaly)
                
                if action != "none":
                    logger.info(f"[ACTION] Hierarchical recovery '{action}' triggered. Waiting for stability...")

                # Wait for next interval
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(interval)
                
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

if __name__ == "__main__":
    main()
