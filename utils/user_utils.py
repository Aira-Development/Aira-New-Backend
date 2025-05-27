import jwt
from datetime import datetime, timedelta
from config import JWT_SECRET_KEY

def verify_jwt_token(token):
    """Decode the JWT token and return the user_id if valid."""
    try:
        decoded_token = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        return decoded_token.get("user_id")  # Ensure this key exists in the token payload
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError:
        print("Invalid token")
        return None

def get_user_id(auth_header):
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        token = auth_header.split(" ")[1]
        user_id = verify_jwt_token(token)
        return user_id  # Returns string if valid, None if invalid
    except:
        return None