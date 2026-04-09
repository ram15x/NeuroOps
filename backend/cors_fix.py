# Add this to main.py before app startup
# Ensure CORS allows WebSocket upgrade
import sys
with open('main.py', 'r') as f:
    content = f.read()

if 'allow_headers' in content and 'websocket' not in content:
    content = content.replace('allow_headers=["*"]', 'allow_headers=["*", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions"]')
    with open('main.py', 'w') as f:
        f.write(content)
        print("✅ CORS updated for WebSocket")
