# DECISIONS.md  

## 1. Indexes
I used three indexes in MongoDB. The first one prevents duplicate employee codes, the second one prevents duplicate attendance records for the same employee on the same date, and the third one helps when searching attendance records by date. I also checked the Admin Explain output to see whether MongoDB was using an index for the queries.

## 2. Punch-in Race
If two punch-in requests come at the same time for the same employee, duplicate attendance records can be created if there is no proper check. I used a unique compound index on employee code and date to prevent this. If a duplicate request comes, the application should handle the error properly.

## 3. Ties
For the late leaderboard, I would follow the tie rules given in `openapi.yaml`. If two employees have the same result near the limit, the code should handle them according to those rules.

## 4. Headcount
While calculating department headcount, employees without attendance records should also be counted. Otherwise, the total number of employees in a department could be incorrect. I still need to verify that the current department summary handles this correctly.

## 5. Future Improvement
If the data increases 100 times, I would test the queries again, check how the indexes are working, and make changes wherever needed to improve performance.
