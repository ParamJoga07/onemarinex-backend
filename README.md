# OneMarinex Backend (HeyPorts API)

This is the backend API for the HeyPorts platform, built using **FastAPI**, **SQLAlchemy**, and **Python**. It handles data persistence, authentication, and business logic for the HeyPorts ecosystem.

## 🚀 Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) - High performance, easy to learn, fast to code, ready for production.
- **Database ORM**: [SQLAlchemy](https://www.sqlalchemy.org/) - The Python SQL Toolkit and Object Relational Mapper.
- **Database Migration**: [Alembic](https://alembic.sqlalchemy.org/en/latest/) (if configured) / Direct table creation scripts.
- **Authentication**: JWT (JSON Web Tokens) via `python-jose`.
- **Validation**: [Pydantic](https://docs.pydantic.dev/) models.
- **Server**: [Uvicorn](https://www.uvicorn.org/) - An ASGI web server implementation for Python.

## 🛠️ Prerequisites

- **Python**: 3.9+
- **Database**: PostgreSQL (recommended) or SQLite (for dev).
- **Virtual Environment**: Recommended to avoid dependency conflicts.

## 📦 Installation

1.  Navigate to the backend directory:
    ```bash
    cd onemarinex-backend
    ```

2.  Create a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuration

Create a `.env` file in the root directory (copy from `.env.example` if available) and configure your database URL and secret keys:

```ini
DATABASE_URL=postgresql://user:password@localhost/dbname
SECRET_KEY=your_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

## 🗄️ Database Setup

To initialize the database tables:

```bash
python create_tables.py
```

To seed initial data (pubs, hotels, restaurants):
```bash
python seed_pubs.py
python seed_hotels.py
python seed_restaurants.py
```

## 🏃‍♂️ Running the Server

Start the API server with hot reload enabled:

```bash
uvicorn app.main:app --reload
```

The API will be available at:
- **Root**: `http://127.0.0.1:8000`
- **Interactive Docs (Swagger UI)**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

## 📂 Project Structure

```
onemarinex-backend/
├── app/
│   ├── api/
│   │   └── v1/            # API Route handlers (Version 1)
│   │       ├── routes_auth.py       # Authentication routes
│   │       ├── routes_users.py      # User management
│   │       ├── routes_vendor.py     # Vendor specific logic
│   │       ├── routes_orders.py     # Order processing
│   │       ├── routes_quotes.py     # Quote management
│   │       ├── routes_rfqs.py       # Request for Quotation logic
│   │       ├── routes_crew.py       # Crew management
│   │       └── ...                  # Other entity routes (hotels, pubs, etc.)
│   ├── core/              # Core configuration
│   │   ├── config.py      # Pydantic settings
│   │   └── security.py    # Password hashing and token utilities
│   ├── db/                # Database layer
│   │   ├── base.py        # Import registry for all models
│   │   ├── session.py     # Database session factory
│   │   └── models/        # SQLAlchemy ORM models
│   │       ├── user.py
│   │       ├── order.py
│   │       ├── ...
│   ├── services/          # Business logic & external services
│   │   ├── auth.py
│   │   ├── email.py
│   │   └── storage.py
│   └── main.py            # FastAPI application entry point
├── uploads/               # Directory for uploaded files (served statically)
├── create_tables.py       # Script to initialize database schema
├── requirements.txt       # Python dependencies
└── pyproject.toml         # Project metadata
```

## 🧩 Key Modules

- **`app/main.py`**: Initializes the FastAPI app, configures CORS, and registers routers.
- **`app/api/v1`**: Contains all the endpoints. Each file typically corresponds to a resource (e.g., `routes_users.py` for user operations).
- **`app/db/models`**: Defines the data structure. Adding a new table requires adding a model here and importing it in `app/db/base.py`.
- **`app/core/config.py`**: Centralized configuration management using environment variables.

## 🧪 Testing

To run tests (if configured):
```bash
pytest
```
