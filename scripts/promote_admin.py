from app import app
from database.db import get_user_by_email, set_user_admin_by_email

email = "malikjiya690@gmail.com"

with app.app_context():
    user = get_user_by_email(email)
    if user is None:
        print(f"USER_NOT_FOUND:{email}")
    else:
        set_user_admin_by_email(email, True)
        refreshed = get_user_by_email(email)
        print(f"{refreshed['email']} admin={bool(refreshed['is_admin'])}")
