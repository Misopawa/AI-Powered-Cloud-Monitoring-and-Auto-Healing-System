import time
import json
import os
import subprocess
import csv
from datetime import datetime
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
        # Path to status cache aligned with project structure
        self.cache_file = os.path.join("config", "status_cache.json")
        self.system_state_file = os.path.join("config", "system_state.json")
        self.forensics_file = "anomalies_forensics.csv"
        
        # Demo Mode logic
        self.demo_mode = self.mon_cfg.get('demo_mode', False)
        if self.demo_mode:
            self.cooldown_period = 30 # Presentation requirement
            logger.info("[ACTION] Demo Mode active. Cooldown reduced to %ds", self.cooldown_period)
        else:
            self.cooldown_period = self.policy_cfg.get('cooldown_period', 90)

        # Track state for escalation
        self.retries = 0
        self.current_level_idx = 0
        self.last_anomaly_type = None
        self.max_retries = self.policy_cfg.get('max_retries', 2)
        
        # 3. State Persistence (Memory Layer)
        self.timestamp_of_first_anomaly = None
        
        # Stabilization Window (Post-action cooling)
        self.STABILIZATION_WINDOW = 90 # Standard (seconds)
        self.last_action_timestamp = 0
        
        # Ensure config directory exists
        os.makedirs("config", exist_ok=True)
        
        # Load state from persistence
        self._load_state()
        self._load_system_state()
        
    def _load_system_state(self):
        """Logic: Create a simple system_state.json file."""
        if os.path.exists(self.system_state_file):
            try:
                with open(self.system_state_file, 'r') as f:
                    state = json.load(f)
                    # On Startup: resume from the saved Level instead of resetting to Level 1
                    self.current_level_idx = state.get('current_escalation_level', 0)
                    self.timestamp_of_first_anomaly = state.get('timestamp_of_first_anomaly')
                    logger.info(f"[MEMORY] Resumed System State: Level Index {self.current_level_idx}, First Anomaly: {self.timestamp_of_first_anomaly}")
            except Exception as e:
                logger.error(f"Failed to load system state: {e}")

    def _save_system_state(self):
        """Data to Store: Save the current_escalation_level and the timestamp_of_first_anomaly."""
        try:
            state = {
                'current_escalation_level': self.current_level_idx,
                'timestamp_of_first_anomaly': self.timestamp_of_first_anomaly
            }
            with open(self.system_state_file, 'w') as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save system state: {e}")
        
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
            
            # Keep system state in sync
            self._save_system_state()
        except Exception as e:
            logger.error(f"Failed to save state cache: {e}")

    def _record_forensics(self, anomaly, level_executed):
        """4. Forensic Anomaly Snapshot (Research Layer)"""
        try:
            features = anomaly.get('features', {})
            score = anomaly.get('score', 0.0)
            timestamp = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
            
            file_exists = os.path.isfile(self.forensics_file)
            
            with open(self.forensics_file, 'a', newline='') as csvfile:
                fieldnames = ['timestamp', 'anomaly_score', 'executed_level'] + list(features.keys())
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                row = {
                    'timestamp': timestamp,
                    'anomaly_score': round(score, 4),
                    'executed_level': level_executed
                }
                row.update(features)
                writer.writerow(row)
                logger.info(f"[RESEARCH] Forensic snapshot recorded in {self.forensics_file}")
        except Exception as e:
            logger.error(f"Failed to record forensics: {e}")

    def evaluate_and_heal(self, anomaly):
        """
        Evaluate anomalies against the Policy Engine and trigger Hierarchical Recovery.
        Aligns with Chapter 3 5-Tier Escalation Path.
        """
        current_time = time.time()
        time_diff = current_time - self.last_action_timestamp
        
        # 3. Wait-and-Watch Logic
        if time_diff < self.STABILIZATION_WINDOW:
            logger.info(f"[STABILIZATION] System is currently in a stabilization window ({int(self.STABILIZATION_WINDOW - time_diff)}s remaining).")
            logger.info("[STABILIZATION] Skipping inference and 3-cycle counter check to allow services to initialize.")
            logger.info("[STABILIZATION] Waiting for Prometheus scraper to catch up with the newly restarted service state.")
            return "stabilization_skip"

        # 1. Fallback for Critical Data Loss
        if anomaly.get('critical_data_loss', False):
            logger.critical("[DETECTION] CRITICAL DATA LOSS detected! Bypassing inference and triggering Level 4 recovery.")
            # Trigger Level 4 immediately
            self.current_level_idx = 3 # Level 4 is index 3 in path [1,2,3,4,5]
            action_taken = self._trigger_level_action(4, "critical_data_loss")
            self._save_state()
            return action_taken

        if not anomaly.get('anomaly'):
            # System is healthy, reset escalation state if it was active
            if self.current_level_idx > 0 or self.retries > 0:
                logger.info("[ACTION] System healthy. Resetting escalation state.")
                self.reset_state()
                self.timestamp_of_first_anomaly = None
                self._save_system_state()
            return "none"

        # Record first anomaly timestamp for state persistence
        if self.timestamp_of_first_anomaly is None:
            self.timestamp_of_first_anomaly = time.time()
            self._save_system_state()

        # Determine anomaly type based on new feature names
        features = anomaly.get('features', {})
        load_1m = features.get('load1_norm', 0)
        mem_free = features.get('mem_free_ratio', 0)
        mem_total = features.get('mem_total_ratio', 1)
        mem_usage_percent = ((mem_total - mem_free) / mem_total) * 100

        if load_1m > 0.8: # CPU anomaly (0.8 = 80% load)
            anomaly_type = 'cpu'
        elif mem_usage_percent > 85: # Memory anomaly
            anomaly_type = 'memory'
        else:
            anomaly_type = 'general'

        # Default escalation path: 1 -> 2 -> 3 -> 4 -> 5
        path = [1, 2, 3, 4, 5]
        
        # Reset if anomaly type changed
        if anomaly_type != self.last_anomaly_type and self.last_anomaly_type is not None:
            logger.info(f"[ACTION] Anomaly type changed from {self.last_anomaly_type} to {anomaly_type}. Resetting path.")
            self.reset_state()
            
        self.last_anomaly_type = anomaly_type
            
        current_level = path[self.current_level_idx]
        
        action_taken = self._trigger_level_action(current_level, anomaly_type)
        
        # 4. Record forensics for Chapter 5
        self._record_forensics(anomaly, current_level)
        
        # Handle retries for Level 1 (Restart Service)
        if current_level == 1:
            if "failed" in action_taken or "verification_failed" in action_taken:
                # 2. Failure Handling: escalate immediately if verification failed
                logger.warning("[ACTION] Level 1 verification failed. Escalating immediately...")
                self.current_level_idx += 1
                self.retries = 0
            else:
                self.retries += 1
                if self.retries > self.max_retries:
                    logger.warning(f"[ACTION] Level 1 retry limit ({self.max_retries}) reached. Escalating to Level 2...")
                    self.current_level_idx += 1
                    self.retries = 0
        else:
            # Escalate immediately if level > 1 persists or verification failed
            if "verification_failed" in action_taken:
                logger.warning(f"[ACTION] Level {current_level} verification failed. Escalating immediately...")
            
            if self.current_level_idx < len(path) - 1:
                self.current_level_idx += 1
            
        self._save_state()
        
        if action_taken == "admin_escalation_halt":
            logger.critical("[ACTION] Level 5 reached. System in Halted state. Waiting for manual intervention.")
            # In a real system, we might set a 'halted' flag in state or config
            return action_taken

        # 2. Verification Failure Logic: skip stabilization window if verification failed
        if "verification_failed" in action_taken:
            logger.warning("[STABILIZATION] Verification failed. Skipping stabilization window to expedite recovery.")
            return action_taken

        logger.info(f"[ACTION] Cooldown: Entering {self.cooldown_period}s stabilization period...")
        time.sleep(self.cooldown_period)
        
        return action_taken

    def reset_state(self):
        self.retries = 0
        self.current_level_idx = 0
        self.last_anomaly_type = None
        self.timestamp_of_first_anomaly = None
        self._save_state()
        self._save_system_state()

    def _verify_service(self, service_name, docker_containers):
        """2. Post-Action Verification (Proof of Work Layer)"""
        if service_name in docker_containers:
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", service_name],
                    capture_output=True, text=True, check=True
                )
                is_running = result.stdout.strip().lower() == "true"
                if is_running:
                    logger.info(f"[VERIFICATION] Service {service_name} is RUNNING.")
                    return True
                else:
                    logger.error(f"[VERIFICATION] Service {service_name} is NOT RUNNING.")
                    return False
            except Exception as e:
                logger.error(f"[VERIFICATION] Failed to inspect docker container {service_name}: {e}")
                return False
        else:
            # LXC Status via Proxmox API
            try:
                proxmox = get_proxmox_client(self.config)
                status = proxmox.nodes(self.node).lxc(self.vmid).status.current.get()
                if status.get('status') == 'running':
                    logger.info(f"[VERIFICATION] LXC Container {self.vmid} is RUNNING.")
                    return True
                else:
                    logger.error(f"[VERIFICATION] LXC Container {self.vmid} is in state: {status.get('status')}")
                    return False
            except Exception as e:
                logger.error(f"[VERIFICATION] Failed to check LXC status via Proxmox: {e}")
                return False

    def _trigger_level_action(self, level, anomaly_type):
        """
        Implementation of the 5-Tier Escalation Hierarchy (Table 3.5).
        """
        proxmox = get_proxmox_client(self.config)
        service_name = self.mon_cfg.get('service_name', 'unknown-service')
        mon_infra = self.policy_cfg.get('monitoring_infrastructure', [])
        docker_containers = self.policy_cfg.get('docker_containers', [])

        if level == 1:
            logger.warning(f"[ACTION] [Level 1] Attempting Recovery for Service: {service_name} (Retry {self.retries + 1}/{self.max_retries + 1})")
            
            # Container-Aware Logic (Prometheus/Grafana etc)
            if service_name in docker_containers:
                logger.info(f"[ACTION] {service_name} identified as Docker container. Using docker restart.")
                try:
                    subprocess.run(["docker", "restart", service_name], check=True)
                    logger.info(f"[ACTION] Docker restart successful. Forcing 15s initialization wait...")
                    time.sleep(15)
                    
                    # 2. Verification
                    if self._verify_service(service_name, docker_containers):
                        self.last_action_timestamp = time.time()
                        self.STABILIZATION_WINDOW = 90
                        return "docker_restart_success"
                    else:
                        return "docker_restart_verification_failed"
                except Exception as e:
                    logger.error(f"Docker restart failed for {service_name}: {e}")
                    return "docker_restart_failed"
            
            # LXC-Aware Logic (Daemon inside LXC)
            logger.info(f"[ACTION] {service_name} identified as LXC daemon. Using Proxmox pct exec.")
            try:
                # pct exec <vmid> systemctl restart <service>
                proxmox.nodes(self.node).lxc(self.vmid).exec.post(command=f"systemctl restart {service_name}")
                time.sleep(5) # Give it a moment before verification
                
                # 2. Verification (LXC)
                if self._verify_service(service_name, docker_containers):
                    self.last_action_timestamp = time.time()
                    self.STABILIZATION_WINDOW = 90
                    return "pct_exec_restart_success"
                else:
                    return "pct_exec_verification_failed"
            except Exception as e:
                logger.error(f"Proxmox pct exec failed for {service_name}: {e}")
                return "pct_exec_restart_failed"
            
        elif level == 2:
            logger.warning(f"[ACTION] [Level 2] Process Reset: Identifying high-resource PIDs in LXC {self.vmid}")
            try:
                # Identify and terminate high-resource processes using pct exec
                # This is a simplified implementation that kills the top CPU process
                cmd = "ps -eo pid,ppid,%cpu,%mem,comm --sort=-%cpu | head -n 2 | tail -n 1 | awk '{print $1}'"
                result = proxmox.nodes(self.node).lxc(self.vmid).exec.post(command=f"bash -c \"kill -9 $({cmd})\"")
                logger.info(f"[ACTION] Process reset triggered for high-resource PID in LXC {self.vmid}")
                
                self.last_action_timestamp = time.time()
                self.STABILIZATION_WINDOW = 90
                return "process_reset_success"
            except Exception as e:
                logger.error(f"Process reset failed in LXC {self.vmid}: {e}")
                return "process_reset_failed"
            
        elif level == 3:
            logger.warning(f"[ACTION] [Level 3] Traffic Rerouting triggered for {anomaly_type} anomaly")
            # Simulated traffic redirection logic
            logger.info("[SIMULATION] Updating IP tables / Nginx config to redirect traffic to backup node...")
            self.last_action_timestamp = time.time()
            self.STABILIZATION_WINDOW = 90
            return "traffic_reroute_simulated"
            
        elif level == 4:
            logger.warning(f"[ACTION] [Level 4] Resource Isolation & Container Soft Reboot (VMID {self.vmid})")
            try:
                # Trigger a soft reboot via Proxmox API
                proxmox.nodes(self.node).lxc(self.vmid).status.reboot.post()
                logger.info(f"[ACTION] Soft reboot initiated for LXC {self.vmid}")
                
                # 2. Verification (Wait for container to at least start rebooting/accessible)
                time.sleep(10)
                if self._verify_service(service_name, docker_containers):
                    # OS boot logic: 4. Intelligence for Level 4 (Reboot) - Extended 120s window
                    self.last_action_timestamp = time.time()
                    self.STABILIZATION_WINDOW = 120
                    logger.info("[ACTION] Level 4 reboot triggered. Extending stabilization window to 120s for OS boot.")
                    return "lxc_soft_reboot"
                else:
                    return "lxc_reboot_verification_failed"
            except Exception as e:
                logger.error(f"Proxmox soft reboot failed for LXC {self.vmid}: {e}")
                return "lxc_soft_reboot_failed"
            
        elif level == 5:
            logger.critical(f"[ACTION] [Level 5] CRITICAL: Automated loop halted. Manual intervention required!")
            # Log to a simulated database or specific audit log
            logger.info(f"[AUDIT] Failure logged for VMID {self.vmid}. Anomaly Type: {anomaly_type}. Escalating to Admin.")
            return "admin_escalation_halt"
            
        return "unknown_action"
            
        return "unknown_action"
