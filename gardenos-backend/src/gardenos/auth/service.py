from config.config import settings, engine, auth
from sqlalchemy.orm import Session
from flask import current_app
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt(current_app)

def hash_password(password: str) -> str:
    return bcrypt.generate_password_hash(password).decode('utf-8')

def verify_hashed_password(password: str, password_hashed: str) -> bool:
    return bcrypt.check_password_hash(password_hashed, password)
    
@auth.verify_password
def verify_login(email: str, password: str) -> bool:
    """
        Verify if given email and password from 
        logging form is a regitered user
    """
    # TODO