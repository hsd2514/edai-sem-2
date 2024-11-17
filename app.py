# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta, date
from sqlalchemy import func
import sqlite3
import os
import pdfkit
from collections import deque
import csv
import msvcrt
import logging
from contextlib import contextmanager
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db_sql = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Add configuration for pdfkit
config = pdfkit.configuration(wkhtmltopdf='C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe')

# User Model
class User(UserMixin, db_sql.Model):
    id = db_sql.Column(db_sql.Integer, primary_key=True)
    username = db_sql.Column(db_sql.String(80), unique=True, nullable=False)
    password = db_sql.Column(db_sql.String(120), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Firebase initialization (your existing code)
cred = credentials.Certificate("F:\edai sem 2\edai-sem-2-firebase-adminsdk-rdy9g-66ab85d999.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://edai-sem-2-default-rtdb.asia-southeast1.firebasedatabase.app/'
})

# Store last minute of readings
ldr1_history = deque(maxlen=12)  # 12 readings = 1 minute at 5s intervals
ldr2_history = deque(maxlen=12)
last_flicker_alert = {'ldr1': None, 'ldr2': None}

# Initialize history tracking
ldr_history = {
    1: deque(maxlen=12),  # Store last minute (12 readings at 5s intervals)
    2: deque(maxlen=12)
}

def check_flickering(ldr_id):
    try:
        history = ldr_history[ldr_id]
        if len(history) < 6:
            return False
            
        # Check last 6 readings (30 seconds)
        recent = list(history)[-12:]
        changes = 0
        for i in range(len(recent)-1):
            if abs(int(recent[i]) - int(recent[i+1])) > 200:
                changes += 1
                
        is_flickering = changes >= 3
        logger.debug(f"LDR{ldr_id} flickering check: {changes} changes, result: {is_flickering}")
        return is_flickering
        
    except Exception as e:
        logger.error(f"Flickering check error: {e}")
        return False

# CSV Functions
CSV_FILE = 'ldr_readings.csv'

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['timestamp', 'ldr_id', 'value', 'status', 'is_flickering'])

@contextmanager
def file_lock(filename):
    file = open(filename, 'a')
    try:
        while True:
            try:
                # Try to acquire lock
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except IOError:
                pass
        yield file
    finally:
        # Release lock
        try:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            file.close()

# Global variables for tracking
last_update = {}  # Track last update time per LDR
alert_conditions = {
    'OFF': 'danger',
    'DIM': 'warning',
    'FLICKERING': 'danger'
}

# Update save_reading function
def save_reading(ldr_id, value):
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        status = get_status(value)
        ldr_history[ldr_id].append(value)
        is_flickering = check_flickering(ldr_id)
        
        # Immediate write to CSV
        with open(CSV_FILE, 'a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                timestamp,
                ldr_id,
                value,
                status,
                is_flickering
            ])
            file.flush()  # Force write to disk
            
        logger.debug(f"CSV write at {timestamp} - LDR{ldr_id}: {value}")
            
    except Exception as e:
        logger.error(f"Save error: {e}")

def get_last_reading(ldr_id):
    try:
        with open(CSV_FILE, 'r') as file:
            reader = list(csv.DictReader(file))
            if reader:
                # Filter for specific LDR and sort by timestamp
                ldr_readings = [r for r in reader if int(r['ldr_id']) == ldr_id]
                if ldr_readings:
                    return sorted(ldr_readings, key=lambda x: x['timestamp'])[-1]
    except Exception as e:
        logger.error(f"Error getting last reading: {e}")
    return None

def get_readings():
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, 'r') as file:
        reader = csv.DictReader(file)
        return list(reader)

# Initialize CSV file
init_csv()

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(request.form['password'])
        new_user = User(username=request.form['username'], password=hashed_password)
        db_sql.session.add(new_user)
        db_sql.session.commit()
        flash('Registration successful')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    ref = db.reference('/')
    data = ref.get() or {}
    return render_template('dashboard.html', data=data)

