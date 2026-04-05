#!/usr/bin/env python
"""
Automated data conversion and model retraining
Run this every 2 days via Task Scheduler
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.database import SessionLocal, MetricHistory
import pandas as pd
import joblib
from datetime import datetime, timedelta
import xgboost as xgb

def convert_new_data():
    """Convert new data to ML format"""
    try:
        db = SessionLocal()
        
        # Get last 48 hours of data (since we run every 2 days)
        cutoff = datetime.utcnow() - timedelta(hours=48)
        records = db.query(MetricHistory).filter(
            MetricHistory.timestamp >= cutoff
        ).all()
        
        if len(records) == 0:
            db.close()
            return None
        
        print(f"Found {len(records)} new records")
        
        # Convert to DataFrame
        df = pd.DataFrame([{
            'instance_id': r.instance_id,
            'metric_name': r.metric_name,
            'value': r.value,
            'timestamp': r.timestamp
        } for r in records])
        
        # Pivot to ML format
        df['timestamp_rounded'] = df['timestamp'].dt.floor('min')
        df_pivot = df.pivot_table(
            index=['instance_id', 'timestamp_rounded'],
            columns='metric_name',
            values='value'
        ).reset_index()
        
        df_pivot.columns.name = None
        df_pivot = df_pivot.rename(columns={'timestamp_rounded': 'timestamp'})
        
        # Add calculated fields
        df_pivot['instance_age_days'] = (df_pivot['timestamp'] - df_pivot['timestamp'].min()).dt.days
        df_pivot['is_anomaly'] = (df_pivot['cpu'] > 80).astype(int) if 'cpu' in df_pivot else 0
        df_pivot['severity'] = df_pivot['cpu'].apply(
            lambda x: 'critical' if x > 95 else ('warning' if x > 80 else 'normal')
        ) if 'cpu' in df_pivot else 'normal'
        df_pivot['reboot_count'] = 0
        
        # Fill missing values
        numeric_cols = ['cpu', 'memory', 'disk']
        for col in numeric_cols:
            if col in df_pivot.columns:
                median_val = df_pivot[col].median()
                df_pivot[col] = df_pivot[col].fillna(median_val)
            else:
                df_pivot[col] = 0
        
        # Ensure all columns exist
        required_cols = ['instance_id', 'timestamp', 'cpu', 'memory', 'disk', 
                         'reboot_count', 'instance_age_days', 'is_anomaly', 'severity']
        for col in required_cols:
            if col not in df_pivot.columns:
                df_pivot[col] = 0 if col != 'timestamp' else datetime.utcnow()
        
        df_pivot = df_pivot[required_cols]
        
        # Save daily data
        os.makedirs('data/daily', exist_ok=True)
        daily_file = f'data/daily/ml_data_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
        df_pivot.to_csv(daily_file, index=False)
        
        db.close()
        return df_pivot
    except Exception as e:
        print(f"Error in convert_new_data: {e}")
        return None

def update_training_data():
    """Merge all daily data with existing training data"""
    try:
        combined_file = 'data/combined_training_data.csv'
        if os.path.exists(combined_file):
            combined = pd.read_csv(combined_file)
        else:
            combined = pd.DataFrame()
        
        # Load all daily files
        daily_files = []
        if os.path.exists('data/daily'):
            daily_files = [f for f in os.listdir('data/daily') if f.endswith('.csv')]
        
        for file in daily_files:
            new_data = pd.read_csv(f'data/daily/{file}')
            combined = pd.concat([combined, new_data], ignore_index=True)
        
        # Remove duplicates
        if len(combined) > 0:
            combined = combined.drop_duplicates(subset=['instance_id', 'timestamp'], keep='last')
            combined.to_csv(combined_file, index=False)
            print(f"Updated combined data: {len(combined)} records")
        else:
            print("No data to update")
        
        return combined
    except Exception as e:
        print(f"Error in update_training_data: {e}")
        return None

def retrain_model():
    """Retrain XGBoost model with latest data"""
    try:
        combined_file = 'data/combined_training_data.csv'
        if not os.path.exists(combined_file):
            print("No training data available")
            return
        
        df = pd.read_csv(combined_file)
        
        if len(df) < 100:
            print(f"Not enough data for retraining (need 100, have {len(df)})")
            return
        
        # Prepare features
        features = ['cpu', 'memory', 'disk', 'instance_age_days']
        X = df[features].fillna(df[features].median()).values
        y = df['is_anomaly'].values
        
        # Train model
        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
            use_label_encoder=False
        )
        
        model.fit(X, y)
        
        # Save model
        os.makedirs('ml_models/saved', exist_ok=True)
        joblib.dump(model, 'ml_models/saved/xgboost_production_model.pkl')
        print(f"Model retrained with {len(df)} records, {sum(y)} anomalies")
        
        # Save metadata
        metadata = {
            'last_trained': datetime.now().isoformat(),
            'records_used': len(df),
            'features': features,
            'anomaly_count': int(sum(y))
        }
        joblib.dump(metadata, 'ml_models/saved/model_metadata.pkl')
        
    except Exception as e:
        print(f"Error in retrain_model: {e}")

def run_pipeline():
    """Run full automation pipeline"""
    print(f"NeuroOps Auto Pipeline - {datetime.now()}")
    print("-" * 50)
    
    new_data = convert_new_data()
    if new_data is not None:
        print(f"Converted {len(new_data)} new records")
    
    update_training_data()
    retrain_model()
    
    print("-" * 50)
    print("Pipeline complete!")

if __name__ == "__main__":
    run_pipeline()
