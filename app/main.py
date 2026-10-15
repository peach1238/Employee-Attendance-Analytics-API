"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
import json
from bson import json_util
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel
from pymongo import MongoClient, ReturnDocument

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def create_indexes():
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="idx_employees_emp_code"
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="idx_attendance_emp_code_date"
    )

    db.attendance_logs.create_index(
        [("date", -1)],
        name="idx_attendance_date"
    )



# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = page * page_size
    total = db.employees.count_documents({})
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    ts =  ( datetime.fromtimestamp(body.punched_at / 1000, tz=IST) if body.punched_at else datetime.now()
    )
    d = ts.date().isoformat()

    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")

    ts = (
        datetime.fromtimestamp(body.punched_at / 1000, tz=IST)
        if body.punched_at is not None
        else datetime.now(IST)
    ).replace(microsecond=0)

    ts_utc = ts.astimezone(timezone.utc).replace(tzinfo=None)

    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$ne": None},
            "punch_out": None,
        },
        sort=[("punch_in", -1)],
    )

    if not record:
        raise HTTPException(404, "no punch-in found")

    if record.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")

    punch_in = record["punch_in"].replace(tzinfo=IST)
    elapsed = (ts - punch_in).total_seconds()


    if elapsed <= 0 or elapsed > 24 * 60 * 60:
        raise HTTPException(422, "invalid punch-out time")

    work_hours = float(
        (Decimal(str(elapsed)) / Decimal("3600")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )

    shift_start = datetime.strptime(emp["shift_start"], "%H:%M").time()
    shift_end = datetime.strptime(emp["shift_end"], "%H:%M").time()
    shift_date = datetime.fromisoformat(record["date"]).date()

    if shift_end <= shift_start:
        shift_date += timedelta(days=1)

    shift_end_dt = datetime.combine(
        shift_date, shift_end, tzinfo=IST
    )
    overtime_elapsed = (
        ts - shift_end_dt
    ).total_seconds()

    overtime_minutes = (
        int(overtime_elapsed // 60)
        if overtime_elapsed >= 30 * 60
        else 0
    )

    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts_utc,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": work_hours < 4.50,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(409, "already punched out")

    updated.pop("_id", None)
    updated["punch_in"] = int(punch_in.timestamp() * 1000)
    updated["punch_out"] = int(ts.timestamp() * 1000)
    return updated

@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeIn):
    from datetime import date as date_type

    try:
        date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")

    if not body.reason.strip() or len(body.reason) < 5 or len(body.reason) > 200:
        raise HTTPException(422, "reason must be 5-200 characters")

    if not body.regularized_by.strip() or len(body.regularized_by) > 50:
        raise HTTPException(422, "regularized_by must be 1-50 characters")

    allowed_statuses = {"PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"}
    if body.status is not None and body.status not in allowed_statuses:
        raise HTTPException(422, "Invalid status")

    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")

    record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not record:
        raise HTTPException(404, "Attendance record not found")

    changes_requested = body.model_dump(exclude_unset=True)
    changes_requested.pop("reason", None)
    changes_requested.pop("regularized_by", None)

    if not changes_requested:
        raise HTTPException(422, "No attendance fields supplied")

    new_status = changes_requested.get("status", record["status"])

    if new_status in {"ABSENT", "LEAVE"}:
        if "punch_in" in changes_requested or "punch_out" in changes_requested:
            raise HTTPException(422, "ABSENT/LEAVE cannot have punch times")
        new_in = None
        new_out = None
    else:
        new_in = (
            datetime.fromtimestamp(changes_requested["punch_in"] / 1000, timezone.utc)
            if "punch_in" in changes_requested
            else record.get("punch_in")
        )
        new_out = (
            datetime.fromtimestamp(changes_requested["punch_out"] / 1000, timezone.utc)
            if "punch_out" in changes_requested
            else record.get("punch_out")
        )

        if new_in is None:
            raise HTTPException(422, "Presence status requires punch_in")

        attendance_day = datetime.fromtimestamp(
            new_in.timestamp(), IST
        ).date().isoformat()

        if attendance_day != date:
            raise HTTPException(422, "punch_in must be on the attendance date")

        if new_out is not None:
            if new_out <= new_in:
                raise HTTPException(422, "punch_out must be after punch_in")
            if (new_out - new_in).total_seconds() > 24 * 3600:
                raise HTTPException(422, "Punch duration cannot exceed 24 hours")

    if new_status in {"ABSENT", "LEAVE"}:
        new_in = None
        new_out = None
        work_hours = None
        late_minutes = 0
        overtime_minutes = 0
        half_day = False
    else:
        # PyMongo returns naive UTC datetimes; convert them to aware UTC.
        pin = new_in.replace(tzinfo=timezone.utc) if new_in.tzinfo is None else new_in
        pout = new_out.replace(tzinfo=timezone.utc) if new_out and new_out.tzinfo is None else new_out

        local_pin = pin.astimezone(IST)
        local_pout = pout.astimezone(IST) if pout else None

        work_hours = compute_work_hours(pin, pout) if pout else None
        late_minutes = compute_late_minutes(local_pin, emp["shift_start"])

        if local_pout:
            overtime_minutes = compute_overtime(local_pout, emp["shift_end"], date)
            half_day = work_hours < 4.5
        else:
            overtime_minutes = 0
            half_day = False

    proposed = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    history_changes = {}
    for key, new_value in proposed.items():
        old_value = record.get(key)
        if old_value != new_value:
            history_changes[key] = {"from": old_value, "to": new_value}

    if not history_changes:
        raise HTTPException(422, "Request does not change the attendance record")

    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": history_changes,
    }

    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": record["_id"],
            "history": record.get("history", []),
        },
        {
            "$set": proposed,
            "$push": {"history": history_entry},
        },
        return_document=__import__("pymongo").ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(409, "Record changed concurrently; retry the request")

    def epoch_ms(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)

    updated.pop("_id", None)
    updated["punch_in"] = epoch_ms(updated.get("punch_in"))
    updated["punch_out"] = epoch_ms(updated.get("punch_out"))

    for entry in updated.get("history", []):
        entry["at"] = epoch_ms(entry["at"])
        for field in ("punch_in", "punch_out"):
            if field in entry.get("changes", {}):
                pair = entry["changes"][field]
                pair["from"] = epoch_ms(pair.get("from"))
                pair["to"] = epoch_ms(pair.get("to"))

    return updated

