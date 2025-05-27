from flask_pymongo import PyMongo
from config import MONGO_URI
from flask import Flask

mongo = PyMongo()

#Global Collections
users_collection = None
sessions_collection = None

def init_db(app: Flask):  
    """Initialize the database connection"""
    app.config["MONGO_URI"] = MONGO_URI
    mongo.init_app(app)
    print("✅ MongoDB connected successfully!")
    return initialize_collections()  # Return the result of initialize_collections

def get_database():
    """Return the AIRA database instance"""
    if mongo.db is None:
        print("⚠️ mongo.db is None. Database not initialized yet.")
        raise RuntimeError("MongoDB is not initialized. Call init_db(app) first.")

    print("🟢 MongoDB instance fetched successfully!")
    return mongo.db  

def initialize_collections():
    """Ensure database is initialized after setting collections"""
    global users_collection, chat_history_collection, feedback_collection, question_collection, sessions_collection, auth_codes_collection, brain_collection, reminder_collection, sentiment_collection, echat_history, ejournal

    try:
        db = mongo.db  

        if db is None:
            print("❌ Database instance is None. Initialization failed!")
            return False

        print(f"✅ Database instance fetched: {db}")

        users_collection = db["users"]
        sessions_collection = db["sessions"]  

        # Debugging print statements
        print(f"✅ Collections initialized successfully!")
        print(f"🔍 Available collections: {db.list_collection_names()}") 
            
        return True

    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False

def get_collection(collection_name):
    """Fetch a collection dynamically"""
    db = get_database()
    return db[collection_name]

def get_current_time(return_str=True):
    from datetime import datetime
    import pytz
    india_timezone = pytz.timezone("Asia/Kolkata")
    current_time = datetime.now(india_timezone)
    return current_time.strftime("%Y-%m-%d %H:%M:%S") if return_str else current_time