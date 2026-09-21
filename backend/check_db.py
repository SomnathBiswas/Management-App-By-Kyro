"""Script to check MongoDB connection and data."""
import asyncio
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

async def check_database():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "test_database")
    
    print(f"Connecting to MongoDB...")
    print(f"MongoDB URL: {mongo_url}")
    print(f"Database Name: {db_name}")
    
    try:
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        
        # Test connection
        await client.admin.command('ping')
        print("Successfully connected to MongoDB")
        
        # Check collections
        collections = await db.list_collection_names()
        print(f"\nCollections found: {collections}")
        
        # Check users collection
        if "users" in collections:
            users_count = await db.users.count_documents({})
            print(f"\nUsers count: {users_count}")
            
            if users_count > 0:
                users = await db.users.find().to_list(10)
                print("Sample users:")
                for user in users:
                    print(f"  - Email: {user.get('email')}, Role: {user.get('role')}, Name: {user.get('name')}")
            else:
                print("WARNING: No users found in database")
        else:
            print("WARNING: 'users' collection does not exist")
        
        # Check other collections
        for collection_name in ["members", "plans", "settings", "payments"]:
            if collection_name in collections:
                count = await db[collection_name].count_documents({})
                print(f"{collection_name.capitalize()}: {count} documents")
            else:
                print(f"WARNING: '{collection_name}' collection does not exist")
        
        client.close()
        
    except Exception as e:
        print(f"ERROR: Error connecting to MongoDB: {e}")
        return False
    
    return True

if __name__ == "__main__":
    asyncio.run(check_database())