# data_store.py
import csv
from datetime import datetime
import os

CSV_FILE = 'ldr_readings.csv'

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['timestamp', 'ldr_id', 'value', 'status', 'is_flickering'])

def save_reading(ldr_id, value, status, is_flickering=False):
    with open(CSV_FILE, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ldr_id,
            value,
            status,
            is_flickering
        ])

def get_readings():
    readings = []
    with open(CSV_FILE, 'r') as file:
        reader = csv.DictReader(file)
        readings = list(reader)
    return readings

# Initialize CSV file
init_csv()