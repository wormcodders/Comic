# File Structure - Comics Collection App

```
E:\Comic\
├── app.py                    # Main Flask application entry point
├── config.py                 # Flask configuration (DB URI, secret keys, etc.)
├── models.py                 # SQLAlchemy database models
├── requirements.txt          # Python package dependencies
├── vision_llm.py             # Standalone AI script for comic metadata extraction
├── database.py               # Database initialization and utility functions
├── design.md                 # Design template from screenshots
│
├── static/
│   ├── css/
│   │   └── style.css         # Main responsive stylesheet
│   ├── js/
│   │   └── main.js           # Client-side JavaScript
│   ├── uploads/
│   │   ├── comics/           # Stored PDF comic files
│   │   └── covers/           # Cover image files
│   └── images/               # UI assets, icons, logos
│
├── templates/
│   ├── base.html             # Base template with bottom nav
│   ├── index.html            # Home/dashboard page
│   ├── category.html         # Category-wise comic listing
│   ├── comic_detail.html     # Individual comic page
│   ├── read.html             # PDF reader (PDF.js)
│   ├── library.html          # User's reading library
│   ├── profile.html          # User profile page
│   ├── auth/
│   │   ├── login.html        # Login form
│   │   └── register.html     # Registration form
│   └── admin/
│       ├── dashboard.html    # Admin overview/dashboard
│       ├── add_comic.html    # Add new comic form (with AI auto-fill)
│       ├── comics.html       # Manage existing comics
│       └── ads.html          # Manage ad placements
│
├── comic_uploads/            # Local PDF storage directory
│
└── venv/                     # Python virtual environment
```