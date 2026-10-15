# REVIEW.md

## Defects I Found

| # | Where (function / line) | What is wrong | How I'd notice it | How I fixed it |
|---|---|---|---|---|
| 1 | Get employees endpoint | The skip calculation was wrong. Because of this, the first page could skip the first set of employees. | When I tried to get the employee list, it showed no employees even though records were present. | I changed the skip calculation to `(page - 1) * page_size`. |
| 2 | Punch-in | The datetime and timezone handling was not consistent with IST. | When I checked the punch-in time in MongoDB, it showed UTC, which made it confusing to compare with Indian time. | I used `datetime.now(IST)` to make the punch-in datetime timezone-aware. |
| 3 | Punch-out | The punch-in and punch-out times were not being handled consistently, which affected the work-hours calculation. | While testing different employees, I noticed that the timestamps looked inconsistent and some work-hours values were incorrect. | I checked the timezone handling and updated punch-in to use IST. The complete punch-out logic still needs to be checked. |
| 4 | Admin Explain — department_summary | The Explain output groups attendance records by employee code instead of department. | When I tested `department_summary`, I saw that the aggregation grouped by `emp_code` and counted attendance records. | I identified this issue, but I still need to check the actual department-summary code before deciding how to fix it. |

## Things I Checked but Didn't Confirm as Defects

1. **MongoDB connection:** I tested the connection and got `{'ok': 1.0}`, so MongoDB was responding successfully.

2. **Date index:** I checked the Admin Explain output and found that MongoDB was using the `idx_attendance_date` index. The query examined one key and one document.

3. **Running the application:** I was able to run the application using the Python executable from my virtual environment.

4. **Health check:** The health endpoint returned `{"status": "ok"}`. However, this response alone does not confirm that MongoDB is connected.

5. **Unique indexes:** I considered using unique indexes to prevent duplicate employee codes and duplicate attendance records for the same employee and date. I still need to verify their definitions and behavior in the actual code.

## Note

These are the issues I noticed while testing and working on the project. I still need to check the complete `main.py` against the requirements to make sure I haven't missed anything.
