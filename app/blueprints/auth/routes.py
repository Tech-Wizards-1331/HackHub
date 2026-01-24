from flask import render_template, request, session, redirect, url_for, flash
from . import auth_bp
from app.extensions import db
from app.models import User, UserRole
from app.utils.helpers import generate_qr

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role_str = request.form.get('role').upper()
        full_name = request.form.get('full_name')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('auth.register'))
            
        try:
            role = UserRole[role_str]
        except KeyError:
            role = UserRole.PARTICIPANT
            
        user = User(username=username, email=email, role=role, full_name=full_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        # Generate QR code if participant
        if role == UserRole.PARTICIPANT:
            qr_data = f"PARTICIPANT-{user.id}"
            qr_path = generate_qr(qr_data, user.id)
            user.registration_qr = qr_path
            db.session.commit()
            
        flash('Registration successful')
        return redirect(url_for('auth.login'))
        
    return render_template('auth/register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role.value
            session['username'] = user.username
            
            if user.role == UserRole.ADMIN:
                return redirect(url_for('admin.dashboard'))
            elif user.role == UserRole.FACULTY:
                return redirect(url_for('faculty.dashboard'))
            else:
                return redirect(url_for('participant.dashboard'))
        
        flash('Invalid credentials')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