@app.route('/ldr/<int:ldr_id>')
@login_required
def ldr_detail(ldr_id):
    try:
        ref = db.reference('/')
        data = ref.get()
        value = data.get(f'ldr{ldr_id}', 0)
        status = get_status(value)
        status_class = 'success' if status == 'ON' else 'danger' if status == 'OFF' else 'warning'
        
        return render_template('ldr.html',
                             ldr_id=ldr_id,
                             value=value,
                             status=status,
                             status_class=status_class,
                             current_time=datetime.now())  # Pass datetime object
    except Exception as e:
        logger.error(f"LDR detail error: {e}")
        return redirect(url_for('dashboard'))

def get_ldr_status(value):
    if value < 500:
        return 'OFF', 'bg-danger'
    elif value > 1000:
        return 'ON', 'bg-success'
    return 'DIM', 'bg-warning'

@app.route('/generate_report')
@login_required
def generate_report():
    # Get end of day data
    ref = db.reference('/')
    data = ref.get()
    return render_template('report.html', data=data)

# Update update route in app.py
@app.route('/update')
def update():
    try:
        ref = db.reference('/')
        data = ref.get()
        
        if not data:
            return jsonify({'error': 'No data'}), 500
            
        # Process each LDR value immediately 
        response_data = {}
        for ldr_id in [1, 2]:
            value = data.get(f'ldr{ldr_id}', 0)
            save_reading(ldr_id, value)
            response_data[f'ldr{ldr_id}'] = value
            
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Update error: {e}")
        return jsonify({'error': str(e)}), 500

def get_status(value):
    if value < 500:
        return 'OFF'
    elif value > 1000:
        return 'ON'
    return 'DIM'

