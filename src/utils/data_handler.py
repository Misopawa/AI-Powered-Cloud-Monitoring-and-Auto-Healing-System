import pandas as pd
import os
from utils.logger import setup_logger

_logger = setup_logger()

def save_metrics(metrics, file_path):
    if isinstance(metrics, dict):
        metrics = [metrics]
    df_new = pd.DataFrame(metrics)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if os.path.isfile(file_path):
        df_new.to_csv(file_path, mode='a', header=False, index=False)
    else:
        df_new.to_csv(file_path, mode='w', header=True, index=False)

    try:
        df_existing = pd.read_csv(file_path)
        if len(df_existing) >= 1000:
            df_existing = df_existing.iloc[500:]
            df_existing.to_csv(file_path, mode='w', header=True, index=False)
    except Exception:
        pass

def save_metrics_to_csv(metrics, config=None):
    path = None
    if isinstance(config, dict):
        path = config.get("processed_data") or config.get("raw_data")
    if not path:
        path = os.path.join("data", "metrics.csv")
    save_metrics(metrics, path)
    _logger.info(f"Metrics written to {path}")

def load_dataset(file_path):
    return pd.read_csv(file_path)
