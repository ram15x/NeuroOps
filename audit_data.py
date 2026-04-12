import pandas as pd
df = pd.read_csv('./training_data/metrics_20260409.csv')
print('Total Rows: ' + str(len(df)))
print('Unique Instances: ' + str(df['instance_id'].nunique()))
print('Date Range: ' + str(df['timestamp'].min()) + ' to ' + str(df['timestamp'].max()))
print(df['metric_name'].value_counts())
print(df['source'].value_counts())
cpu_df = df[df['metric_name'] == 'cpu']['value']
print('CPU Mean: ' + str(round(cpu_df.mean(), 2)) + '%')
print('CPU Max: ' + str(cpu_df.max()) + '%')
print('CPU Min: ' + str(cpu_df.min()) + '%')