# Add route for CSV download
@app.route('/download/<int:ldr_id>')
@login_required
def download_csv(ldr_id):
    filename = f'ldr{ldr_id}_readings.csv'
    export_to_csv(ldr_id, filename)
    return send_file(
        filename,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

# app.py - Update reports route
@app.route('/reports')
@login_required
def reports():
    # Get filter parameters with defaults
    today = datetime.now()
    start_date = request.args.get('start_date', default=today.strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', default=today.strftime('%Y-%m-%d'))
    ldr_id = request.args.get('ldr_id', type=int)
    status = request.args.get('status')

    # Read and filter CSV data
    readings = []
    try:
        with open(CSV_FILE, 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # Convert string timestamp to datetime
                row_datetime = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
                row_date = row_datetime.strftime('%Y-%m-%d')
                
                if (row_date >= start_date and row_date <= end_date and
                    (not ldr_id or int(row['ldr_id']) == ldr_id) and
                    (not status or row['status'] == status)):
                    readings.append({
                        'timestamp': row_datetime,
                        'ldr_id': int(row['ldr_id']),
                        'value': int(row['value']),
                        'status': row['status'],
                        'is_flickering': row['is_flickering'] == 'True'
                    })
    except FileNotFoundError:
        readings = []

    # Calculate statistics
    stats = calculate_stats(readings)

    return render_template('reports.html',
                         readings=readings,
                         stats=stats,
                         start_date=start_date,
                         end_date=end_date)

# Add to app.py - Updated calculate_stats function
def calculate_stats(readings):
    try:
        status_times = {'ON': 0, 'OFF': 0, 'DIM': 0}
        flicker_count = 0
        
        for reading in readings:
            status = reading['status']
            status_times[status] += 5/3600  # Convert 5 seconds to hours
            
            # Handle is_flickering as string or bool
            is_flickering = reading.get('is_flickering')
            if isinstance(is_flickering, str):
                is_flickering = is_flickering.lower() == 'true'
            elif isinstance(is_flickering, bool):
                is_flickering = bool(is_flickering)
                
            if is_flickering:
                flicker_count += 1
        
        def format_time(hours):
            total_minutes = int(hours * 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            return f"{hours}h {minutes}m"
        
        return {
            'on_time': format_time(status_times['ON']),
            'off_time': format_time(status_times['OFF']),
            'dim_time': format_time(status_times['DIM']),
            'flicker_count': flicker_count,
            'total_readings': len(readings)
        }
    except Exception as e:
        logger.error(f"Stats calculation error: {e}")
        return {
            'on_time': '0h 0m',
            'off_time': '0h 0m',
            'dim_time': '0h 0m',
            'flicker_count': 0,
            'total_readings': 0
        }

# Add JavaScript for auto-updating

# app.py - Add export route
@app.route('/export-report')
@login_required
def export_report():
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    ldr_id = request.args.get('ldr_id', type=int)
    
    # Read and filter data
    readings = []
    with open(CSV_FILE, 'r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            reading_date = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
            if ((not start_date or reading_date >= start_date) and 
                (not end_date or reading_date <= end_date) and
                (not ldr_id or int(row['ldr_id']) == ldr_id)):
                readings.append(row)
    
    # Create export file
    export_file = 'ldr_report.csv'
    with open(export_file, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Timestamp', 'LDR', 'Value', 'Status', 'Flickering'])
        for reading in readings:
            writer.writerow([
                reading['timestamp'],
                reading['ldr_id'],
                reading['value'],
                reading['status'],
                reading['is_flickering']
            ])
    
    return send_file(
        export_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ldr_report_{datetime.now().strftime("%Y%m%d")}.csv'
    )

# app.py - Add new route for AJAX updates
@app.route('/report-updates')
def report_updates():
    try:
        readings = []
        with open(CSV_FILE, 'r') as file:
            reader = csv.DictReader(file)
            readings = list(reader)
            
        # Sort by timestamp, newest first
        readings.sort(key=lambda x: x['timestamp'], reverse=True)
        
        stats = calculate_stats(readings)
        
        return jsonify({
            'readings': readings[:100],  # Limit to last 100 entries
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Report update error: {e}")
        return jsonify({'error': str(e)}), 500

# Create tables
with app.app_context():
    db_sql.create_all()

# Add to app.py - State management
flickering_status = {
    1: False,
    2: False
}

def update_flickering_status(ldr_id, value):
    global flickering_status
    # Add to history
    ldr_history[ldr_id].append(value)
    # Update status
    flickering_status[ldr_id] = check_flickering(ldr_id)
    return flickering_status[ldr_id]

# Email Configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "harsh.dange23@vit.edu"
SMTP_PASSWORD = "mayq ezhx dqmw rwwz"  # Generate from Google Account settings
RECIPIENT_EMAIL = "harhdange25@gmail.com"



def send_report_email(date_str, pdf_path):
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = f"Light Monitoring Report - {date_str}"

        # Add HTML body
        html = f"""
        <html>
            <body>
                <h2>Light Monitoring Daily Report</h2>
                <p>Date: {date_str}</p>
                <p>Please find attached the daily monitoring report.</p>
            </body>
        </html>
        """
        msg.attach(MIMEText(html, 'html'))

        # Attach PDF
        with open(pdf_path, 'rb') as f:
            pdf = MIMEApplication(f.read(), _subtype='pdf')
            pdf.add_header('Content-Disposition', 'attachment', 
                         filename=f'report_{date_str}.pdf')
            msg.attach(pdf)

        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
            logger.info(f"Email sent successfully for {date_str}")
            return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

@app.route('/send-daily-report', methods=['POST'])
@login_required
def send_daily_report():
    try:
        date_str = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        pdf_file = generate_pdf_report(date_str)
        
        if pdf_file and send_report_email(date_str, pdf_file):
            flash('Report sent successfully!', 'success')
        else:
            flash('Failed to send report', 'danger')
            
        return redirect(url_for('debug'))
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        flash('Error generating report', 'danger')
        return redirect(url_for('debug'))

def generate_pdf_report(date_str=None):
    try:
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
            
        # Get readings
        readings = []
        with open(CSV_FILE, 'r') as file:
            reader = csv.DictReader(file)
            readings = [r for r in reader if r['timestamp'].startswith(date_str)]
        
        # Calculate stats
        ldr_stats = calculate_ldr_stats(readings)
        
        # Generate HTML
        html_content = create_report_html(date_str, ldr_stats, readings)
        
        # Create PDF using config
        pdf_path = os.path.join(os.path.dirname(CSV_FILE), f"report_{date_str}.pdf")
        pdfkit.from_string(html_content, pdf_path, configuration=config)
        logger.info(f"Report generated: {pdf_path}")
        
        return pdf_path
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return None

def calculate_ldr_stats(readings):
    ldr_stats = {}
    for ldr_id in [1, 2]:
        ldr_readings = [r for r in readings if int(r['ldr_id']) == ldr_id]
        
        # Count statuses
        status_counts = {
            'ON': sum(1 for r in ldr_readings if r['status'] == 'ON'),
            'OFF': sum(1 for r in ldr_readings if r['status'] == 'OFF'),
            'DIM': sum(1 for r in ldr_readings if r['status'] == 'DIM')
        }
        
        # Calculate time in hours and minutes (5 seconds per reading)
        def format_time(count):
            total_seconds = count * 5  # 5 seconds per reading
            hours = total_seconds // 3600  # 3600 seconds = 1 hour
            minutes = (total_seconds % 3600) // 60
            # Validate hours don't exceed 24
            if hours > 24:
                hours = hours % 24
            return f"{hours}h {minutes}m"
        
        ldr_stats[ldr_id] = {
            'total_readings': len(ldr_readings),
            'on_time': format_time(status_counts['ON']),
            'off_time': format_time(status_counts['OFF']),
            'dim_time': format_time(status_counts['DIM']),
            'flicker_events': sum(1 for r in ldr_readings if r['is_flickering'].lower() == 'true')
        }
    
    return ldr_stats

# Update create_report_html function
def create_report_html(date_str, ldr_stats, readings):
    # Get only last 10 readings
    recent_readings = readings[-10:]
    
    # Prepare chart data
    ldr1_data = [r['value'] for r in readings if r['ldr_id'] == '1']
    ldr2_data = [r['value'] for r in readings if r['ldr_id'] == '2']
    timestamps = [r['timestamp'].split()[1] for r in readings]  # Only time part
    
    chart_js = f"""
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    new Chart(document.getElementById('statusChart'), {{
        type: 'line',
        data: {{
            labels: {timestamps},
            datasets: [
                {{
                    label: 'LDR 1',
                    data: {ldr1_data},
                    borderColor: 'rgb(75, 192, 192)'
                }},
                {{
                    label: 'LDR 2',
                    data: {ldr2_data},
                    borderColor: 'rgb(153, 102, 255)'
                }}
            ]
        }}
    }});
    </script>
    """
    
    return f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial; padding: 20px; max-width: 1200px; margin: 0 auto; }}
            .header {{ text-align: center; padding: 20px; background: #f8f9fa; margin-bottom: 30px; }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-bottom: 30px; }}
            .stat-card {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .chart-container {{ margin: 30px 0; height: 400px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th {{ background: #f8f9fa; }}
            th, td {{ padding: 12px; border: 1px solid #dee2e6; text-align: left; }}
            .badge {{ padding: 5px 10px; border-radius: 4px; color: white; }}
            .badge-success {{ background: #28a745; }}
            .badge-danger {{ background: #dc3545; }}
            .badge-warning {{ background: #ffc107; color: black; }}
        </style>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
        <div class="header">
            <h1>Light Monitoring Report</h1>
            <p>Date: {date_str}</p>
        </div>
        
        <div class="stats-grid">
            {generate_stat_cards(ldr_stats)}
        </div>
        
        <div class="chart-container">
            <canvas id="statusChart"></canvas>
        </div>
        
        <h2>Recent Readings</h2>
        <table>
            <tr>
                <th>Time</th>
                <th>LDR</th>
                <th>Value</th>
                <th>Status</th>
            </tr>
            {generate_table_rows(recent_readings)}
        </table>
        
        {chart_js}
    </body>
    </html>
    """

def generate_stat_cards(ldr_stats):
    return ''.join([f"""
        <div class="stat-card">
            <h3>LDR {ldr_id}</h3>
            <p>ON Time: {stats['on_time']}</p>
            <p>OFF Time: {stats['off_time']}</p>
            <p>DIM Time: {stats['dim_time']}</p>
            <p>Flicker Events: {stats['flicker_events']}</p>
        </div>
    """ for ldr_id, stats in ldr_stats.items()])

def generate_table_rows(readings):
    return ''.join([f"""
        <tr>
            <td>{r['timestamp']}</td>
            <td>LDR {r['ldr_id']}</td>
            <td>{r['value']}</td>
            <td><span class="badge badge-{get_status_class(r['status'])}">{r['status']}</span></td>
        </tr>
    """ for r in readings])

def get_status_class(status):
    return {
        'ON': 'success',
        'OFF': 'danger',
        'DIM': 'warning'
    }.get(status, 'secondary')

# Update email configuration
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'username': 'your-email@gmail.com',
    'password': 'your-app-password',  # Generate from Google Account settings
    'recipient': 'recipient@email.com'
}

def send_email_report(pdf_path, date_str):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['username']
        msg['To'] = EMAIL_CONFIG['recipient']
        msg['Subject'] = f"Light Monitoring Report - {date_str}"
        
        body = f"Please find attached the light monitoring report for {date_str}"
        msg.attach(MIMEText(body, 'plain'))
        
        with open(pdf_path, 'rb') as f:
            attachment = MIMEApplication(f.read(), _subtype='pdf')
            attachment.add_header('Content-Disposition', 'attachment', 
                                filename=os.path.basename(pdf_path))
            msg.attach(attachment)
        
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['username'], EMAIL_CONFIG['password'])
            server.send_message(msg)
            
        logger.info(f"Email sent successfully for {date_str}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

# Add to app.py
@app.route('/debug', methods=['GET'])
@login_required
def debug():
    return render_template('debug.html',datetime=datetime)

def send_email_report(pdf_path, date_str):
    try:
        msg = MIMEMultipart()
        
        # Get email config from environment or use defaults securely
        smtp_config = {
            'server': 'smtp.gmail.com',
            'port': 587,
            'username': os.getenv('EMAIL_USERNAME', 'your-email@gmail.com'),
            'password': os.getenv('EMAIL_PASSWORD', 'your-app-password'),
            'recipient': os.getenv('EMAIL_RECIPIENT', 'recipient@email.com')
        }

        msg['From'] = smtp_config['username']
        msg['To'] = smtp_config['recipient']
        msg['Subject'] = f"Light Monitoring Report - {date_str}"

        # Add body
        body = f"Light Monitoring Report for {date_str} is attached."
        msg.attach(MIMEText(body, 'plain'))

        # Attach PDF
        if os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                pdf = MIMEApplication(f.read(), _subtype='pdf')
                pdf.add_header('Content-Disposition', 'attachment', 
                             filename=os.path.basename(pdf_path))
                msg.attach(pdf)
        else:
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Send email
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            server.starttls()
            server.login(smtp_config['username'], smtp_config['password'])
            server.send_message(msg)
            logger.info(f"Email sent successfully for {date_str}")
            return True

    except Exception as e:
        logger.error(f"Email sending failed: {str(e)}")
        return False

# Update send_report route
@app.route('/send-report', methods=['GET', 'POST'])
@login_required
def send_report():
    try:
        date_str = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        pdf_path = generate_pdf_report(date_str)
        
        if pdf_path and send_email_report(pdf_path, date_str):
            flash('Report generated and sent successfully!', 'success')
        else:
            flash('Error sending report', 'danger')
            
        return redirect(url_for('debug'))
        
    except Exception as e:
        logger.error(f"Report generation failed: {str(e)}")
        flash('Error generating report', 'danger')
        return redirect(url_for('debug'))

# Add to app.py
def send_email_report(pdf_path, date_str):
    try:
        msg = MIMEMultipart()
        msg['From'] = "harsh.dange23@vit.edu"
        msg['To'] = "harshdange25@gmail.com"
        msg['Subject'] = f"Light Monitoring Report - {date_str}"
        
        # Add email body
        body = f"""
        Light Monitoring System Report
        Date: {date_str}
        
        Please find the detailed report attached.
        
        This is an automated email from your Light Monitoring System.
        """
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach PDF
        with open(pdf_path, 'rb') as f:
            pdf = MIMEApplication(f.read(), _subtype='pdf')
            pdf.add_header('Content-Disposition', 'attachment', 
                         filename=f'light_report_{date_str}.pdf')
            msg.attach(pdf)
        
        # Send email using the provided credentials
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login("harsh.dange23@vit.edu", "mayq ezhx dqmw rwwz")
            server.send_message(msg)
            
        logger.info(f"Report email sent successfully for {date_str}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False



# app.py
@app.route('/get-current-location')
def get_current_location():
    try:
        ref = db.reference('/')
        data = ref.get()
        
        return jsonify({
            'lat': data.get('latitude', 18.4636),  # Default coords if none found
            'lng': data.get('longitude', 73.8682),
            'ldr1': data.get('ldr1', 0)
        })
    except Exception as e:
        logger.error(f"Location fetch error: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    with app.app_context():
        db_sql.create_all()
    app.run(debug=True, port=5000)