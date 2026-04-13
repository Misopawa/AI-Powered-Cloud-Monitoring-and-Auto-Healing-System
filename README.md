AI-Based Cloud Server Monitoring & Auto-Healing System
🎓 Final Year Project | Bachelor in Network Computing
Author: Mohamad Syahmi

Project Scope: Intelligent Automation, Industry 4.0, and Real-time Infrastructure Reliability.

🚀 Project Overview
This project implements a hybrid cloud server monitoring system that bridges traditional threshold-based monitoring with AI-driven anomaly detection. By utilizing the Isolation Forest algorithm, the system identifies abnormal server behavior that static thresholds might miss, reducing downtime through automated recovery actions (Auto-Healing) without human intervention.

🧠 Hybrid Detection Logic
The system monitors four core components: CPU, Memory, Disk, and Network.

Threshold-Based Monitoring: Provides immediate, interpretable alerts for CPU, Memory, Disk, and Network when resource usage exceeds predefined limits.

AI-Based Anomaly Detection: Uses the Isolation Forest model (trained on a processed Westermo industrial dataset) to detect complex patterns in CPU, Memory, and Disk usage.

Network Monitoring: Handled exclusively via thresholds due to the bursty/cumulative nature of network packet data.

📂 Project Structure
Python Bash Code/
├── src/
│   ├── main.py                # Main execution loop
│   ├── monitoring/
│   │   ├── metrics_collector.py
│   │   └── threshold_monitor.py
│   ├── ai/
│   │   ├── train_model.py
│   │   └── anomaly_detector.py
│   ├── utils/
│   │   ├── config_loader.py
│   │   ├── csv_writer.py
│   │   ├── logger.py
│   │   └── westermo_preprocessor.py
│   └── recovery/
│       └── auto_healer.py
├── config/
│   └── config.yaml            # Thresholds, dataset paths, and log settings
├── data/
│   ├── raw/                   # Mock metrics and Westermo data
│   ├── processed/             # Cleaned datasets for training
│   └── metrics.csv            # Runtime logged metrics
├── models/
│   └── isolation_forest.pkl   # Saved AI model
├── logs/
│   └── system.log             # Event, alert, and recovery logs
└── README.md

🛠️ Workflow & Execution
1. Configuration: Define resource limits and file paths in config/config.yaml.

2. Preprocessing: Run the westermo_preprocessor.py to prepare the industrial dataset.

3. Training: Execute train_model.py to generate the isolation_forest.pkl model.

4. Monitoring: Launch main.py. The system will:

    Collect real-time metrics using psutil.

    Perform concurrent Threshold and AI checks.

    Log all data to metrics.csv.

    Trigger auto_healer.py if a breach or anomaly is detected.

🔧 Installation
# Clone the repository
git clone https://github.com/Misopawa/AI-Powered-Cloud-Monitoring-and-Auto-Healing-System.git

# Install required libraries
pip install psutil pandas scikit-learn pyyaml

Note: This system is designed as a foundation for intelligent fault detection in cloud and industrial environments, aligning with Industry 4.0 automation standards.