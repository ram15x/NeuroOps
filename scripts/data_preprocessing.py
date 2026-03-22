import pandas as pd
import os

#inframidn
input_folder = "datasets/inframind"
output_file = "datasets/processed/metrics_clean.csv"
all_data = []
for file in os.listdir(input_folder):
    if file.endswith(".csv"):
        path = os.path.join(input_folder, file)
        df = pd.read_csv(path)
        # Fix column names
        if len(df.columns) == 2:
            df.columns = ["timestamp", "value"]
        # Add metric name
        df["metric"] = file.replace(".csv","")
        all_data.append(df)
combined = pd.concat(all_data)
combined.to_csv(output_file, index=False)
print("InfraMind metrics processed")

#opsGpt
log_file = "datasets/opsgpt/hdfs_logs.csv"
output_logs = "datasets/processed/logs_clean.csv"
logs = pd.read_csv(log_file)
logs = logs[["EventId","EventTemplate","Content"]]
logs.to_csv(output_logs,index=False)
print("Logs dataset processed")

#failurePredictiom
failure_file = "datasets/failure_prediction/train_FD001.txt"
output_failure = "datasets/processed/failure_clean.csv"
cols = ["unit","cycle"] + [f"sensor{i}" for i in range(1,25)]
failure = pd.read_csv(failure_file, sep=" ", header=None)
failure = failure.dropna(axis=1)
failure.columns = cols
failure.to_csv(output_failure,index=False)
print("Failure dataset processed")