def valid_date(value):
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    raise ValueError("Invalid date format")

def weekday_count(start, end):
    count = 0
    current = start.date() if isinstance(start, datetime) else start
    last = end.date() if isinstance(end, datetime) else end

    while current < last:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)

    return count

def presence_expr():
    return {
        "$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]
    }


def monthly_pipeline(emp_code, start_s, end_s, joined_on):
    return [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": start_s,
                    "$lte": end_s
                }
            }
        },
        {
            "$set": {
                "_weekday": {
                    "$dayOfWeek": {
                        "$dateFromString": {
                            "dateString": "$date"
                        }
                    }
                },
                "_present": presence_expr(),
                "_late": {
                    "$gt": [
                        {"$ifNull": ["$late_minutes", 0]},
                        0
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_present",
                                    {"$gte": ["$_weekday", 2]},
                                    {"$lte": ["$_weekday", 6]}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$ifNull": ["$half_day", False]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": ["$_late", 1, 0]
                    }
                },
                "total_late_minutes": {
                    "$sum": {
                        "$ifNull": ["$late_minutes", 0]
                    }
                },
                "total_overtime_minutes": {
                    "$sum": {
                        "$ifNull": ["$overtime_minutes", 0]
                    }
                }
            }
        }
    ]

def round_half_up(value, places=2):
    quantum = Decimal("1").scaleb(-places)
    return float(
        Decimal(str(value)).quantize(
            quantum,
            rounding=ROUND_HALF_UP
        )
    )

def month_bounds(month: str):
    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    if start.month == 12:
        end = start.replace(
            year=start.year + 1,
            month=1
        )
    else:
        end = start.replace(month=start.month + 1)

    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    return start_s, end_s, start, end



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    start_s, end_s, start, end = month_bounds(month)

    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")

    work_start = max(start, valid_date(emp["joined_on"]))
    working_days = weekday_count(work_start, end)

    result = list(
        db.attendance_logs.aggregate(
            monthly_pipeline(
                emp_code,
                start_s,
                end_s,
                emp["joined_on"]
            )
        )
    )

    stats = result[0] if result else {}

    present = round_half_up(stats.get("present_days", 0), 2)

    pct = (
        round_half_up(present / working_days * 100, 4)
        if working_days
        else None
    )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get(
            "total_overtime_minutes", 0
        ),
        "attendance_pct": pct
    }

