from proxmoxer import ProxmoxAPI
import time
import urllib3
import math

# Suppress SSL warnings for local Proxmox connections
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_proxmox_client(config):
    """
    Initialize and return a Proxmox API client.
    """
    prox_cfg = config.get('proxmox', {})
    return ProxmoxAPI(
        prox_cfg.get('host'),
        user=prox_cfg.get('user'),
        password=prox_cfg.get('password'),
        verify_ssl=prox_cfg.get('verify_ssl', False)
    )

def collect_metrics(config):
    """
    Collect real-time telemetry from Proxmox for LXC 101.
    Aligns with Westermo system-1.csv feature vector requirements.
    Handles the 'Boot-up Gap' where API returns None or 0 for CPU/Memory.
    """
    prox_cfg = config.get('proxmox', {})
    node = prox_cfg.get('node', 'pve')
    vmid = prox_cfg.get('vmid', 101)
    
    proxmox = get_proxmox_client(config)
    
    # Fetch LXC status/current metrics
    try:
        status = proxmox.nodes(node).lxc(vmid).status.current.get()
    except Exception:
        return None # Null Guard: Skip if Proxmox API is unreachable
    
    # Robust Parsing (The "Null" Guard)
    cpu_raw = status.get('cpu')
    mem_raw = status.get('mem')
    max_mem = status.get('maxmem', 1)
    
    # If API returns None (during reboot), skip this cycle
    if cpu_raw is None or mem_raw is None:
        return None
    
    # Decimal Normalization [0,1]
    # CPU: Proxmox returns value in decimal (e.g. 0.5 for 50%). Use directly.
    load_1m = round(float(cpu_raw), 4)
    
    # Memory/Swap: Convert absolute byte values into ratios
    # Memory Ratio = current_usage / total_capacity
    sys_mem_total = float(max_mem)
    sys_mem_free = float(max_mem - mem_raw)
    sys_mem_available = sys_mem_free # Approximation
    
    # Normalized features (ratios)
    mem_ratio = round(mem_raw / max_mem, 4)
    free_ratio = round(sys_mem_free / max_mem, 4)
    available_ratio = round(sys_mem_available / max_mem, 4)

    # Required Features Alignment (Exactly 12 features in specific order)
    vector = {
        'timestamp': time.time(),
        'load-1m': load_1m,
        'load-5m': 0.0,
        'load-15m': 0.0,
        'sys-mem-free': free_ratio,
        'sys-mem-available': available_ratio,
        'sys-mem-total': 1.0, # Capacity as denominator for ratios
        'sys-mem-cache': 0.0,
        'sys-mem-buffered': 0.0,
        'sys-mem-swap-total': 1.0, # Placeholder ratio denominator
        'sys-mem-swap-free': 1.0,   # Placeholder ratio
        'sys-fork-rate': 0.0,
        'sys-interrupt-rate': 0.0
    }

    # 1. Data Sanitization (Anti-Crash Layer)
    for key, value in vector.items():
        if key == 'timestamp': continue
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return {**vector, 'critical_data_loss': True}
            
    return {**vector, 'critical_data_loss': False}
