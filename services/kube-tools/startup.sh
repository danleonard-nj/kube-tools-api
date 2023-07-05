echo "Hello!  Starting up the server..."
uvicorn --log-level=error --host 0.0.0.0 --port=80 --workers 1 app:app