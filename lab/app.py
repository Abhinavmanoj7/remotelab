from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort, send_file
from werkzeug.security import check_password_hash
from models import *
import random
import os
from datetime import datetime, timedelta
import pathlib

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24))
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///exams.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(pathlib.Path.cwd(), 'Uploads')

db.init_app(app)

with app.app_context():
    db.create_all()

from collections import defaultdict

def distribute_questions(num_people, questions):
    min_per_question = num_people // len(questions)
    result = [None] * num_people
    question_count = defaultdict(int)

    for i in range(num_people):
        available = []
        for q in questions:
            adjacent_ok = i == 0 or q != result[i - 1]
            distribution_ok = question_count[q] < min_per_question or (
                all(question_count[other] >= min_per_question for other in questions)
            )
            if adjacent_ok and distribution_ok:
                available.append(q)

        if not available:
            return distribute_questions(num_people, questions)

        selected = random.choice(available)
        result[i] = selected
        question_count[selected] += 1

    return result

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('create_exam'))
        else:
            flash('Invalid credentials!', 'danger')

    return render_template('login.html')

@app.route('/create_exam', methods=['GET', 'POST'])
def create_exam():
    if not session.get('logged_in'):
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        duration = float(request.form.get('duration'))
        reg_prefix = request.form.get('reg_prefix')
        reg_range = request.form.get('reg_range')
        
        try:
            start, end = map(int, reg_range.split('-'))
            if start >= end:
                flash('Range start must be less than end', 'danger')
                return render_template('create_exam.html', exams=Exam.query.all())
        except ValueError:
            flash('Invalid range format. Use start-end (e.g., 1-10)', 'danger')
            return render_template('create_exam.html', exams=Exam.query.all())
            
        new_exam = Exam(
            name=name,
            duration=duration,
            reg_number_prefix=reg_prefix,
            reg_number_range=reg_range
        )
        db.session.add(new_exam)
        db.session.flush()
        
        for i in range(start, end + 1):
            reg_number = f"{reg_prefix}{i:03d}" 
            student = Student(
                registration_number=reg_number,
                exam_id=new_exam.id
            )
            db.session.add(student)
            
        db.session.commit()
        flash(f'Exam "{name}" created with {end-start+1} students!', 'success')
        return redirect(url_for('add_questions', exam_id=new_exam.id))
        
    exams = Exam.query.all()
    return render_template('create_exam.html', exams=exams)

@app.route('/add_questions/<int:exam_id>', methods=['GET', 'POST'])
def add_questions(exam_id):
    if not session.get('logged_in'):
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))
        
    exam = Exam.query.get_or_404(exam_id)
    
    if request.method == 'POST':
        question_number = request.form.get('question_number')
        question_text = request.form.get('question_text')
        
        if not question_number or not question_text:
            flash('Both question number and text are required!', 'danger')
        else:
            try:
                q_num = int(question_number)
                
                existing_question = Question.query.filter_by(
                    exam_id=exam_id, 
                    question_number=q_num
                ).first()
                
                if existing_question:
                    flash(f'Question number {q_num} already exists for this exam!', 'danger')
                else:
                    new_question = Question(
                        question_number=q_num,
                        question_text=question_text,
                        exam_id=exam_id
                    )
                    db.session.add(new_question)
                    db.session.commit()
                    flash('Question added successfully!', 'success')
            except ValueError:
                flash('Question number must be an integer!', 'danger')
        
    questions = Question.query.filter_by(exam_id=exam_id).order_by(Question.question_number).all()
    
    return render_template('add_questions.html', exam=exam, questions=questions)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        reg_number = request.form.get('reg_number')
        exam_id = request.form.get('exam_id')
        current_ip = request.remote_addr
        exam = Exam.query.get_or_404(exam_id)
        if exam.is_ended:
            flash('The exam has ended. Registration is not allowed.', 'danger')
            return redirect(url_for('register'))
        student = Student.query.filter_by(
            registration_number=reg_number,
            exam_id=exam_id
        ).first()

        if student:
            if student.submitted_file:
                flash('You have already submitted your answer. Login is not allowed.', 'danger')
                return redirect(url_for('register'))

            if student.ip_address and student.ip_address != current_ip:
                flash('Please login from your registered PC!', 'danger')
            else:
                if not student.ip_address:
                    student.ip_address = current_ip
                    db.session.commit()
                flash('Registration successful!', 'success')
                return redirect(url_for('student_exam', student_id=student.id))
        else:
            flash('Invalid registration number or exam ID!', 'danger')

    exams = Exam.query.all()
    return render_template('register.html', exams=exams)

@app.route('/stop_exam', methods=['POST'])
def stop_exam():
    if not session.get('logged_in'):
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))

    exam_id = request.form.get('exam_id')
    exam = Exam.query.get_or_404(exam_id)
    
    exam.is_ended = True
    db.session.commit()
    
    flash(f'Exam "{exam.name}" has been stopped!', 'success')
    return redirect(url_for('exam_details', exam_id=exam_id))

