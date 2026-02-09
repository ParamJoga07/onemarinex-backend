from sqlalchemy import create_engine, inspect
from app.core.config import settings

def check_schema():
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    
    print(f"🔄 Checking columns for 'users' table...")
    columns = [col['name'] for col in inspector.get_columns('users')]
    print(f"Columns: {columns}")
    
    if 'mobile_number' in columns:
        print("✅ 'mobile_number' column exists.")
    else:
        print("❌ 'mobile_number' column is MISSING.")
        
    print(f"\n🔄 Checking for new tables...")
    tables = inspector.get_table_names()
    print(f"Tables: {tables}")
    
    for table in ['crew_profiles', 'client_profiles']:
        if table in tables:
            print(f"✅ Table '{table}' exists.")
        else:
            print(f"❌ Table '{table}' is MISSING.")

if __name__ == "__main__":
    check_schema()
