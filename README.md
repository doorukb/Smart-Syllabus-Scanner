# Smart Syllabus Scanner

- Python 3.10+
- Anhropic Claude API (tool_use, multi-turn, Batch API)
- Pydantic v2
- pdfplumber
- Fast API
- python-dotenv
- icalendar
  
<br><br>

A document intelligence pipeline that takes a raw PDF/PNG/TXT syllabus, and extracts structured course data using the Anthropic Claude API, validates it with a second LLM reasoning pass, and exposes the full system as a FastAPI REST microservice with asynchronous batch processing support. 

Most syllabus information (grading policies, deadlines, instructor contacts) lives in unstructured PDFs that no system can query directly. Smart Syllabus Scanner solves this by turning any syllabus into clean, validated, machine-readable JSON in two LLM passes : 
- Pass 1 - Extraction : PDF text is routed through Claude via native tool_use, producing a Pydantic-validated JSON object with automatic retry on malformed output. 
- Pass 2 - Reasoning: A second Claude call reads the extracted data. It checks correctness, such as whether grading weights sum to 100%, flags date conflicts, and scores unusually strict policies by severity. The result is a reliable, queryable data object the downstream systems can actually use.

<br><br>

# INSTALLATION
1. Clone and enter the repo
- git clone https://github.com/doorukb/smart-syllabus-scanner.git
- cd smart-syllabus-scanner

2. Create and activate a virtual environment
- python -m venv .venv

macOS / Linux 
- Run source .venv/bin/activate

Windows 
- Run .venv\Scripts\activate

3. Install dependencies
- pip install -r requirements.txt

4. Set up your API key
- copy .env.example .env (Windows)
- cp .env.example .env  (macOS / Linux)
- Open .env and replace the placeholder with your real key
- Get a key at: https://console.anthropic.com/settings/keys

<br><br>

# USAGE

A) CLI - Single File

Extract from a PDF
- python demo_extract.py --file syllabus.pdf

Extract from plain text
- python demo_extract.py --file syllabus.txt

Pipe from stdin
- type syllabus.txt | python demo_extract.py        (Windows)
- cat syllabus.txt  | python demo_extract.py        (macOS / Linux)

Debug mode (prints stop reason and error class to stderr)
- python demo_extract.py --file syllabus.pdf --debug

Limit characters sent for long documents (default: 50,000)
- python demo_extract.py --file syllabus.txt --max-chars 20000

Write output directly to a file
- python demo_extract.py --file syllabus.pdf > output.json

Export important dates to an iCalendar file (confirmation goes to stderr; JSON stays on stdout)
- python demo_extract.py --file syllabus.txt --export-calendar out.ics

B) Web UI

Start the server (from the project root)
- uvicorn api.main:app --reload

Open the app in your browser
- http://localhost:8000/app  (or http://localhost:8000/ — redirects to the app)

Upload a syllabus file PDF/JPG/PNG/TXT or paste text, click 
**Extract syllabus**, then review the overview, grading, dates, and policy cards. 
If you wish, use **Download JSON** or **Download calendar (.ics)** in the Overview card to export results (calendar uses `POST /calendar` with the cached extraction, which doesn't require a separate call). You can export this file into an external calendar app, such as Google Calendar, but make sure your syllabus contains clear dates before doing so.
Use the chat panel below the results to ask questions; follow-up messages keep full conversation context. Click **Parse another syllabus** to reset and start over.

C) REST API

Interactive API docs (Swagger UI) — test every endpoint in the browser
- http://localhost:8000/docs

API metadata
- http://localhost:8000/api

Health check
- curl http://localhost:8000/health

POST a syllabus file
- curl -X POST http://localhost:8000/extract -F "file=@syllabus.pdf"

POST raw syllabus text
- curl -X POST http://localhost:8000/extract -F "text=@syllabus.txt"

Download an .ics calendar file
- curl -X POST http://localhost:8000/extract/calendar -F "file=@syllabus.pdf" -o syllabus.ics

D) Batch Processing

Process a full folder of syllabi asynchronously
- python batch_extract.py --folder ./syllabi --output combined.json

<br><br>

# INPUT : 
```
CS 101: Introduction to Computer Science
Fall 2025

Instructor: Dr. Jane Smith
Email: j.smith@university.edu
Office Hours: Monday/Wednesday 2–3 PM, Room 304

Course Description:
An introduction to the fundamentals of computer science, covering
algorithms, data structures, and basic programming concepts.

Grading:
  Homework Assignments: 30%
  Midterm Exam:         25%
  Final Exam:           35%
  Participation:        10%

Important Dates:
  Midterm Exam:            October 15, 2025
  Last day to withdraw:    November 1, 2025
  Final Exam:              December 10, 2025

Policies:
- Late submissions will be penalized 10% per day, up to a maximum of 50%.
- Attendance is expected at all lectures and recitations.
- Academic dishonesty (plagiarism, cheating) will result in a zero for
  the assignment and may be referred to the academic integrity office.
- Students requiring accommodations should contact the instructor within
  the first two weeks of the semester.
- All electronic devices must be silenced during lectures.

```

# OUTPUT : 
```
{
  "course_code": "CS 101",
  "instructor_email": "j.smith@university.edu",
  "grading_weights": [
    { "component": "Homework Assignments", "percent": 30.0 },
    { "component": "Midterm Exam",         "percent": 25.0 },
    { "component": "Final Exam",           "percent": 35.0 },
    { "component": "Participation",        "percent": 10.0 }
  ],
  "important_dates": [
    { "label": "Midterm Exam",          "date_iso": "2025-10-15", "raw_text": "" },
    { "label": "Last day to withdraw",  "date_iso": "2025-11-01", "raw_text": "" },
    { "label": "Final Exam",            "date_iso": "2025-12-10", "raw_text": "" }
  ],
  "policy_bullets": [
    "Late submissions will be penalized 10% per day, up to a maximum of 50%.",
    "Academic dishonesty will result in a zero and may be referred to the academic integrity office."
  ],
  "validation": {
    "grading_sums_to_100": true,
    "date_conflicts": [],
    "policy_flags": [
      {
        "policy": "Late submissions will be penalized 10% per day, up to a maximum of 50%.",
        "severity": 2,
        "reason": "Above-average late penalty rate."
      }
    ]
  }
}
```
