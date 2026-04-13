AI-Based Cloud Server Monitoring & Auto-Healing System

This project implements a hybrid cloud server monitoring system that combines traditional threshold-based monitoring with AI-based anomaly detection using the Isolation Forest algorithm. The objective of the system is to detect abnormal server behavior, reduce downtime, and automatically trigger recovery actions without human intervention. The system is designed to align with Industry 4.0 principles, focusing on intelligent automation, reliability, and real-time monitoring of server infrastructure.

The system monitors four main components of a server: CPU, memory, disk, and network. CPU, memory, and disk resources are monitored using both threshold-based rules and AI-based anomaly detection. Threshold-based monitoring provides fast and interpretable alerts when resource usage exceeds predefined limits, while the Isolation Forest model detects unusual behavior patterns that cannot be easily identified using static thresholds alone. Network monitoring is handled using threshold-based detection only, as network metrics such as packet drops and errors are cumulative and highly bursty, making them less suitable for Isolation Forest without advanced preprocessing.

The AI anomaly detection model is trained using a processed version of the Westermo industrial dataset. The dataset is first preprocessed to extract relevant numerical features and stored in CSV format before being used to train the Isolation Forest model. Once trained, the model is saved and loaded during runtime to detect anomalies in real-time system metrics.

The system follows a modular project structure to ensure scalability and maintainability. System metrics are collected using the psutil library, stored in CSV format for logging and analysis, and evaluated against predefined thresholds. When an anomaly or threshold breach is detected, the system triggers an auto-healing mechanism that simulates recovery actions such as service restarts or system stabilization. All system events, alerts, and recovery actions are logged for monitoring and evaluation purposes.

The configuration of the system is managed through a YAML configuration file. This file defines CPU, memory, disk, and network thresholds, as well as paths for datasets, models, and log files. Network thresholds are defined using reasonable average values that represent acceptable server conditions, allowing warnings to be triggered only when network behavior deviates significantly from normal operation.

To run the system, the Westermo dataset is first preprocessed, followed by training the Isolation Forest model. After training is complete, the main monitoring program is executed. During execution, the system continuously collects metrics, logs data, performs threshold checks, applies AI-based anomaly detection, and triggers auto-healing when required.

This project demonstrates the integration of artificial intelligence into traditional server monitoring systems and highlights how AI can enhance fault detection and recovery in cloud and industrial environments. It is suitable for academic evaluation, Final Year Project submission, and as a foundation for future enhancements such as dashboard visualization, distributed monitoring, and intelligent recovery optimization.

Python Bash Code/
│
├── src/
│ ├── main.py # Main execution loop
│ │
│ ├── monitoring/
│ │ ├── metrics_collector.py
│ │ └── threshold_monitor.py
│ │
│ ├── ai/
│ │ ├── train_model.py
│ │ └── anomaly_detector.py
│ │
│ ├── utils/
│ │ ├── config_loader.py
│ │ ├── csv_writer.py
│ │ ├── logger.py
│ │ └── westermo_preprocessor.py
│ │
│ └── recovery/
│ └── auto_healer.py
│
├── config/
│ └── config.yaml
│
├── data/
│ ├── raw/
│ │ └── mock_metrics.csv
│ ├── processed/
│ │ └── cleaned_metrics.csv
│ └── metrics.csv
│
├── models/
│ └── isolation_forest.pkl
│
├── logs/
│ └── system.log
│
└── README.md

Author: Mohamad Syahmi
Bachelor Degree in Network Computing
Final Year Project – AI-Powered Cloud Monitoring and Auto-Healing System