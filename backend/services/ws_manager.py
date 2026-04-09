from fastapi import WebSocket
from typing import List
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
       # await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected! Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected! Total: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(data))
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.remove(conn)

    async def send_personal(self, data: dict, websocket: WebSocket):
        await websocket.send_text(json.dumps(data))

manager = ConnectionManager()
