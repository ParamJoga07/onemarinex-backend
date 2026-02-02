#!/usr/bin/env python3
"""
Database connection test script for OneMarinex project
This script tests the PostgreSQL database connection
"""

import psycopg2
import sys
import os
from urllib.parse import urlparse

def test_direct_connection():
    """Test direct connection with hardcoded credentials"""
    print("🔄 Testing direct database connection...")
    
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="onemarinex",
            user="onemarinex_user", 
            password="onemarinex123!",
            port="5432"
        )
        
        cur = conn.cursor()
        
        # Test basic connection
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print("✅ Database connection successful!")
        print(f"PostgreSQL version: {version[0][:50]}...")
        
        # Test current database and user
        cur.execute("SELECT current_database(), current_user;")
        info = cur.fetchone()
        print(f"Connected to database: {info[0]}")
        print(f"Connected as user: {info[1]}")
        
        # Test if we can create tables (permissions test)
        cur.execute("""
            SELECT has_database_privilege(current_user, current_database(), 'CREATE');
        """)
        can_create = cur.fetchone()[0]
        print(f"Can create tables: {'✅ Yes' if can_create else '❌ No'}")
        
        cur.close()
        conn.close()
        
        return True
        
    except Exception as error:
        print(f"❌ Direct connection failed: {error}")
        return False

def main():
    """Run connection test"""
    print("🚀 OneMarinex Database Connection Test")
    print("=" * 50)
    
    # Test direct connection
    test_passed = test_direct_connection()
    
    if test_passed:
        print("\n🎉 Database connection successful! You can proceed with creating tables.")
        return 0
    else:
        print("\n⚠️  Database connection failed. Please check your setup.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