@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: Optional[str] = None,
):
    # Validate month and get the date range.
    start_s, end_s, start, end = month_bounds(month)

    # Include employees who joined on or before the last day
    # of the requested month.
    employee_match = {
        "joined_on": {"$lte": (end - timedelta(days=1)).strftime("%Y-%m-%d")}
    }

    # Optional exact department filter.
    if department:
        employee_match["department"] = department

    pipeline = [
        {
            "$match": employee_match
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$employee_code"]},
                                    {"$gte": ["$date", start_s]},
                                    {"$lt": ["$date", end_s]},
                                ]
                            }
                        }
                    }
                ],
                "as": "logs",
            }
        },
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
            "$addFields": {
                "log_date": {
                    "$cond": [
                        {"$ne": ["$logs.date", None]},
                        {
                            "$dateFromString": {
                                "dateString": "$logs.date",
                                "format": "%Y-%m-%d",
                            }
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$addFields": {
                "is_weekday": {
                    "$and": [
                        {"$ne": ["$log_date", None]},
                        {"$gte": [{"$dayOfWeek": "$log_date"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$log_date"}, 6]},
                    ]
                },
                "is_present_status": {
                    "$in": [
                        "$logs.status",
                        ["PRESENT", "WFH", "ON_DUTY"],
                    ]
                },
                "late_value": {
                    "$ifNull": ["$logs.late_minutes", 0]
                },
                "overtime_value": {
                    "$ifNull": ["$logs.overtime_minutes", 0]
                },
            }
        },
        {
            "$group": {
                "_id": "$department",

                # Each employee counts once, even if they have
                # multiple attendance records.
                "employee_codes": {"$addToSet": "$emp_code"},

                # Present days count only on weekdays.
                # A half day contributes 0.5.
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_present_status",
                                    "$is_weekday",
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1.0,
                                ]
                            },
                            0,
                        ]
                    }
                },

                # Average work hours across qualifying attendance
                # records, not across employee averages.
                "work_hours_total": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_present_status",
                                    {"$ne": ["$logs.work_hours", None]},
                                ]
                            },
                            "$logs.work_hours",
                            0,
                        ]
                    }
                },
                "work_hours_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_present_status",
                                    {"$ne": ["$logs.work_hours", None]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },

                # Count records with positive late minutes.
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_value", 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": "$late_value"
                },

                # Count leave and on-duty records.
                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": {"$size": "$employee_codes"},
                "present_days": 1,
                "avg_work_hours": {
                    "$cond": [
                        {"$gt": ["$work_hours_count", 0]},
                        {
                            "$divide": [
                                "$work_hours_total",
                                "$work_hours_count",
                            ]
                        },
                        None,
                    ]
                },
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },
        {
            "$sort": {"department": 1}
        },
    ]

    results = list(db.employees.aggregate(pipeline))

    # Apply two-decimal, half-up rounding to the average work hours.
    for item in results:
        avg = item["avg_work_hours"]

        if avg is not None:
            item["avg_work_hours"] = float(
                Decimal(str(avg)).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            )

    return {
        "month": month,
        "items": results,
    }

