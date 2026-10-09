# OfficeRide backend (Phase 1: foundation)

Django + PostgreSQL. This phase has the project skeleton, split settings, a custom email-login User, the admin, and a home page.

## Run it
1. Create the database: `createdb officeride`
2. Create and activate a virtual environment:
   - Mac/Linux: `python3 -m venv venv && source venv/bin/activate`
   - Windows: `python -m venv venv` then `venv\Scripts\activate`
3. Install packages: `pip install -r requirements/base.txt`
4. Copy `.env.example` to `.env` and fill in `SECRET_KEY` and your database login.
5. Build the tables: `python manage.py migrate`
6. Create an admin: `python manage.py createsuperuser` (it asks for an email and password)
7. Start the server: `python manage.py runserver`
8. Open http://127.0.0.1:8000 (home) and http://127.0.0.1:8000/admin/ (admin)

## Check it
`python manage.py test` runs the Phase 1 tests (they create a temporary test database in PostgreSQL).

## Layout
- `config/settings/` base, dev and prod settings (dev is the default)
- `apps/accounts/` custom User model
- `apps/core/` home page
- `templates/` shared templates, `static/` CSS, JS and images
