# Smart Syllabus Scanner

- Python 3.10+
- Anthropic Claude API (tool_use, multi-turn, async)
- Pydantic v2
- FastAPI + Uvicorn
- python-dotenv
- icalendar
- Docker (optional)

A document intelligence pipeline that takes a raw PDF, PNG, JPG, or TXT syllabus and extracts structured course data using the Anthropic Claude API, validates it with a second LLM reasoning pass, and exposes the full system as a FastAPI REST microservice with a browser-based UI and a conversational Q&A layer.

Most syllabus information (grading policies, deadlines, instructor contacts) lives in unstructured PDFs that no system can query directly. Smart Syllabus Scanner solves this by turning any syllabus into clean, validated, machine-readable JSON in two LLM passes :
- Step 1 - Extraction : The document is routed through Claude via native tool_use, producing a Pydantic-validated JSON object containing the course code, instructor email, grading weights, important dates, policy statements, and letter-grade cutoffs when present. Malformed or schema-violating responses trigger automatic retry rather than propagating to Stage 2.
- Step 2 - Cross Validation (Concurrent) : Two Claude calls run concurrently using asyncio.gather, each evaluating a different quality dimension of the Step 1 output. Running these as parallel, independent passes rather than a single combined call keeps two quality signals separate: structural correctness and semantic quality have different failure modes, and conflating them into one prompt makes each harder to isolate when something goes wrong. Both results are returned alongside the Stage 1 extraction.
  - Structural validation checks whether grading weights sum to 100%, flags date conflicts (e.g., withdrawal deadline after the final     exam), and surfaces any logical inconsistencies in the extracted data
  - Semantic quality scoring evaluates each policy statement for severity and potential student impact, returning a structured            severity rating per policy

- Step 3 - Delivery : Validated output reaches three downstream consumers : a FastAPI REST microservice (interactive docs at /docs), a browser-based dashboard, and a multi-turn Q&A layer. The Q&A layer uses the validated JSON as its sole knowledge source, and it is explicitly prohibited from using outside knowledge, which means answer accuracy is directly bounded by the precision of the extraction and validation stages above it.

<br><br>

### Installation
1. Clone and enter the repo
- git clone https://github.com/doorukb/smart-syllabus-scanner.git
- cd smart-syllabus-scanner

2. Create and activate a virtual environment
- python -m venv .venv

macOS / Linux
- source .venv/bin/activate

Windows
- .venv\Scripts\activate

3. Install dependencies
- pip install -r requirements.txt

4. Set up your API key : your Anthropic API key is required.
- copy .env.example .env (Windows)
- cp .env.example .env (macOS / Linux)
- Open .env and replace the placeholder with your real key
- Get a key at: https://console.anthropic.com/settings/keys
- Place your key to .env : ANTHROPIC_API_KEY = (your key)
- Never share this key with anyone, and never commit .env

<br><br>

### Docker

If you have Docker installed you can skip the virtual environment and pip steps entirely.

1. Set up your API key (same as step 4 above, required before building)
- copy .env.example .env (Windows)
- cp .env.example .env (macOS / Linux)
- Add your ANTHROPIC_API_KEY to the .env file

2. Build and start the container
- docker compose up --build

Open the app at http://localhost:8000/app

To stop the container
- docker compose down

<br><br>

### Usage
#### A) Web UI

Start the server from the project root
- uvicorn api.main:app --reload

Open the app in your browser
- http://localhost:8000/app

Upload a syllabus file (PDF, JPG, PNG, or TXT) or paste text directly, then click Extract syllabus. The results appear as cards showing the overview, grading breakdown, letter-grade scale (when present in the syllabus), important dates, and policies with severity ratings.

From the Overview card you can download the extracted data as a JSON file or as an .ics iCalendar file that can be imported into Google Calendar, Apple Calendar, or Outlook. Note that calendar export only produces events for dates the model could parse to a specific day, syllabi that use relative schedules (Week 8, two weeks before finals) will produce an empty calendar. So make sure your syllabus contains specific and parse-able dates.

Use the chat panel below the results to ask questions in natural language. Follow-up messages keep full conversation context. Click Parse another syllabus to reset and start over.

Here's an example conversation in natural language. As the conversation history is stored in JSON format during runtime, he model is aware of the context and you can carry the conversation as long as you wish. 

