"""Bootstrap script to create or mark a user as admin.

Usage examples:
  python -m scripts.bootstrap_admin --email admin@example.com --name Admin --password secret
  python -m scripts.bootstrap_admin --email existing@example.com --make-admin
"""
import argparse
from app import create_app


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--name")
    p.add_argument("--password")
    p.add_argument("--make-admin", action="store_true")
    args = p.parse_args()

    app = create_app()
    with app.app_context():
        from database.db import get_user_by_email, create_user, set_user_admin

        user = get_user_by_email(args.email)
        if user is None:
            if not args.password or not args.name:
                print("To create a new user provide --name and --password")
                return
            user = create_user(args.name, args.email, args.password, consent_given=True)
            print(f"Created user {args.email} (id={user['id']})")
        if args.make_admin:
            set_user_admin(user["id"], True)
            print(f"Promoted {args.email} to admin")


if __name__ == "__main__":
    main()
