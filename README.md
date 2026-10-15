# Candidate kit
Employee Attendance and Productivity KPI API

1. Project Overview

This project is an Employee Attendance and Productivity KPI API built using Python, FastAPI, and MongoDB.

It supports employee management, attendance tracking, punch-in, punch-out, attendance regularization, work-hour calculations, and reporting.

2. Technologies Used

Python

FastAPI

Uvicorn

MongoDB

PyMongo

python-dotenv


3. Project Files

app/main.py – Contains the API implementation.

requirements.txt – Lists the required Python packages.

openapi.yaml – Defines the API contract and business rules.

DATA_MODEL.md – Describes the MongoDB data model.

sample_data/ – Contains nine sample documents.

sample_seed.py – Loads sample data into MongoDB.

REVIEW.md – Contains review notes.

DECISIONS.md – Documents design decisions.

.env.example – Provides example MongoDB configuration.


4. Setup Instructions

Step 1: Clone the Repository

git clone YOUR_GITHUB_REPOSITORY_URL
cd candidate_kit

Replace the URL with your GitHub repository URL.

Step 2: Create a Virtual Environment

python -m venv .venv

Windows Command Prompt:

.venv\Scripts\activate.bat

Windows PowerShell:

.\.venv\Scripts\Activate.ps1

macOS/Linux:

source .venv/bin/activate

Step 3: Install Dependencies

python -m pip install -r requirements.txt

If PowerShell blocks activation, use the virtual environment's Python directly:

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

5. Configure MongoDB

Create your own .env file in the project root, alongside requirements.txt.

Copy .env.example to .env.

Windows PowerShell:

Copy-Item .env.example .env

Windows Command Prompt:

copy .env.example .env

macOS/Linux:

cp .env.example .env

Open .env and enter your own MongoDB connection details:

MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_dev

Replace the example connection string with your own MongoDB URI.

MongoDB 6.0 or newer is required. MongoDB Atlas can also be used.

Never upload your actual .env file or database credentials to GitHub.

6. Load Sample Data

Configure your .env file before loading sample data.

With the virtual environment activated:

python sample_seed.py

Without activating the environment on Windows:

.\.venv\Scripts\python.exe sample_seed.py

The script loads the sample documents into your configured MongoDB database.

7. Run the Application

Recommended method for Windows when the virtual environment is not activated:

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

If the virtual environment is already activated:

python -m uvicorn app.main:app --reload --port 8000

Using the virtual environment's Python executable directly avoids issues when the terminal selects a different Python environment.

8. Access API Documentation

After the server starts, open:

http://127.0.0.1:8000/docs

Use Swagger UI to view and test the available API endpoints.

9. Attendance Regularization (PATCH)

The attendance regularization PATCH endpoint uses Unix timestamps in milliseconds for the punch_in and punch_out fields.

Enter timestamps in milliseconds, not a date string such as 2026-05-10.

To test the endpoint:

1. Open /docs.


2. Find the attendance regularization PATCH endpoint.


3. Click Try it out.


4. Enter the required employee details.


5. Provide punch_in and punch_out as Unix timestamps in milliseconds.


6. Click Execute and check the response.



Refer to openapi.yaml for the complete request schema and required fields.

10. Security Notes

Keep MongoDB credentials private.

Do not upload .env or .venv to GitHub.

Use your own MongoDB connection when running the project.

Follow the API contract and business rules defined in openapi.yaml.
