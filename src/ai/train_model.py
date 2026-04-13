import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from pathlib import Path
from utils.config_loader import load_config
from utils.logger import get_logger

logger = get_logger(__name__)

def preprocess_westermo(file_path):
    """
    Preprocess Westermo dataset to match our internal feature format.
    """
    df = pd.read_csv(file_path)
    
    # Map Westermo columns to our internal metrics
    # Westermo cpu-user and cpu-system are in 0.0-1.0 range usually, but let's check
    df['cpu_usage_percent'] = (df['cpu-user'] + df['cpu-system']) * 100
    df['memory_usage_percent'] = (1 - (df['sys-mem-available'] / df['sys-mem-total'])) * 100
    df['disk_usage_percent'] = df['disk-io-time'] * 100  # Proxy for disk activity
    
    # For network, since it's not in the dataset, we'll use 0 or synthetic values for baseline
    df['net_in_bytes'] = 0
    df['net_out_bytes'] = 0
    
    return df[['cpu_usage_percent', 'memory_usage_percent', 'disk_usage_percent', 'net_in_bytes', 'net_out_bytes']]

def train(config=None, additional_data=None):
    """
    Phase 1: Baseline training with Westermo dataset.
    Phase 2: Continuous training with rolling buffer data.
    """
    if config is None:
        config = load_config("config/config.yaml")
        
    ai_cfg = config.get('ai', {})
    westermo_path = ai_cfg.get('westermo_path', 'data/westermo/system-1.csv')
    model_path = ai_cfg.get('model_path', 'models/isolation_forest.pkl')
    
    # Load baseline
    logger.info(f"Loading baseline data from {westermo_path}")
    baseline_df = preprocess_westermo(westermo_path)
    
    # Combine with additional data (Online Learning)
    if additional_data is not None and not additional_data.empty:
        logger.info("Merging baseline data with online learning buffer")
        train_df = pd.concat([baseline_df, additional_data], ignore_index=True)
    else:
        train_df = baseline_df
        
    # Train Isolation Forest
    # multivariate anomaly detection
    model = IsolationForest(
        n_estimators=100,
        contamination='auto',
        random_state=42
    )
    
    features = ['cpu_usage_percent', 'memory_usage_percent', 'disk_usage_percent', 'net_in_bytes', 'net_out_bytes']
    model.fit(train_df[features])
    
    # Save model
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    logger.info(f"Model saved to {model_path}")
    
    return model

if __name__ == "__main__":
    train()
