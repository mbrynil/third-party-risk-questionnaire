# Third-Party Risk Questionnaire System

## Overview
A simple FastAPI web application for collecting third-party vendor risk assessments. Admins can create questionnaires, share unique links with vendors, and view submitted responses.

## Tech Stack
- **Framework**: FastAPI
- **Database**: SQLite with SQLAlchemy ORM
- **Templates**: Jinja2
- **Server**: Uvicorn

## Project Structure
```
├── main.py              # FastAPI application and routes
├── models.py            # SQLAlchemy database models
├── templates/           # Jinja2 HTML templates
│   ├── base.html
│   ├── home.html
│   ├── create.html
│   ├── created.html
│   ├── vendor_form.html
│   ├── submitted.html
│   ├── responses.html
│   └── questionnaire_responses.html
└── questionnaires.db    # SQLite database (auto-created)
```

## Pages
- `/` - Home page with navigation
- `/create` - Admin page to create new questionnaires
- `/vendor/{token}` - Public vendor form (unique per questionnaire)
- `/responses` - Admin page listing all questionnaires
- `/responses/{id}` - View responses for specific questionnaire

## How to Run
```bash
uvicorn main:app --host 0.0.0.0 --port 5000
```

## Database Models
- **Questionnaire**: Title, unique token, creation date
- **Question**: Question text, order, linked to questionnaire
- **Response**: Vendor name, email, submission date
- **Answer**: Answer text, linked to question and response
