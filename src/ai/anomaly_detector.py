import joblib
import pandas as pd
from pathlib import Path
from utils.logger import get_logger
from ai.train_model import train as retrain_model

logger = get_logger(__name__)

class AnomalyDetector:
    def __init__(self, config):
        self.config = config
        self.ai_cfg = config.get('ai', {})
        self.model_path = Path(self.ai_cfg.get('model_path', 'models/isolation_forest.pkl'))
        self.rolling_buffer = []
        self.buffer_size = self.ai_cfg.get('rolling_buffer_size', 1000)
        self.retrain_interval = self.ai_cfg.get('retrain_interval', 10)
        self.cycles_since_retrain = 0
        self.model = self._load_model()
        self.last_known_metrics = None
        
    def _load_model(self):
        if self.model_path.exists():
            logger.info("[LEARNING] Loading AI model from %s", self.model_path)
            return joblib.load(self.model_path)
        else:
            logger.info("[LEARNING] Model not found. Initializing baseline training...")
            return retrain_model(self.config)

    def detect_anomaly(self, metrics):
        """
        Multivariate anomaly detection using Isolation Forest.
        Aligns with FEATURE_COLUMNS from training data.
        """
        if metrics is None:
            return {"anomaly": False, "score": 0.0, "skip": True}

        # The 12 features must match the order in training data
        FEATURE_COLUMNS = [
            'load1_norm', 'load5_norm', 'load15_norm', 
            'mem_free_ratio', 'mem_available_ratio', 'mem_total_ratio', 
            'mem_cache_ratio', 'mem_buffered_ratio', 
            'swap_total_ratio', 'swap_free_ratio', 
            'fork_rate', 'intr_rate'
        ]
        
        # Extract features from metrics in the correct order
        current_vector = [float(metrics.get(col, 0.0)) for col in FEATURE_COLUMNS]
        current_data_dict = {col: val for col, val in zip(FEATURE_COLUMNS, current_vector)}
        
        self.last_known_metrics = current_data_dict
        
        # Convert the raw vector into a 2D DataFrame with headers
        # This prevents the "Feature names mismatch" error
        X = pd.DataFrame([current_vector], columns=FEATURE_COLUMNS)
        
        # Add to rolling buffer for Online Learning
        self.rolling_buffer.append(current_data_dict)
        if len(self.rolling_buffer) > self.buffer_size:
            self.rolling_buffer.pop(0)
            
        # Trigger retraining
        self.cycles_since_retrain += 1
        if self.cycles_since_retrain >= self.retrain_interval:
            logger.info("[LEARNING] Updating model with online learning buffer (%d cycles)...", self.cycles_since_retrain)
            buffer_df = pd.DataFrame(self.rolling_buffer)
            self.model = retrain_model(self.config, additional_data=buffer_df)
            self.cycles_since_retrain = 0
            
        # Predict using decision_function to get the score
        score = self.model.score_samples(X)[0]
        
        anomaly_threshold = self.ai_cfg.get('anomaly_threshold', -0.75)
        is_anomaly = score < anomaly_threshold
            
        if is_anomaly:
            logger.warning(f"[DETECTION] AI anomaly detected (score={score:.4f})")
        else:
            logger.info(f"[DETECTION] System healthy (score={score:.4f})")
            
        return {
            "anomaly": bool(is_anomaly),
            "score": float(score),
            "features": current_data_dict
        }
