with open('failure.py', 'r') as f:
    content = f.read()

# Fix the predict_proba issue
old = """        if model:
            prediction = model.predict(features)[0]
            probability = model.predict_proba(features)[0]
            will_fail = bool(prediction == 1)
            fail_prob = round(float(probability[1]) * 100, 2)"""

new = """        if model:
            prediction = model.predict(features)[0]
            # Handle both classifier and regressor
            if hasattr(model, 'predict_proba'):
                probability = model.predict_proba(features)[0]
                will_fail = bool(prediction == 1)
                fail_prob = round(float(probability[1]) * 100, 2)
            else:
                # For regressor, use prediction value as probability
                will_fail = prediction > 0.5
                fail_prob = round(float(prediction) * 100, 2)"""

content = content.replace(old, new)

with open('failure.py', 'w') as f:
    f.write(content)
print("✅ Fixed failure predict")
