# Student Attendance Automation – Backend API

This is a separate FastAPI backend for the Student Attendance Automation Streamlit project.

## Run locally
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open:
- API status: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health
- Interactive API docs: http://127.0.0.1:8000/docs

## Endpoints
- `GET /` – API information
- `GET /health` – health check
- `POST /api/attendance/analyze` – upload two CSV files and receive overall/student/shortage/validation results
- `POST /api/attendance/shortage` – upload two CSV files and receive only shortage students

### Required CSV columns
Students: `student_id, student_name, department, semester, section`

Attendance: `student_id, attendance_date, subject, attendance_status`

Optional query parameters:
- `threshold`: 0–100; default 75
- `od_mode`: `attended`, `not_attended`, or `exclude`; default `attended`

## Deploy on Render
1. Create a GitHub repository and upload `main.py` and `requirements.txt` to its root.
2. In Render, create a **New Web Service** and connect that repository.
3. Set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Deploy. Render will provide the real public URL. Add `/docs` to that URL for API documentation.

This backend is independently deployable. Your existing Streamlit frontend does not automatically call it yet; connecting the frontend requires updating its Python code to send the uploaded CSV data to this API.
