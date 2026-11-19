from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bincom_secret_key"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",          # Replace with your MySQL username
    "password": "1234",          # Replace with your MySQL password
    "database": "bincom_test"
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# --- API ENDPOINTS FOR CHAINED DROPDOWNS (LGA -> WARD -> POLLING UNIT) ---
@app.route("/api/wards/<int:lga_id>")
def get_wards(lga_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT ward_id, ward_name FROM ward WHERE lga_id = %s ORDER BY ward_name", (lga_id,))
    wards = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(wards)

@app.route("/api/polling_units/<int:ward_id>")
def get_polling_units(ward_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT uniqueid, polling_unit_number, polling_unit_name 
        FROM polling_unit 
        WHERE ward_id = %s AND polling_unit_name IS NOT NULL AND polling_unit_name != ''
        ORDER BY polling_unit_name
    """, (ward_id,))
    units = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(units)

# --- QUESTION 1: DISPLAY INDIVIDUAL POLLING UNIT RESULT ---
@app.route("/", methods=["GET", "POST"])
def index():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # State ID 25 = Delta State
    cursor.execute("SELECT lga_id, lga_name FROM lga WHERE state_id = 25 ORDER BY lga_name")
    lgas = cursor.fetchall()

    results = []
    selected_pu = None

    if request.method == "POST":
        pu_uniqueid = request.form.get("polling_unit_id")
        if pu_uniqueid:
            cursor.execute("SELECT * FROM polling_unit WHERE uniqueid = %s", (pu_uniqueid,))
            selected_pu = cursor.fetchone()

            cursor.execute("""
                SELECT party_abbreviation, party_score 
                FROM announced_pu_results 
                WHERE polling_unit_uniqueid = %s
            """, (pu_uniqueid,))
            results = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template("index.html", lgas=lgas, results=results, selected_pu=selected_pu)

# --- QUESTION 2: SUMMED TOTAL RESULT OF ALL POLLING UNITS UNDER AN LGA ---
@app.route("/lga-results", methods=["GET", "POST"])
def lga_results():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT lga_id, lga_name FROM lga WHERE state_id = 25 ORDER BY lga_name")
    lgas = cursor.fetchall()

    summed_results = []
    selected_lga = None

    if request.method == "POST":
        lga_id = request.form.get("lga_id")
        if lga_id:
            cursor.execute("SELECT lga_name FROM lga WHERE lga_id = %s", (lga_id,))
            selected_lga = cursor.fetchone()

            # Summed directly from announced_pu_results (NOT announced_lga_results)
            cursor.execute("""
                SELECT apr.party_abbreviation, SUM(apr.party_score) AS total_score
                FROM announced_pu_results apr
                JOIN polling_unit pu ON apr.polling_unit_uniqueid = pu.uniqueid
                WHERE pu.lga_id = %s
                GROUP BY apr.party_abbreviation
                ORDER BY total_score DESC
            """, (lga_id,))
            summed_results = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template("lga_results.html", lgas=lgas, summed_results=summed_results, selected_lga=selected_lga)

# --- QUESTION 3: STORE RESULTS FOR ALL PARTIES FOR A NEW POLLING UNIT ---
@app.route("/add-polling-unit", methods=["GET", "POST"])
def add_polling_unit():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT lga_id, lga_name FROM lga WHERE state_id = 25 ORDER BY lga_name")
    lgas = cursor.fetchall()

    # Fetch all parties dynamically from the party table
    cursor.execute("SELECT partyname FROM party ORDER BY partyname")
    parties = cursor.fetchall()

    if request.method == "POST":
        lga_id = request.form.get("lga_id")
        ward_id = request.form.get("ward_id")
        pu_number = request.form.get("pu_number")
        pu_name = request.form.get("pu_name")
        pu_description = request.form.get("pu_description", "")
        entered_by = request.form.get("entered_by", "Admin")
        date_entered = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_ip = request.remote_addr or "127.0.0.1"

        # 1. Insert new polling unit into polling_unit table
        cursor.execute("""
            INSERT INTO polling_unit 
            (polling_unit_id, ward_id, lga_id, uniquewardid, polling_unit_number, polling_unit_name, polling_unit_description, entered_by_user, date_entered, user_ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (0, ward_id, lga_id, ward_id, pu_number, pu_name, pu_description, entered_by, date_entered, user_ip))

        new_pu_uniqueid = cursor.lastrowid

        # 2. Insert scores for ALL parties into announced_pu_results
        for p in parties:
            party_abbr = p["partyname"][:4]  # Column limit is usually 4 chars
            score = request.form.get(f"score_{p['partyname']}", 0) or 0
            cursor.execute("""
                INSERT INTO announced_pu_results 
                (polling_unit_uniqueid, party_abbreviation, party_score, entered_by_user, date_entered, user_ip_address)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (str(new_pu_uniqueid), party_abbr, int(score), entered_by, date_entered, user_ip))

        conn.commit()
        flash(f"Successfully saved new polling unit '{pu_name}' (Unique ID: {new_pu_uniqueid}) with all party results!", "success")
        cursor.close()
        conn.close()
        return redirect(url_for("add_polling_unit"))

    cursor.close()
    conn.close()
    return render_template("add_pu.html", lgas=lgas, parties=parties)

if __name__ == "__main__":
    app.run(debug=True)