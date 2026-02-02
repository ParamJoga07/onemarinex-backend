from app.db.base import engine, Base

def create_tables():
    """Create all tables in the database"""
    try:
        # Import models to register them with Base
        from app.db.models.user import User
        print("User model imported successfully")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        print("✅ All tables created successfully!")
        
        # List the tables that were created
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"Created tables: {tables}")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    create_tables()
