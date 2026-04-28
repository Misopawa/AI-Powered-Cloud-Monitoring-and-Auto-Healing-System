import json
import os
import time
from typing import Any, Dict, Optional

import requests


class PrometheusCollector:
    def __init__(self, config_path: str = None, timeout_seconds: int = 8):
        self.config_path = config_path or os.path.join("config", "prometheus_config.json")
        self.timeout_seconds = int(timeout_seconds)
        self.cfg = self._load_config()
        self._last_values = {}

    def _load_config(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            return {}
        return {}

    def _query(self, promql: str) -> Optional[float]:
        url = str(self.cfg.get("prometheus_url") or "").rstrip("/")
        if not url or "<PROMETHEUS_IP>" in url:
            return None
        endpoint = f"{url}/api/v1/query"

        try:
            resp = requests.get(endpoint, params={"query": promql}, timeout=self.timeout_seconds)
            data = resp.json() if resp.ok else None
            if not data or data.get("status") != "success":
                return None
            results = ((data.get("data") or {}).get("result")) or []
            if not results:
                return None
            value = (results[0].get("value") or [None, None])[1]
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    def collect(self) -> Optional[Dict[str, float]]:
        base_selector = str(self.cfg.get("label_selector") or "").strip()
        base_selector = base_selector.strip()
        base_selector = base_selector.strip("{}").strip()

        def sel(extra: str = "") -> str:
            if base_selector and extra:
                return "{" + base_selector + "," + extra + "}"
            if base_selector:
                return "{" + base_selector + "}"
            if extra:
                return "{" + extra + "}"
            return ""

        cpu_q = '1 - avg(irate(node_cpu_seconds_total' + sel('mode="idle"') + '[1m]))'
        mem_q = "node_memory_Active_bytes" + sel() + " / node_memory_MemTotal_bytes" + sel()
        job_name = str(self.cfg.get("job_name") or "").strip()
        website_url = str(self.cfg.get("website_url") or "").strip()
        latency_threshold_ms = float(self.cfg.get("network_latency_threshold_ms") or 500.0)
        retrans_threshold = float(self.cfg.get("network_retrans_threshold") or 5.0)

        latency_ms_q = None
        probe_success_q = None
        if website_url:
            latency_ms_q = 'avg(probe_duration_seconds{instance="' + website_url + '"}) * 1000'
            probe_success_q = 'min(probe_success{instance="' + website_url + '"})'
        if not latency_ms_q:
            if job_name:
                latency_ms_q = 'avg(node_netstat_Tcp_RtoAlgorithm{job="' + job_name + '"}) * 1000'
            else:
                latency_ms_q = "avg(node_netstat_Tcp_RtoAlgorithm) * 1000"

        if job_name:
            retrans_q = 'irate(node_netstat_Tcp_RetransSegs{job="' + job_name + '"}[1m])'
        else:
            retrans_q = "irate(node_netstat_Tcp_RetransSegs[1m])"

        mountpoint = str(self.cfg.get("storage_mountpoint") or "/")
        storage_device = str(self.cfg.get("storage_device") or "").strip()
        if storage_device:
            extra = 'device="' + storage_device + '"'
            if job_name:
                extra = extra + ', job="' + job_name + '"'
            storage_q = "1 - (node_filesystem_avail_bytes{" + extra + "} / node_filesystem_size_bytes{" + extra + "})"
        else:
            storage_extra = f'mountpoint="{mountpoint}",fstype!~"tmpfs|overlay|squashfs"'
            storage_q = (
                "(1 - (node_filesystem_avail_bytes" + sel(storage_extra) + " / "
                "node_filesystem_size_bytes" + sel(storage_extra) + "))"
            )

        cpu = self._query(cpu_q)
        mem = self._query(mem_q)
        latency_ms = self._query(latency_ms_q) if latency_ms_q else None
        retrans_per_sec = self._query(retrans_q)
        probe_success = self._query(probe_success_q) if probe_success_q else None
        storage = self._query(storage_q)

        if cpu is None:
            cpu = self._last_values.get("cpu")
        if mem is None:
            mem = self._last_values.get("mem")
        if cpu is None or mem is None:
            return None
        self._last_values["cpu"] = float(cpu)
        self._last_values["mem"] = float(mem)

        def clamp01(x: float) -> float:
            try:
                return max(0.0, min(1.0, float(x)))
            except Exception:
                return 0.0

        if latency_ms is None:
            latency_ms = self._last_values.get("net_latency_ms")
        if retrans_per_sec is None:
            retrans_per_sec = self._last_values.get("net_retrans_per_sec")
        if probe_success is None:
            probe_success = self._last_values.get("probe_success")
        if storage is None:
            storage = self._last_values.get("storage_ratio")

        network_health_ratio = 1.0
        if probe_success is not None and float(probe_success) <= 0.0:
            network_health_ratio = 0.0
        elif latency_ms is not None and float(latency_ms) > 0:
            network_health_ratio = clamp01(float(latency_threshold_ms) / float(latency_ms))

        if latency_ms is not None:
            self._last_values["net_latency_ms"] = float(latency_ms)
        if retrans_per_sec is not None:
            self._last_values["net_retrans_per_sec"] = float(retrans_per_sec)
        if probe_success is not None:
            self._last_values["probe_success"] = float(probe_success)
        if storage is not None:
            self._last_values["storage_ratio"] = float(storage)

        return {
            "timestamp": float(time.time()),
            "cpu_usage_ratio": clamp01(cpu),
            "mem_used_ratio": clamp01(mem),
            "storage_used_ratio": clamp01(storage if storage is not None else 0.0),
            "network_ratio": clamp01(network_health_ratio),
            "network_latency_ms": float(latency_ms or 0.0),
            "network_retrans_per_sec": float(retrans_per_sec or 0.0),
            "probe_success": float(probe_success) if probe_success is not None else 1.0,
            "network_latency_threshold_ms": float(latency_threshold_ms),
            "network_retrans_threshold": float(retrans_threshold),
            "critical_data_loss": False,
        }
