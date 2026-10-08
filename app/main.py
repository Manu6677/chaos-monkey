from fastapi import FastAPI
import socket

app = FastAPI()


@app.get("/")
def home():
    return {
        "message": "Hello from FastAPI",
        "hostname": socket.gethostname(),
    }


@app.get("/healthz")
def health():
    return {
        "status": "ok"
    }