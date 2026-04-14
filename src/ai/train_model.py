import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from pathlib import Path
from utils.config_loader import load_config
from utils.logger import get_logger

logger = get_logger(__name__)

def preprocess_westermo(file_path):
    """
    Preprocess Westermo dataset to match the 12 required features exactly.
    Includes Unit Normalization Layer (converting memory from Bytes to GB).
    """
    df = pd.read_csv(file_path)
    
    # Required Features List (Westermo headers)
    features = [
        'load-1m', 'load-5m', 'load-15m', 
        'sys-mem-swap-total', 'sys-mem-swap-free', 'sys-mem-free', 
        'sys-mem-cache', 'sys-mem-buffered', 'sys-mem-available', 
        'sys-mem-total', 'sys-fork-rate', 'sys-interrupt-rate'
    ]
    
    # Unit Normalization Layer: Convert memory fields from Bytes to GB
    mem_fields = [
        'sys-mem-swap-total', 'sys-mem-swap-free', 'sys-mem-free', 
        'sys-mem-cache', 'sys-mem-buffered', 'sys-mem-available', 
        'sys-mem-total'
    ]
    
    gb_divider = 1024 ** 3
    for col in mem_fields:
        if col in df.columns:
            df[col] = df[col] / gb_divider
    
    # Return only the required features
    return df[features]

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
    logger.info(f"[LEARNING] Loading baseline data from {westermo_path}")
    baseline_df = preprocess_westermo(westermo_path)
    
    # Combine with additional data (Online Learning)
    if additional_data is not None and not additional_data.empty:
        logger.info("[LEARNING] Merging baseline data with online learning buffer")
        train_df = pd.concat([baseline_df, additional_data], ignore_index=True)
    else:
        train_df = baseline_df
        
    # Train Isolation Forest
    # multivariate anomaly detection
    model = IsolationForest(
        n_estimators=100,
        contamination=0.01,  # 1% contamination for clean lab environment
        random_state=42
    )
    
    features = [
        'load-1m', 'load-5m', 'load-15m', 
        'sys-mem-swap-total', 'sys-mem-swap-free', 'sys-mem-free', 
        'sys-mem-cache', 'sys-mem-buffered', 'sys-mem-available', 
        'sys-mem-total', 'sys-fork-rate', 'sys-interrupt-rate'
    ]
    model.fit(train_df[features])
    
    # Save model
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    logger.info(f"[LEARNING] Model saved to {model_path}")
    
    return model

if __name__ == "__main__":
    train()
