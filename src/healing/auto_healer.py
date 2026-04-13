import time
import json
import os
from utils.logger import get_logger
from monitoring.metrics_collector import get_proxmox_client

logger = get_logger(__name__)

class PolicyEngine:
    def __init__(self, config):
        self.config = config
        self.policy_cfg = config.get('policies', {})
        self.mon_cfg = config.get('monitoring', {})
        self.prox_cfg = config.get('proxmox', {})
        self.vmid = self.prox_cfg.get('vmid', 101)
        self.node = self.prox_cfg.get('node', 'pve')
        self.cache_file = "status_cache.json"
        
        # Demo Mode logic
        self.demo_mode = self.mon_cfg.get('demo_mode', False)
        if self.demo_mode:
            self.cooldown_period = self.mon_cfg.get('demo_cooldown', 30)
            logger.info("[ACTION] Demo Mode active. Cooldown reduced to %ds", self.cooldown_period)
        else:
            self.cooldown_period = self.policy_cfg.get('cooldown_period', 90)

        # Track state for escalation
        self.retries = 0
        self.current_level_idx = 0
        self.last_anomaly_type = None
        self.max_retries = self.policy_cfg.get('max_retries', 2)
        
        # Load state from persistence
        self._load_state()
        
    def _load_state(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    state = json.load(f)
                    vm_state = state.get(str(self.vmid), {})
                    self.current_level_idx = vm_state.get('level_idx', 0)
                    self.retries = vm_state.get('retries', 0)
                    self.last_anomaly_type = vm_state.get('anomaly_type')
                    if self.current_level_idx > 0:
                        logger.info(f"[ACTION] Resumed escalation state for VMID {self.vmid}: Level Index {self.current_level_idx}")
            except Exception as e:
                logger.error(f"Failed to load state cache: {e}")

    def _save_state(self):
        try:
            state = {}
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    state = json.load(f)
            
            state[str(self.vmid)] = {
                'level_idx': self.current_level_idx,
                'retries': self.retries,
                'anomaly_type': self.last_anomaly_type,
                'last_updated': time.time()
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save state cache: {e}")

    def _get_path(self, anomaly_type):
        paths = self.policy_cfg.get('escalation_paths', {})
        return paths.get(anomaly_type, [1, 2, 4, 5])

    def evaluate_and_heal(self, anomaly):
        """
        Evaluate anomalies against the Policy Engine and trigger Hierarchical Recovery.
        """
        if not anomaly.get('anomaly'):
            # System is healthy, reset escalation state if it was active
            if self.current_level_idx > 0 or self.retries > 0:
                logger.info("[ACTION] System healthy. Resetting escalation state.")
                self.reset_state()
            return "none"

        # Determine anomaly type
        features = anomaly.get('features', {})
        if features.get('net_in_bytes', 0) > 1000000: # Example: high traffic
            anomaly_type = 'network'
        elif features.get('cpu_usage_percent', 0) > 80:
            anomaly_type = 'cpu'
        elif features.get('memory_usage_percent', 0) > 80:
            anomaly_type = 'memory'
        else:
            anomaly_type = 'cpu'

        path = self._get_path(anomaly_type)
        
        # Reset if anomaly type changed
        if anomaly_type != self.last_anomaly_type and self.last_anomaly_type is not None:
            logger.info(f"[ACTION] Anomaly type changed from {self.last_anomaly_type} to {anomaly_type}. Resetting path.")
            self.reset_state()
            
        self.last_anomaly_type = anomaly_type
            
        current_level = path[self.current_level_idx]
        
        action_taken = self._trigger_level_action(current_level, anomaly_type)
        
        # Handle retries for Level 1
        if current_level == 1:
            self.retries += 1
            if self.retries > self.max_retries:
                logger.warning(f"[ACTION] Level 1 retry limit ({self.max_retries}) reached. Escalating...")
                self.current_level_idx += 1
                self.retries = 0
        else:
            # Escalate immediately if level > 1 persists
            self.current_level_idx = min(self.current_level_idx + 1, len(path) - 1)
            
        self._save_state()
        
        logger.info(f"[ACTION] Cooldown: Entering {self.cooldown_period}s stabilization period...")
        time.sleep(self.cooldown_period)
        
        return action_taken

    def reset_state(self):
        self.retries = 0
        self.current_level_idx = 0
        self.last_anomaly_type = None
        self._save_state()

    def _trigger_level_action(self, level, anomaly_type):
        """
        Implement the 5-Tier Escalation actions.
        """
        proxmox = get_proxmox_client(self.config)
        
        if level == 1:
            logger.warning(f"[ACTION] [Level 1] Restarting services for {anomaly_type} anomaly (Retry {self.retries + 1})")
            return "restart_service"
            
        elif level == 2:
            logger.warning(f"[ACTION] [Level 2] Process Reset for {anomaly_type} anomaly (VMID {self.vmid})")
            try:
                proxmox.nodes(self.node).lxc(self.vmid).status.reboot.post()
            except Exception as e:
                logger.error(f"Proxmox reboot failed: {e}")
            return "process_reset"
            
        elif level == 3:
            logger.warning(f"[ACTION] [Level 3] Traffic Rerouting for Network anomaly")
            return "traffic_rerouting"
            
        elif level == 4:
            logger.warning(f"[ACTION] [Level 4] Resource Isolation for {anomaly_type} anomaly")
            return "resource_isolation"
            
        elif level == 5:
            logger.error(f"[ACTION] [Level 5] Escalation: Manual intervention required for {anomaly_type} anomaly!")
            return "escalate_to_admin"
            
        return "unknown_action"
