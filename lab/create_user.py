from app import app, db
from models import User

with app.app_context():
    db.create_all()
    admin_user = User(username='sharon', password='sharon')
    db.session.add(admin_user)
    db.session.commit()
    print("Admin user created successfully.")