from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Load the .env file that contains your DATABASE_URL
load_dotenv()

app = FastAPI(title="Slate API")

@app.get("/")
def read_root():
    # Never return the connection string (or any part of it): it can contain the DB password.
    return {"message": "Backend is running", "database_configured": bool(os.getenv("DATABASE_URL"))}
