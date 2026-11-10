from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import re
from datetime import datetime

app = FastAPI(
    title="Student Attendance Automation API",
    description="REST API for cleaning, validating and analysing student attendance CSV files.",
    version="1.0.0",
)

# Allows a browser-based frontend to call this API. Restrict origins before production use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STUDENT_COLS = ["student_id", "student_name", "department", "semester", "section"]
ATT_COLS = ["student_id", "attendance_date", "subject", "attendance_status"]
STATUS_MAP = {
    "present": "Present", "p": "Present", "pr": "Present", "yes": "Present",
    "y": "Present", "1": "Present", "attended": "Present",
    "absent": "Absent", "a": "Absent", "ab": "Absent", "no": "Absent",
    "n": "Absent", "0": "Absent",
    "od": "OD", "o.d": "OD", "o.d.": "OD", "on duty": "OD",
    "on-duty": "OD", "onduty": "OD",
    "holiday": "Holiday", "h": "Holiday", "hol": "Holiday",
}
ALIASES = {
    "studentid": "student_id", "id": "student_id", "roll_no": "student_id",
    "rollno": "student_id", "reg_no": "student_id",
    "name": "student_name", "studentname": "student_name",
    "dept": "department", "sem": "semester", "sec": "section",
    "date": "attendance_date", "attendancedate": "attendance_date",
    "status": "attendance_status", "attendancestatus": "attendance_status",
    "subject_name": "subject", "course": "subject",
}
OD_MODES = {
    "attended": "Count OD as attended",
    "not_attended": "Count OD as not attended",
    "exclude": "Exclude OD from eligible sessions",
}

def blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip().lower() in {
        "", "nan", "none", "null", "nat", "n/a"
    }

def clean_id(v):
    if blank(v):
        return None
    s = re.sub(r"\.0+$", "", str(v).strip())
    s = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    return s or None

def norm_cols(df):
    df = df.copy()
    cols = []
    for col in df.columns:
        name = re.sub(r"[\s\-]+", "_", str(col).strip().lower())
        cols.append(ALIASES.get(name, name))
    df.columns = cols
    return df

