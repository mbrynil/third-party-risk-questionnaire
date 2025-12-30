# Third-Party Risk Questionnaire System

## Overview
A FastAPI web application for collecting third-party vendor risk assessments. Admins create questionnaires from a curated GRC question bank, share unique links with vendors, and view submitted responses with completion tracking.

## Tech Stack
- **Framework**: FastAPI
- **Database**: SQLite with SQLAlchemy ORM
- **Templates**: Jinja2
- **UI**: Bootstrap 5 with CDN
- **Server**: Uvicorn

## Project Structure
```
├── main.py              # FastAPI application and routes
├── models.py            # SQLAlchemy database models
├── templates/           # Jinja2 HTML templates
│   ├── base.html        # Base template with Bootstrap 5
│   ├── home.html        # Landing page
│   ├── create.html      # Question bank selection
│   ├── created.html     # Success page with shareable link
│   ├── vendor_form.html # Vendor intake form with answer buttons
│   ├── submitted.html   # Submission confirmation
│   ├── responses.html   # Questionnaire list with completion stats
│   └── questionnaire_responses.html  # Individual response details
└── questionnaires.db    # SQLite database (auto-created)
```

## Features
- **Question Bank**: ~26 curated GRC questions across 7 categories
- **Answer Choices**: Pre-filled buttons (Yes/No/Partial/N/A) instead of text
- **Progress Tracking**: Live progress bar on vendor form
- **Completion Status**: Shows "X/Y complete" on response views
- **Full URLs**: Generates complete shareable links with copy button
- **Validation**: Server-side validation requires all answers

## Pages
- `/` - Home page with navigation
- `/create` - Create questionnaire from question bank
- `/vendor/{token}` - Vendor form with answer buttons
- `/responses` - Questionnaire list with completion stats
- `/responses/{id}` - View individual responses with colored badges

## How to Run
```bash
uvicorn main:app --host 0.0.0.0 --port 5000
```

## Database Models
- **QuestionBankItem**: Category, text, active status
- **Questionnaire**: Company name, title, unique token
- **Question**: Question text, order, linked to questionnaire
- **Response**: Vendor name, email, submission date
- **Answer**: Answer choice (yes/no/partial/na), linked to question and response
