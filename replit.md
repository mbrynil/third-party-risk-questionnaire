# Third-Party Risk Questionnaire System

## Overview
A FastAPI web application for collecting third-party vendor risk assessments. Admins create questionnaires from a curated GRC question bank, share unique links with vendors, and view submitted responses with completion tracking. Vendors can save drafts and resume later.

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
│   ├── vendor_form.html # Vendor intake form with draft support
│   ├── submitted.html   # Submission confirmation
│   ├── responses.html   # Questionnaire list with status counts
│   └── questionnaire_responses.html  # Individual response details
├── uploads/             # Evidence file storage (gitignored)
│   └── {questionnaire_id}/{response_id}/  # Organized by questionnaire and response
└── questionnaires.db    # SQLite database (auto-created)
```

## Features
- **Question Bank**: ~170+ curated GRC questions across 25 categories
- **Question Weights**: Company A can assign weights (Low/Medium/High/Critical) to each question during questionnaire creation
- **Answer Choices**: Pre-filled buttons (Yes/No/Partial/N/A) instead of text
- **Notes Field**: Optional notes/comments per question
- **Save Draft**: Vendors can save partial progress and resume later
- **Resume by Email**: Enter email to load previous draft answers
- **Progress Tracking**: Live progress bar on vendor form
- **Last Saved Timestamp**: Shows when draft was last saved
- **Submit Final**: Locks the form after final submission
- **Status Badges**: DRAFT vs SUBMITTED status on dashboard
- **Status Filtering**: Filter responses by DRAFT or SUBMITTED
- **Completion Progress**: Visual progress bars per response
- **Validation**: Server-side validation requires all answers for final submit
- **Evidence Uploads**: Vendors can upload supporting documents (PDF, DOCX, XLSX, PNG, JPG, JPEG) up to 10MB per file
- **Evidence Management**: View/download evidence files on admin dashboard, delete files before submission

## Pages
- `/` - Home page with navigation
- `/create` - Create questionnaire from question bank
- `/vendor/{token}` - Vendor form with save draft/submit
- `/responses` - Questionnaire list with DRAFT/SUBMITTED counts
- `/responses/{id}` - View responses with status filter and progress bars

## API Endpoints
- `GET /api/vendor/{token}/check-draft?email=` - Check for existing draft
- `GET /api/vendor/{token}/evidence?email=` - List evidence files for a vendor
- `POST /vendor/{token}/upload-evidence` - Upload evidence file (multipart form)
- `DELETE /vendor/{token}/evidence/{id}?vendor_email=` - Delete evidence file
- `GET /evidence/{id}` - Download evidence file
- `GET /submissions/{submission_id}/export` - Print-friendly export page for PDF generation

## How to Run
```bash
uvicorn main:app --host 0.0.0.0 --port 5000
```

## Database Models
- **QuestionBankItem**: Category, text, active status
- **Questionnaire**: Company name, title, unique token
- **Question**: Question text, order, linked to questionnaire
- **Response**: Vendor name, email, status (DRAFT/SUBMITTED), submitted_at, last_saved_at
- **Answer**: Answer choice (yes/no/partial/na), notes, linked to question and response
- **EvidenceFile**: original_filename, stored_filename, stored_path, content_type, size_bytes, uploaded_at, linked to questionnaire and response
- **FollowUp**: message, created_at, response_text, responded_at, linked to response

## Schema Notes
- When schema changes, delete questionnaires.db to recreate (dev only)
- Status values: DRAFT (in progress), SUBMITTED (final, locked), NEEDS_INFO (awaiting vendor follow-up response)