def parse_date(v):
    if blank(v):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).normalize()
    s = str(v).strip()
    formats = [
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y",
        "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%b %d, %Y",
        "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            pass
    return pd.NaT

def normalize_status(v):
    if blank(v):
        return None
    key = re.sub(r"\s+", " ", str(v).strip().lower())
    return STATUS_MAP.get(key)

def read_csv_upload(upload):
    try:
        raw = upload.file.read()
        return pd.read_csv(io.BytesIO(raw), dtype=str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read {upload.filename}: {exc}")

def analyze_frames(students_raw, attendance_raw, threshold, od_mode):
    students = norm_cols(students_raw)
    attendance = norm_cols(attendance_raw)

    missing_s = [c for c in STUDENT_COLS if c not in students.columns]
    missing_a = [c for c in ATT_COLS if c not in attendance.columns]
    if missing_s or missing_a:
        raise HTTPException(status_code=422, detail={
            "missing_student_columns": missing_s,
            "missing_attendance_columns": missing_a,
            "required_student_columns": STUDENT_COLS,
            "required_attendance_columns": ATT_COLS,
        })

    students = students[STUDENT_COLS].copy()
    students["student_id"] = students["student_id"].map(clean_id)
    students = students[students["student_id"].notna()].copy()
    for c in ["student_name", "department", "semester", "section"]:
        students[c] = students[c].map(lambda x: "Unknown" if blank(x) else re.sub(r"\s+", " ", str(x).strip()))
    students["department"] = students["department"].str.upper()
    students["section"] = students["section"].str.upper()
    students = students.drop_duplicates("student_id", keep="first").reset_index(drop=True)
    valid_ids = set(students["student_id"])

    a = attendance[ATT_COLS].copy()
    a["student_id"] = a["student_id"].map(clean_id)
    a["attendance_date"] = a["attendance_date"].map(parse_date)
    a["attendance_status"] = a["attendance_status"].map(normalize_status)
    a["subject"] = a["subject"].map(lambda x: "Unspecified" if blank(x) else re.sub(r"\s+", " ", str(x).strip()))

    invalid_mask = (
        a["student_id"].isna()
        | a["attendance_date"].isna()
        | a["attendance_status"].isna()
        | ~a["student_id"].isin(valid_ids)
    )
    issues = []
    for idx, row in a[invalid_mask].iterrows():
        if blank(row["student_id"]):
            issue = "Missing Student ID"
        elif pd.isna(row["attendance_date"]):
            issue = "Invalid or Missing Date"
        elif blank(row["attendance_status"]):
            issue = "Unknown or Missing Status"
        else:
            issue = "Unknown Student ID"
        issues.append({"row": int(idx) + 2, "student_id": row["student_id"], "issue": issue})
    a = a[~invalid_mask].copy()

    duplicate_mask = a.duplicated(["student_id", "attendance_date", "subject"], keep="first")
    for idx, row in a[duplicate_mask].iterrows():
        issues.append({"row": int(idx) + 2, "student_id": row["student_id"], "issue": "Duplicate Record"})
    a = a[~duplicate_mask].copy()

    status = a["attendance_status"]
    if od_mode == "attended":
        a["eligible"] = status.isin(["Present", "Absent", "OD"]).astype(int)
        a["attended"] = status.isin(["Present", "OD"]).astype(int)
    elif od_mode == "not_attended":
        a["eligible"] = status.isin(["Present", "Absent", "OD"]).astype(int)
        a["attended"] = status.eq("Present").astype(int)
    else:
        a["eligible"] = status.isin(["Present", "Absent"]).astype(int)
        a["attended"] = status.eq("Present").astype(int)

    counts = a.groupby("student_id").agg(
        eligible_sessions=("eligible", "sum"),
        attended_sessions=("attended", "sum"),
        od_count=("attendance_status", lambda x: int((x == "OD").sum())),
        holiday_count=("attendance_status", lambda x: int((x == "Holiday").sum())),
    ).reset_index()

    summary = students.merge(counts, on="student_id", how="left")
    for col in ["eligible_sessions", "attended_sessions", "od_count", "holiday_count"]:
        summary[col] = summary[col].fillna(0).astype(int)
    summary["absent_sessions"] = summary["eligible_sessions"] - summary["attended_sessions"]
    summary["attendance_pct"] = summary.apply(
        lambda r: None if r["eligible_sessions"] == 0
        else round(r["attended_sessions"] / r["eligible_sessions"] * 100, 2), axis=1
    )
    def status_for(row):
        if row["eligible_sessions"] == 0:
            return "No Data"
        return "Shortage" if row["attended_sessions"] * 100 < threshold * row["eligible_sessions"] - 1e-9 else "Sufficient"
    summary["status"] = summary.apply(status_for, axis=1)
    summary["shortage_pct"] = summary.apply(
        lambda r: round(threshold - r["attendance_pct"], 2)
        if r["status"] == "Shortage" else 0.0, axis=1
    )

    shortage = summary[summary["status"] == "Shortage"].copy()
    overall_eligible = int(summary["eligible_sessions"].sum())
    overall_attended = int(summary["attended_sessions"].sum())
    overall = {
        "total_students": int(len(summary)),
        "total_records": int(len(a)),
        "eligible_sessions": overall_eligible,
        "attended_sessions": overall_attended,
        "attendance_pct": round(overall_attended / overall_eligible * 100, 2) if overall_eligible else None,
        "shortage_students": int((summary["status"] == "Shortage").sum()),
        "sufficient_students": int((summary["status"] == "Sufficient").sum()),
        "no_data_students": int((summary["status"] == "No Data").sum()),
        "rejected_records": int(invalid_mask.sum()),
        "duplicate_records": int(duplicate_mask.sum()),
    }
    return {
        "ok": True,
        "threshold": threshold,
        "od_mode": OD_MODES[od_mode],
        "overall": overall,
        "student_summary": summary.where(pd.notna(summary), None).to_dict(orient="records"),
        "shortage": shortage.where(pd.notna(shortage), None).to_dict(orient="records"),
        "issues": issues,
    }

@app.get("/")
def root():
    return {"message": "Student Attendance Automation API", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/api/attendance/analyze")
async def analyze_attendance(
    students_file: UploadFile = File(...),
    attendance_file: UploadFile = File(...),
    threshold: float = Query(75.0, ge=0, le=100),
    od_mode: str = Query("attended", pattern="^(attended|not_attended|exclude)$"),
):
    students = read_csv_upload(students_file)
    attendance = read_csv_upload(attendance_file)
    return analyze_frames(students, attendance, threshold, od_mode)

@app.post("/api/attendance/shortage")
async def get_shortage(
    students_file: UploadFile = File(...),
    attendance_file: UploadFile = File(...),
    threshold: float = Query(75.0, ge=0, le=100),
    od_mode: str = Query("attended", pattern="^(attended|not_attended|exclude)$"),
):
    result = analyze_frames(
        read_csv_upload(students_file),
        read_csv_upload(attendance_file),
        threshold,
        od_mode,
    )
    return {"threshold": threshold, "shortage_students": result["shortage"], "count": len(result["shortage"])}

