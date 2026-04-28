import math
from utils.logger import get_logger

logger = get_logger(__name__)

class AnomalyDetector:
    def __init__(self, config):
        self.config = config
        self.ai_cfg = config.get('ai', {})
        self.alpha = float(self.ai_cfg.get("head_ema_alpha", 0.05))
        self.std_k = float(self.ai_cfg.get("head_std_k", 3.0))
        self.head_states = {
            "CPU": {"mean": None, "var": 0.0},
            "MEMORY": {"mean": None, "var": 0.0},
            "STORAGE": {"mean": None, "var": 0.0},
        }
        self.net_latency_state = {"mean": None, "var": 0.0}
        self.net_retrans_state = {"mean": None, "var": 0.0}

    def detect_anomaly(self, metrics):
        if metrics is None:
            return {"anomaly": False, "score": 1.0, "skip": True, "culprits": [], "heads": {}}

        cpu = self._as_float(metrics.get("cpu_usage_ratio", metrics.get("load1_norm", 0.0)))
        mem = self._as_float(metrics.get("mem_used_ratio", 1.0 - self._as_float(metrics.get("mem_available_ratio", 1.0))))
        storage = self._as_float(metrics.get("storage_used_ratio", 0.0))
        net_ratio = self._as_float(metrics.get("network_ratio", 1.0))
        net_latency_ms = self._as_float(metrics.get("network_latency_ms", 0.0))
        net_retrans_per_sec = self._as_float(metrics.get("network_retrans_per_sec", 0.0))
        probe_success = self._as_float(metrics.get("probe_success", 1.0))
        net_latency_threshold_ms = self._as_float(metrics.get("network_latency_threshold_ms", 500.0), 500.0)
        net_retrans_threshold = self._as_float(metrics.get("network_retrans_threshold", 5.0), 5.0)

        heads = {}
        heads["CPU"] = self._eval_high_ratio_head("CPU", cpu, floor=0.85)
        heads["MEMORY"] = self._eval_high_ratio_head("MEMORY", mem, floor=0.85)
        heads["STORAGE"] = self._eval_high_ratio_head("STORAGE", storage, floor=0.90)
        heads["NETWORK"] = self._eval_network_qos_head(
            net_ratio,
            net_latency_ms,
            net_retrans_per_sec,
            probe_success,
            net_latency_threshold_ms,
            net_retrans_threshold,
        )

        culprits = []
        for name, info in heads.items():
            if info.get("anomaly"):
                culprits.append(name)
        net_info = heads.get("NETWORK") or {}
        if net_info.get("anomaly"):
            for tag in (net_info.get("tags") or []):
                if tag not in culprits:
                    culprits.append(tag)
        is_anomaly = bool(culprits)

        score = 1.0
        for info in heads.values():
            excess = float(info.get("excess_ratio", 0.0) or 0.0)
            score = min(score, max(0.0, 1.0 - excess))

        if is_anomaly:
            logger.warning("[DETECTION] Multi-head anomaly detected in %s", ",".join(culprits))
        else:
            logger.info("[DETECTION] System healthy (multi-head)")

        return {"anomaly": is_anomaly, "score": float(score), "features": metrics, "culprits": culprits, "heads": heads}

    def _as_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _eval_high_ratio_head(self, name: str, value: float, floor: float) -> dict:
        state = self.head_states.get(name) or {"mean": None, "var": 0.0}
        mean = state.get("mean")
        var = float(state.get("var", 0.0) or 0.0)

        if mean is None:
            state["mean"] = float(value)
            state["var"] = 0.0
            self.head_states[name] = state
            threshold = max(float(floor), float(value))
            return {
                "value": float(value),
                "baseline": float(value),
                "deviation": 0.0,
                "threshold": float(threshold),
                "anomaly": False,
                "excess_ratio": 0.0,
            }

        mean = float(mean)
        std = math.sqrt(max(0.0, var))
        threshold = max(float(floor), mean + (self.std_k * std))
        anomaly = bool(float(value) > float(threshold))
        deviation = abs(float(value) - float(mean))

        if not anomaly:
            diff = float(value) - mean
            mean = mean + (self.alpha * diff)
            var = (1.0 - self.alpha) * (var + (self.alpha * diff * diff))
            state["mean"] = float(mean)
            state["var"] = float(var)
            self.head_states[name] = state

        denom = max(1e-6, 1.0 - float(threshold))
        excess = max(0.0, (float(value) - float(threshold)) / denom)
        return {
            "value": float(value),
            "baseline": float(mean),
            "deviation": float(deviation),
            "threshold": float(threshold),
            "anomaly": anomaly,
            "excess_ratio": float(excess),
        }

    def _eval_network_qos_head(
        self,
        health_ratio: float,
        latency_ms: float,
        retrans_per_sec: float,
        probe_success: float,
        latency_threshold_ms: float,
        retrans_threshold: float,
    ) -> dict:

        tags = []
        is_site_down = bool(float(probe_success) <= 0.0)
        if is_site_down:
            tags.append("SITE_DOWN")
        if float(latency_ms) > float(latency_threshold_ms):
            tags.append("NET_LATENCY")
        if float(retrans_per_sec) > float(retrans_threshold):
            tags.append("NET_CONGESTION")

        anomaly = bool(tags)

        baseline_latency = self.net_latency_state.get("mean")
        baseline_retrans = self.net_retrans_state.get("mean")

        if baseline_latency is None:
            baseline_latency = float(latency_ms)
            self.net_latency_state["mean"] = float(latency_ms)
            self.net_latency_state["var"] = 0.0
        if baseline_retrans is None:
            baseline_retrans = float(retrans_per_sec)
            self.net_retrans_state["mean"] = float(retrans_per_sec)
            self.net_retrans_state["var"] = 0.0

        if not anomaly:
            lat_mean = float(self.net_latency_state.get("mean", latency_ms) or latency_ms)
            lat_var = float(self.net_latency_state.get("var", 0.0) or 0.0)
            lat_diff = float(latency_ms) - lat_mean
            lat_mean = lat_mean + (self.alpha * lat_diff)
            lat_var = (1.0 - self.alpha) * (lat_var + (self.alpha * lat_diff * lat_diff))
            self.net_latency_state["mean"] = float(lat_mean)
            self.net_latency_state["var"] = float(lat_var)

            rt_mean = float(self.net_retrans_state.get("mean", retrans_per_sec) or retrans_per_sec)
            rt_var = float(self.net_retrans_state.get("var", 0.0) or 0.0)
            rt_diff = float(retrans_per_sec) - rt_mean
            rt_mean = rt_mean + (self.alpha * rt_diff)
            rt_var = (1.0 - self.alpha) * (rt_var + (self.alpha * rt_diff * rt_diff))
            self.net_retrans_state["mean"] = float(rt_mean)
            self.net_retrans_state["var"] = float(rt_var)

        baseline_latency = float(self.net_latency_state.get("mean", baseline_latency) or baseline_latency)
        deviation_latency = abs(float(latency_ms) - baseline_latency)

        info = {
            "value": float(health_ratio),
            "baseline": float(baseline_latency),
            "deviation": float(deviation_latency),
            "threshold": float(latency_threshold_ms),
            "anomaly": anomaly,
            "excess_ratio": float(max(0.0, 1.0 - float(health_ratio))),
            "latency_ms": float(latency_ms),
            "retrans_per_sec": float(retrans_per_sec),
            "probe_success": float(probe_success),
            "site_down": bool(is_site_down),
            "tags": list(tags),
        }
        return info

    def _eval_high_rate_head(self, name: str, value_bps: float, floor_bps: float) -> dict:
        state = self.head_states.get(name) or {"mean": None, "var": 0.0}
        mean = state.get("mean")
        var = float(state.get("var", 0.0) or 0.0)

        if mean is None:
            state["mean"] = float(value_bps)
            state["var"] = 0.0
            self.head_states[name] = state
            threshold = max(float(floor_bps), float(value_bps))
            return {"value": float(value_bps), "threshold": float(threshold), "anomaly": False, "excess_ratio": 0.0}

        mean = float(mean)
        std = math.sqrt(max(0.0, var))
        threshold = max(float(floor_bps), mean + (self.std_k * std))
        anomaly = bool(float(value_bps) > float(threshold))

        if not anomaly:
            diff = float(value_bps) - mean
            mean = mean + (self.alpha * diff)
            var = (1.0 - self.alpha) * (var + (self.alpha * diff * diff))
            state["mean"] = float(mean)
            state["var"] = float(var)
            self.head_states[name] = state

        denom = max(1e-6, float(threshold))
        excess = max(0.0, (float(value_bps) - float(threshold)) / denom)
        return {"value": float(value_bps), "threshold": float(threshold), "anomaly": anomaly, "excess_ratio": float(excess)}