<p align="center">
<img width="400" height="250" alt="image" src="https://github.com/user-attachments/assets/14144567-6cb8-4490-99be-76ec96b97bbd" />
</p>

#### B) CLI - Single File

Extract from a PDF
- python src/demo_extract.py --file syllabus.pdf

Extract from plain text
- python src/demo_extract.py --file syllabus.txt

Pipe from stdin
- type syllabus.txt | python src/demo_extract.py (Windows)
- cat syllabus.txt | python src/demo_extract.py (macOS / Linux)

Debug mode (prints stop reason and model call count to stderr)
- python src/demo_extract.py --file syllabus.pdf --debug

Limit characters sent for long documents (default: 50,000, no effect on PDF/image)
- python src/demo_extract.py --file syllabus.txt --max-chars 20000

Write output directly to a file
- python src/demo_extract.py --file syllabus.pdf > output.json

Export important dates to an iCalendar file (confirmation goes to stderr, JSON stays on stdout)
- python src/demo_extract.py --file syllabus.txt --export-calendar out.ics

##### Input (TXT/PDF/PNG/JPG) :
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

Grade Scale:
  A:  93% and above
  A-: 90 - 92%
  B+: 87 - 89%
  B:  83 - 86%
  B-: 80 - 82%
  C+: 77 - 79%
  C:  73 - 76%
  C-: 70 - 72%
  D:  60 - 69%
  F:  below 60%

Policies:
- Late submissions will be penalized 10% per day, up to a maximum of 50%.
- Attendance is expected at all lectures and recitations.
- Academic dishonesty (plagiarism, cheating) will result in a zero for
  the assignment and may be referred to the academic integrity office.
- Students requiring accommodations should contact the instructor within
  the first two weeks of the semester.
- All electronic devices must be silenced during lectures.

```

##### Output (JSON) : 
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
  "grade_scale": [
    { "letter": "A",  "min_percent": 93.0 },
    { "letter": "A-", "min_percent": 90.0 },
    { "letter": "B+", "min_percent": 87.0 },
    { "letter": "B",  "min_percent": 83.0 },
    { "letter": "B-", "min_percent": 80.0 },
    { "letter": "C+", "min_percent": 77.0 },
    { "letter": "C",  "min_percent": 73.0 },
    { "letter": "C-", "min_percent": 70.0 },
    { "letter": "D",  "min_percent": 60.0 },
    { "letter": "F",  "min_percent": null }
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

##### Output (.ICS)
Using this file, you may export the dates in your syllabus to an external calendar app, such as Google Calendar, iCalendar, etc.
```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Syllabus Parser//EN
CALSCALE:GREGORIAN
X-WR-CALNAME:CS 101
BEGIN:VEVENT
SUMMARY:Midterm Exam
DTSTART;VALUE=DATE:20251015
DTEND;VALUE=DATE:20251016
DESCRIPTION:Midterm Exam
END:VEVENT
BEGIN:VEVENT
SUMMARY:Last day to withdraw
DTSTART;VALUE=DATE:20251101
DTEND;VALUE=DATE:20251102
DESCRIPTION:Last day to withdraw
END:VEVENT
BEGIN:VEVENT
SUMMARY:Final Exam
DTSTART;VALUE=DATE:20251210
DTEND;VALUE=DATE:20251211
DESCRIPTION:Final Exam
END:VEVENT
END:VCALENDAR
```


#### C) REST API

Interactive API docs (Swagger UI) - test every endpoint in the browser
- http://localhost:8000/docs

Health check
- curl http://localhost:8000/health

API info and endpoint list
- curl http://localhost:8000/api

POST a syllabus file, returns extraction + validation + policy flags as JSON
- curl -X POST http://localhost:8000/extract -F "file=@syllabus.pdf"

POST raw syllabus text
- curl -X POST http://localhost:8000/extract -F "text=CS 101..."

Download an .ics calendar file (re-runs full extraction)
- curl -X POST http://localhost:8000/extract/calendar -F "file=@syllabus.pdf" -o syllabus.ics

Generate an .ics file from already-extracted JSON (no extra Claude call)
- curl -X POST http://localhost:8000/calendar -H "Content-Type: application/json" -d '{"extraction": {...}}' -o syllabus.ics

Ask a question about an extracted syllabus (multi-turn, send full history each request)
- curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"extraction": {...}, "history": [], "message": "What happens if I submit late?"}'
