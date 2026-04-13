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
                
                if metrics.get('is_booting'):
                    logger.info("[DETECTION] Boot-up Gap detected. Skipping analysis...")
                    time.sleep(interval)
                    continue

                logger.info(f"[DETECTION] Telemetry: CPU={metrics['cpu_usage_percent']}%, MEM={metrics['memory_usage_percent']}%")
                
                if monitoring_cfg.get('save_to_csv'):
                    save_metrics_to_csv(metrics)
                
                # 2. AI/ML Layer
                anomaly = detector.detect_anomaly(metrics)
                
                # 3. Auto-Healing Layer (Policy Engine & Validation Loop)
                action = policy_engine.evaluate_and_heal(anomaly)
                
                if action != "none":
                    logger.info(f"[ACTION] Healing action '{action}' executed. Waiting for stability...")

                # Wait for next interval
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(interval)
                
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

if __name__ == "__main__":
    main()