@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None,
):
    # Validate month and get its date boundaries
    start_s, end_s, start, end = month_bounds(month)

    # Match attendance records for the selected month
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": start_s,
                    "$lt": end_s,
                }
            }
        },
        {
            "$addFields": {
                "late_value": {
                    "$ifNull": ["$late_minutes", 0]
                }
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": "$late_value"
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_value", 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        # Only employees with positive total late minutes
        {
            "$match": {
                "total_late_minutes": {"$gt": 0}
            }
        },
        # Get employee name and department
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    # Apply department filter before calculating ranks
    if department:
        pipeline.append(
            {
                "$match": {
                    "employee.department": department
                }
            }
        )

    # Calculate competition ranks.
    # Employees with equal late minutes receive the same rank.
    pipeline.extend(
        [
            {
                "$setWindowFields": {
                    "sortBy": {
                        "total_late_minutes": -1
                    },
                    "output": {
                        "rank": {"$rank": {}}
                    },
                }
            },
            # Apply limit AFTER ranking so ties are preserved
            {
                "$match": {
                    "rank": {"$lte": limit}
                }
            },
            # Sort ties by employee code
            {
                "$sort": {
                    "total_late_minutes": -1,
                    "_id": 1,
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "rank": 1,
                    "emp_code": "$_id",
                    "name": "$employee.name",
                    "department": "$employee.department",
                    "total_late_minutes": 1,
                    "late_count": 1,
                }
            },
        ]
    )

    # Run the MongoDB aggregation
    results = list(db.attendance_logs.aggregate(pipeline))

    return {
    "month": month,
    "items": results,
}

@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
):
    # Validate the date format
    try:
        start_date = datetime.strptime(
            from_, "%Y-%m-%d"
        ).date()

        end_date = datetime.strptime(
            to, "%Y-%m-%d"
        ).date()

        # Reject dates that are not in YYYY-MM-DD format
        if (
            start_date.strftime("%Y-%m-%d") != from_
            or end_date.strftime("%Y-%m-%d") != to
        ):
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD format",
        )

    # Validate the date range
    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'",
        )

    if (end_date - start_date).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days",
        )

    # Check whether the department exists
    if not db.employees.find_one(
        {"department": department},
        {"_id": 1},
    ):
        raise HTTPException(
            status_code=404,
            detail="Department not found",
        )

    # Prepare the date boundaries for MongoDB
    start_dt = datetime.combine(
        start_date,
        time.min,
        timezone.utc,
    )

    end_dt = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        timezone.utc,
    )

    # Create one row for every calendar day
    pipeline = [
        {
            "$match": {
                "department": department,
            }
        },
        {"$limit": 1},
        {
            "$project": {
                "_id": 0,
                "seed": {"$literal": start_dt},
            }
        },
        {
            "$set": {
                "_id": "$seed",
            }
        },
        {
            "$densify": {
                "field": "_id",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_dt, end_dt],
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateToString": {
                        "date": "$_id",
                        "format": "%Y-%m-%d",
                    }
                },
                "is_working_day": {
                    "$and": [
                        {
                            "$gte": [
                                {"$dayOfWeek": "$_id"},
                                2,
                            ]
                        },
                        {
                            "$lte": [
                                {"$dayOfWeek": "$_id"},
                                6,
                            ]
                        },
                    ]
                },
            }
        },
        # Count employees who have joined by each date
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                        }
                    },
                    {
                        "$match": {
                            "$expr": {
                                "$lte": [
                                    "$joined_on",
                                    "$$day",
                                ]
                            }
                        }
                    },
                    {"$count": "count"},
                ],
                "as": "headcount_data",
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$headcount_data.count",
                                0,
                            ]
                        },
                        0,
                    ]
                }
            }
        },
        # Find attendance records for this department and day
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "day": "$date",
                    "dept": department,
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": [
                                    "$date",
                                    "$$day",
                                ]
                            }
                        }
                    },
                    {
                        "$lookup": {
                            "from": "employees",
                            "let": {
                                "code": "$emp_code",
                                "dept": "$$dept",
                            },
                            "pipeline": [
                                {
                                    "$match": {
                                        "$expr": {
                                            "$and": [
                                                {
                                                    "$eq": [
                                                        "$emp_code",
                                                        "$$code",
                                                    ]
                                                },
                                                {
                                                    "$eq": [
                                                        "$department",
                                                        "$$dept",
                                                    ]
                                                },
                                            ]
                                        }
                                    }
                                },
                                {"$project": {"_id": 1}},
                            ],
                            "as": "employee_match",
                        }
                    },
                    {
                        "$match": {
                            "employee_match.0": {
                                "$exists": True,
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                [
                                                    "PRESENT",
                                                    "WFH",
                                                    "ON_DUTY",
                                                ],
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {
                                                    "$eq": [
                                                        {
                                                            "$ifNull": [
                                                                "$half_day",
                                                                False,
                                                            ]
                                                        },
                                                        True,
                                                    ]
                                                },
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {
                                                    "$ifNull": [
                                                        "$late_minutes",
                                                        0,
                                                    ]
                                                },
                                                0,
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "attendance_data",
            }
        },
        {
            "$set": {
                "present_count": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$attendance_data.present_count",
                                0,
                            ]
                        },
                        0,
                    ]
                },
                "late_count": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$attendance_data.late_count",
                                0,
                            ]
                        },
                        0,
                    ]
                },
            }
        },
        # Calculate attendance rate, rounded to 4 decimals
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {
                                                        "$divide": [
                                                            "$present_count",
                                                            "$headcount",
                                                        ]
                                                    },
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        # Average the current day and up to six previous days
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, 0],
                        },
                    }
                },
            }
        },
        # Round the moving average to 4 decimals
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": {
                    "$cond": [
                        {
                            "$ne": [
                                "$moving_avg_7d",
                                None,
                            ]
                        },
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    "$moving_avg_7d",
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                },
            }
        },
        {"$sort": {"date": 1}},
    ]

    # Execute the aggregation
    items = list(db.employees.aggregate(pipeline))

    return {
        "department": department,
        "items": items,
    }

