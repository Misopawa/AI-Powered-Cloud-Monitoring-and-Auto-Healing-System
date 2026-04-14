from proxmoxer import ProxmoxAPI
import time
import urllib3

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
    
    # Map Proxmox cpu to load-1m
    # Use direct decimal values to match Westermo dataset scale (e.g., 0.09)
    load_1m = round(float(cpu_raw), 4)
    
    # Map Proxmox mem and maxmem to sys-mem fields
    # Convert memory from Bytes to Gigabytes (GB)
    gb_divider = 1024 ** 3
    sys_mem_total = round(max_mem / gb_divider, 4)
    sys_mem_free = round((max_mem - mem_raw) / gb_divider, 4)
    sys_mem_available = sys_mem_free # Approximation

    
    # Required Features Alignment (Westermo headers)
    return {
        'timestamp': time.time(),
        'load-1m': load_1m,
        'load-5m': 0.0,
        'load-15m': 0.0,
        'sys-mem-swap-total': 0.0,
        'sys-mem-swap-free': 0.0,
        'sys-mem-free': sys_mem_free,
        'sys-mem-cache': 0.0,
        'sys-mem-buffered': 0.0,
        'sys-mem-available': sys_mem_available,
        'sys-mem-total': sys_mem_total,
        'sys-fork-rate': 0.0,
        'sys-interrupt-rate': 0.0
    }