@app.route('/start_exam', methods=['GET', 'POST'])
def start_exam():
    if not session.get('logged_in'):
        flash('Please login first!', 'warning')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        exam_id = request.form.get('exam_id')
        
        exam_questions = Question.query.filter_by(exam_id=exam_id).all()
        
        if not exam_questions:
            flash('No questions available for this exam!', 'danger')
            return redirect(url_for('add_questions', exam_id=exam_id))
            
        students = Student.query.filter_by(exam_id=exam_id).all()
        exam = Exam.query.get(exam_id)
        exam.is_started = True

        question_texts = [q.question_text for q in exam_questions]
        num_students = len(students)

        distributed_questions = distribute_questions(num_students, question_texts)
        for student, question in zip(students, distributed_questions):
            student.set_question(question)
              
        db.session.commit()
        flash(f'Exam "{exam.name}" started and questions allocated to {len(students)} students!', 'success')
        return redirect(url_for('exam_details', exam_id=exam_id))
        
    exams = Exam.query.all()
    return render_template('start_exam.html', exams=exams)  

@app.route('/student_exam/<int:student_id>', methods=['GET', 'POST'])
def student_exam(student_id):
    student = Student.query.get_or_404(student_id)
    exam = Exam.query.get_or_404(student.exam_id)

    if student.submitted_file:
        flash('You have already submitted your answer. Further edits are not allowed.', 'warning')
        return redirect(url_for('register'))
    if exam.is_ended:
        flash('The exam has ended.', 'danger')
        return redirect(url_for('register'))
    
    question = Question.query.filter_by(exam_id=exam.id, question_text=student.get_question()).first()
    question_id = question.question_number if question else 0

    if request.method == 'POST':
        uploaded_file = request.files.get('answer_file')
        if uploaded_file and uploaded_file.filename != '':
            upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(exam.id), student.registration_number)
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, uploaded_file.filename)
            uploaded_file.save(file_path)

            student.submitted_file = file_path
            db.session.commit()

            flash('Answer submitted successfully! You cannot make further changes.', 'success')
            return redirect(url_for('register'))
        else:
            flash('Please upload a valid file!', 'danger')

    questions = student.get_question()
    return render_template('student_exam.html', student=student, exam=exam, questions=questions, question_id=question_id)

@app.route('/exam/start', methods=['POST'])
def start_exam_student():
    data = request.get_json()
    student_id = data.get('student_id')
    exam_id = data.get('exam_id')
    exam = Exam.query.get_or_404(exam_id)
    if exam.is_ended:
        return jsonify({'error': 'The exam has ended.'}), 400
    session = ExamSession.query.filter_by(student_id=student_id, exam_id=exam_id).first()

    if session:
        elapsed_time = (datetime.now() - session.start_time).total_seconds()
        remaining_time = max(0, session.duration - elapsed_time)
    else:
        exam = Exam.query.get(exam_id)
        duration = int(exam.duration * 60 * 60)
        session = ExamSession(
            student_id=student_id,
            exam_id=exam_id,
            start_time=datetime.now(),
            duration=duration
        )
        db.session.add(session)
        db.session.commit()
        remaining_time = duration

    return jsonify({'remaining_time': remaining_time})

@app.route('/preview_answer/<path:file_path>')
def preview_answer(file_path):
    try:
        if os.path.isabs(file_path):
            abort(400, "Invalid file path")

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'Uploads'))
        full_path = os.path.join(base_dir, file_path)

        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            abort(404)

        if request.args.get('download') == 'true':
            return send_file(full_path, as_attachment=True)

        text_extensions = ['.txt', '.py', '.html', '.css', '.js', '.json', '.md']
        _, ext = os.path.splitext(full_path)
        if ext.lower() in text_extensions:
            with open(full_path, 'r') as f:
                content = f.read()
            return content, 200, {'Content-Type': 'text/plain'}

        return "Preview not supported for this file type.", 400

    except (ValueError, TypeError):
        abort(404)

@app.route('/exam/<int:exam_id>', methods=['GET'])
def exam_details(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    students = Student.query.filter_by(exam_id=exam_id).all()

    student_data = []
    for student in students:
        allocated_question = student.allocated_questions
        submission_status = bool(student.submitted_file)
        submitted_file = os.path.relpath(student.submitted_file, app.config['UPLOAD_FOLDER']) if student.submitted_file else None

        student_data.append({
            'registration_number': student.registration_number,
            'ip_address': student.ip_address,
            'allocated_question': allocated_question,
            'is_submitted': submission_status,
            'submitted_file': submitted_file
        })

    return render_template('exam_details.html', exam=exam, students=student_data)

@app.route('/exam/<int:exam_id>/<string:student_reg>/<int:question_id>/<string:submitted_status>')
def student_question(exam_id, student_reg, question_id, submitted_status):
    exam = Exam.query.get_or_404(exam_id)
    student = Student.query.filter_by(registration_number=student_reg, exam_id=exam_id).first_or_404()
    question = Question.query.filter_by(exam_id=exam_id, question_number=question_id).first_or_404()

    if exam.is_ended:
        return jsonify({'error': 'The exam has ended.'}), 400

    if student.submitted_file and submitted_status.lower() == 'not_submitted':
        return jsonify({'error': 'Submission status mismatch. Answer already submitted.'}), 400

    if not student.submitted_file and submitted_status.lower() == 'submitted':
        return jsonify({'error': 'Submission status mismatch. No answer submitted.'}), 400

    return jsonify({
        'exam_id': exam_id,
        'exam_name': exam.name,
        'student_reg': student_reg,
        'question_id': question_id,
        'question_text': question.question_text,
        'submitted_status': submitted_status.lower()
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)