@app.get("/admin/explain/{endpoint}")
def admin_explain(
    endpoint: str = Path(
        ...,
        pattern="^(attendance_list|employee_monthly|department_summary|late_leaderboard|department_trend)$"
    ),
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Explain MongoDB query execution plans for supported endpoints.
    """

    if endpoint == "attendance_list":
        collection = db.attendance_logs

        filters = {}

        if emp_code:
            filters["emp_code"] = emp_code

        if status:
            filters["status"] = status

        if date_from or date_to:
            filters["date"] = {}

            if date_from:
                filters["date"]["$gte"] = date_from

            if date_to:
                filters["date"]["$lte"] = date_to

        query = {
            "find": collection.name,
            "filter": filters,
            "sort": {"date": -1},
            "skip": (page - 1) * page_size,
            "limit": page_size,
        }

        explain_result = collection.database.command(
            {
                "explain": query,
                "verbosity": "executionStats",
            }
        )

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required",
            )

        # Validate month using the same helper as the real endpoint
        start_s, end_s, start, end = month_bounds(month)

        # Match the employee lookup in the real endpoint
        emp = db.employees.find_one({"emp_code": emp_code})

        if not emp:
            raise HTTPException(
                status_code=404,
                detail="employee not found",
            )

        collection = db.attendance_logs

        # Reuse the exact aggregation pipeline from the real endpoint
        pipeline = monthly_pipeline(
            emp_code,
            start_s,
            end_s,
            emp["joined_on"],
        )

        explain_result = collection.database.command(
            {
                "explain": {
                    "aggregate": collection.name,
                    "pipeline": pipeline,
                    "cursor": {},
                },
                "verbosity": "executionStats",
            }
        )

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required",
            )

        collection = db.attendance_logs

        start_date = f"{month}-01"

        year, month_number = map(int, month.split("-"))

        if month_number < 1 or month_number > 12:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

        if month_number == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month_number + 1:02d}-01"

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": start_date,
                        "$lt": end_date,
                    }
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_records": {"$sum": 1},
                }
            },
        ]

        explain_result = collection.database.command(
            {
                "explain": {
                    "aggregate": collection.name,
                    "pipeline": pipeline,
                    "cursor": {},
                },
                "verbosity": "executionStats",
            }
        )

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required",
            )

        collection = db.attendance_logs

        year, month_number = map(int, month.split("-"))

        if month_number < 1 or month_number > 12:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

        start_date = f"{month}-01"

        if month_number == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month_number + 1:02d}-01"

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": start_date,
                        "$lt": end_date,
                    },
                    "late_minutes": {"$gt": 0},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {
                        "$sum": "$late_minutes"
                    },
                }
            },
            {
                "$sort": {
                    "total_late_minutes": -1
                }
            },
            {"$limit": limit},
        ]

        explain_result = collection.database.command(
            {
                "explain": {
                    "aggregate": collection.name,
                    "pipeline": pipeline,
                    "cursor": {},
                },
                "verbosity": "executionStats",
            }
        )

    else:
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from and to are required",
            )

        collection = db.attendance_logs

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": from_date,
                        "$lte": to_date,
                    }
                }
            },
            {
                "$group": {
                    "_id": "$date",
                    "total_records": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        explain_result = collection.database.command(
            {
                "explain": {
                    "aggregate": collection.name,
                    "pipeline": pipeline,
                    "cursor": {},
                },
                "verbosity": "executionStats",
            }
        )

    return json.loads(json_util.dumps({
        "endpoint": endpoint,
        "collection": collection.name,
        "explain": explain_result,
    }))


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
