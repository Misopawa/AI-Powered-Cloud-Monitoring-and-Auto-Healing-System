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
    Handles the 'Boot-up Gap' where API returns None or 0 for CPU/Memory.
    """
    prox_cfg = config.get('proxmox', {})
    node = prox_cfg.get('node', 'pve')
    vmid = prox_cfg.get('vmid', 101)
    
    proxmox = get_proxmox_client(config)
    
    # Fetch LXC status/current metrics
    status = proxmox.nodes(node).lxc(vmid).status.current.get()
    
    # Robust Parsing (The "Null" Guard)
    # Proxmox returns None/0 for about 15-30s during container boot
    cpu_raw = status.get('cpu')
    mem_raw = status.get('mem')
    max_mem = status.get('maxmem', 1)
    disk_raw = status.get('disk')
    max_disk = status.get('maxdisk', 1)
    
    is_booting = False
    if cpu_raw is None or mem_raw is None or cpu_raw == 0 or mem_raw == 0:
        is_booting = True
    
    cpu_usage = (cpu_raw * 100) if cpu_raw is not None else 0.0
    mem_usage = ((mem_raw / max_mem) * 100) if mem_raw is not None else 0.0
    disk_usage = ((disk_raw / max_disk) * 100) if disk_raw is not None else 0.0
    
    # Fetch Network metrics
    net_in = status.get('netin', 0)
    net_out = status.get('netout', 0)
    
    return {
        'timestamp': time.time(),
        'cpu_usage_percent': round(cpu_usage, 2),
        'memory_usage_percent': round(mem_usage, 2),
        'disk_usage_percent': round(disk_usage, 2),
        'net_in_bytes': net_in,
        'net_out_bytes': net_out,
        'net_errin': 0,
        'net_errout': 0,
        'net_dropin': 0,
        'net_dropout': 0,
        'is_booting': is_booting  # Flag for the AI to ignore
    }
