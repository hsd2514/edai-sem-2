# models.py
from datetime import datetime
from app import db_sql

class LdrReading(db_sql.Model):
    __tablename__ = 'ldr_readings'
    
    id = db_sql.Column(db_sql.Integer, primary_key=True)
    timestamp = db_sql.Column(db_sql.DateTime, nullable=False, default=datetime.utcnow)
    ldr_id = db_sql.Column(db_sql.Integer, nullable=False)
    value = db_sql.Column(db_sql.Integer, nullable=False)
    status = db_sql.Column(db_sql.String(20), nullable=False)
    is_flickering = db_sql.Column(db_sql.Boolean, default=False)

    def __repr__(self):
        return f'<LdrReading {self.ldr_id}: {self.value} at {self.timestamp}>'

# data_manager.py
import csv
from datetime import datetime, timedelta
from models import LdrReading

def store_reading(ldr_id, value, status, is_flickering):
    reading = LdrReading(
        ldr_id=ldr_id,
        value=value,
        status=status,
        is_flickering=is_flickering
    )
    db_sql.session.add(reading)
    db_sql.session.commit()

def get_readings(ldr_id, hours=24):
    since = datetime.utcnow() - timedelta(hours=hours)
    return LdrReading.query.filter(
        LdrReading.ldr_id == ldr_id,
        LdrReading.timestamp >= since
    ).order_by(LdrReading.timestamp.desc()).all()

def export_to_csv(ldr_id, filename):
    readings = get_readings(ldr_id)
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Timestamp', 'Value', 'Status', 'Flickering'])
        for reading in readings:
            writer.writerow([
                reading.timestamp,
                reading.value,
                reading.status,
                reading.is_flickering
            ])

# Update app.py route
@app.route('/update')
@login_required
def update():
    ref = db.reference('/')
    data = ref.get()
    
    for ldr_id in [1, 2]:
        value = data.get(f'ldr{ldr_id}', 0)
        status = get_status(value)
        is_flickering = check_flickering(
            ldr1_history if ldr_id == 1 else ldr2_history
        )
        
        store_reading(ldr_id, value, status, is_flickering)
    
    return jsonify(data)