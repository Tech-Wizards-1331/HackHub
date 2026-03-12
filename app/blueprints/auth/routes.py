from flask import render_template, request, session, redirect, url_for, flash
from . import auth_bp
from app.extensions import db
from app.models import User, UserRole
from app.utils.helpers import generate_qr

import uuid

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role_str = (request.form.get('role') or 'participant').upper()
        full_name = request.form.get('full_name')
        university_name = (request.form.get('university_name') or '').strip()
        experience_level = (request.form.get('experience_level') or '').strip()

        if not university_name:
            flash('University Name is required', 'error')
            return redirect(url_for('auth.register'))

        allowed_experience = {'Beginner', 'Intern', 'Expert'}
        if experience_level not in allowed_experience:
            flash('Experience Level is required', 'error')
            return redirect(url_for('auth.register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('auth.register'))
            
        try:
            role = UserRole[role_str]
        except KeyError:
            role = UserRole.PARTICIPANT
        
        # Extract and validate skills for participants
        skills_str = None
        if role == UserRole.PARTICIPANT:
            # Get selected predefined skills
            selected_skills = request.form.getlist('skills')
            
            # Get custom skills
            custom_skills = request.form.get('custom_skills', '').strip()
            
            # Combine all skills
            all_skills = selected_skills.copy()
            if custom_skills:
                # Split by comma and clean up
                custom_list = [s.strip() for s in custom_skills.split(',') if s.strip()]
                all_skills.extend(custom_list)
            
            # Validate at least one skill is provided
            if not all_skills:
                flash('Participants must provide at least one technical skill', 'error')
                return redirect(url_for('auth.register'))
            
            # Store as comma-separated string
            skills_str = ', '.join(all_skills)
        
        # Generte persistent QR Token
        qr_token = str(uuid.uuid4())

        user = User(
            username=username,
            email=email,
            role=role,
            full_name=full_name,
            skills=skills_str,
            college=university_name,
            experience_level=experience_level,
            qr_token=qr_token
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        # Generate QR code if participant (using the permanent token)
        if role == UserRole.PARTICIPANT:
            qr_path = generate_qr(qr_token, user.id)
            user.registration_qr = qr_path
            db.session.commit()
            
        flash('Registration successful', 'success')
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
        
        flash('Invalid credentials', 'error')

    demo_users = (
        User.query
        .filter(User.email.like('%@hackhub.demo'))
        .order_by(User.role, User.id)
        .all()
    )
    return render_template('auth/login.html', demo_users=demo_users)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
