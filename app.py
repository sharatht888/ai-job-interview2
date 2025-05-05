from flask import Flask, render_template, request, redirect, url_for, session, send_file
from PyPDF2 import PdfReader
from xhtml2pdf import pisa
from io import BytesIO
import os
import config
import pyodbc

app = Flask(__name__)
app.secret_key = config.SECRET_KEY  # Replace with a strong, random key

app.jinja_env.globals.update(zip=zip)

# --- Database Connection ---
def get_db_connection():
    connection_string = f"""
        DRIVER={config.DB_DRIVER};
        SERVER={config.DB_SERVER};
        DATABASE={config.DB_NAME};
        UID={config.DB_USER};
        PWD={config.DB_PASSWORD};
        Encrypt=yes;
        TrustServerCertificate=no;
        Connection Timeout=30;
    """
    return pyodbc.connect(connection_string)

# --- Routes ---
@app.route('/')
def home():
    return redirect(url_for('signup'))  # Show signup page first

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, password))
            conn.commit()
        except pyodbc.IntegrityError:
            conn.close()
            return "User already exists!"
        conn.close()
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, password))
        user = cursor.fetchone()
        conn.close()
        if user:
            session['user'] = email
            return redirect(url_for('upload_resume_form'))
        else:
            return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/upload_resume_form')
def upload_resume_form():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('upload_resume.html')

@app.route('/upload_resume', methods=['POST'])
def upload_resume():
    if 'resume' not in request.files:
        return "No file uploaded.", 400

    resume_file = request.files['resume']
    if resume_file.filename == '':
        return "No selected file.", 400

    try:
        pdf_reader = PdfReader(resume_file)
        resume_text = ""
        for page in pdf_reader.pages:
            resume_text += page.extract_text()

        skills = ['Python', 'JavaScript', 'HTML', 'CSS', 'Machine Learning', 'SQL', 'Java']
        skills_found = [skill for skill in skills if skill.lower() in resume_text.lower()]
        score = int(len(skills_found) / len(skills) * 100)
        feedback = f"Skills matched: {', '.join(skills_found)}"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE results SET resume_score = ?, skills_found = ? WHERE id = (SELECT TOP 1 id FROM results WHERE user_email = ? ORDER BY id DESC)", (score, ', '.join(skills_found), session['user']))
        conn.commit()
        conn.close()

        return redirect(url_for('start_interview'))

    except Exception as e:
        return f"Error processing resume: {e}", 500

@app.route('/start_interview')
def start_interview():
    if 'user' not in session:
        return redirect(url_for('login'))
    questions = [
        "Tell me about a project you built using Python.",
        "What is the difference between HTML and CSS?",
        "Can you explain how Machine Learning works?",
        "What are the key concepts of JavaScript?",
        "How do you optimize a website’s performance?"
    ]
    return render_template("start_interview.html", questions=questions)

@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    if 'user' not in session:
        return redirect(url_for('login'))
    feedbacks = []
    questions = [
        "Tell me about a project you built using Python.",
        "What is the difference between HTML and CSS?",
        "Can you explain how Machine Learning works?",
        "What are the key concepts of JavaScript?",
        "How do you optimize a website’s performance?"
    ]
    keywords = [
        ['project', 'python', 'developed', 'code'],
        ['html', 'css', 'style', 'structure'],
        ['data', 'algorithm', 'model', 'training'],
        ['variables', 'functions', 'DOM', 'events'],
        ['optimize', 'load', 'speed', 'cache']
    ]
    for i in range(len(questions)):
        answer = request.form.get(f'answer{i+2}', '').lower()
        key_hits = sum(1 for word in keywords[i] if word in answer)
        if key_hits >= 3:
            fb = "Good answer! You covered the key points."
        elif key_hits == 2:
            fb = "Fair answer. You touched on some important topics."
        else:
            fb = "Needs improvement. Try to be more specific."
        feedbacks.append((questions[i], answer, fb))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO results (user_email, resume_score, skills_found, answers, feedback) VALUES (?, ?, ?, ?, ?)",
        (session['user'], 0, '', '|'.join([item[1] for item in feedbacks]), '|'.join([item[2] for item in feedbacks]))
    )
    conn.commit()
    conn.close()

    return render_template("interview_feedback.html", feedbacks=feedbacks)

@app.route('/results')
def results():
    if 'user' not in session:
        return redirect(url_for('login'))
    email = session['user']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT resume_score, skills_found, answers, feedback FROM results WHERE user_email = ? ORDER BY id DESC", (email,))
    rows = cursor.fetchall()
    rows.reverse()
    conn.close()
    data = []
    for row in rows:
        resume_score = row[0]
        skills_found = row[1]
        answers = row[2].split('|')
        feedback = row[3].split('|')
        data.append({
            'resume_score': resume_score,
            'skills_found': skills_found,
            'answers': answers,
            'feedback': feedback
        })
    print(f"Data: {data}")
    return render_template('results.html', data=data)

@app.route('/download_report')
def download_report():
    if 'user' not in session:
        return redirect(url_for('login'))
    email = session['user']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TOP 1 resume_score, skills_found, answers, feedback FROM results WHERE user_email = ? ORDER BY id DESC", (email,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return "No interview result found."
    resume_score, skills_found, answers, feedback = result
    answers = answers.split('|')
    feedback = feedback.split('|')

    html = render_template("pdf_template.html", resume_score=resume_score,
                           skills_found=skills_found, answers=answers, feedback=feedback)
    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf)
    if pisa_status.err:
        return "PDF generation failed"
    pdf.seek(0)
    return send_file(pdf, download_name="interview_report.pdf", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
