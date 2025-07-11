import random
import re
import os
import smtplib
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_session import Session
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key")

# MySQL Configuration
app.config["MYSQL_HOST"] = os.getenv("MYSQL_HOST")
app.config["MYSQL_USER"] = os.getenv("MYSQL_USER")
app.config["MYSQL_PASSWORD"] = os.getenv("MYSQL_PASSWORD")
app.config["MYSQL_DB"] = os.getenv("MYSQL_DB")
app.config["MYSQL_PORT"] = int(os.getenv("MYSQL_PORT", 3306))

# Email Configuration
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# MySQL connection function
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=app.config["MYSQL_HOST"],
            user=app.config["MYSQL_USER"],
            password=app.config["MYSQL_PASSWORD"],
            database=app.config["MYSQL_DB"],
            port=app.config["MYSQL_PORT"]
        )
        return conn
    except Exception as e:
        print("Error connecting to DB:", e)
        return None

@app.route("/")
def index():
    search_query = request.args.get("search", "").strip().lower()
    conn = get_db_connection()
    if conn is None:
        flash("Database connection failed!", "error")
        return render_template("index.html", agencies=[])

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM agencies")
    agencies = cursor.fetchall()

    if search_query:
        agencies = [
            agency for agency in agencies
            if search_query in agency["agencies_name"].lower() or
               search_query in agency["city"].lower() or
               search_query in agency["country"].lower()
        ]

    for agency in agencies:
        cursor.execute("SELECT * FROM packages WHERE registration_id = %s", (agency["registration_id"],))
        agency["packages"] = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template("index.html", agencies=agencies)

@app.route("/enter_email")
def enter_email():
    return render_template("email.html")

def is_valid_email(email):
    regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
    return re.match(regex, email)

def send_otp(email):
    if not is_valid_email(email):
        return False
    otp = str(random.randint(100000, 999999))
    session["otp"] = otp
    session["otp_expiry"] = (datetime.now() + timedelta(minutes=5)).timestamp()
    session["email"] = email

    subject = "Your OTP for Umrah Tour Login"
    message = f"Subject: {subject}\n\nYour OTP is: {otp} (Valid for 5 minutes)"

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, email, message)
        return True
    except smtplib.SMTPException:
        return False

@app.route("/send_otp", methods=["POST"])
def send_otp_route():
    email = request.form.get("email")
    if not email or not is_valid_email(email):
        flash("Invalid email!", "error")
        return redirect(url_for("enter_email"))
    if send_otp(email):
        return render_template("otp.html")
    else:
        flash("Failed to send OTP. Try again!", "error")
        return redirect(url_for("enter_email"))

@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    entered_otp = request.form.get("otp")
    stored_otp = session.get("otp")
    otp_expiry = session.get("otp_expiry")
    email = session.get("email")

    if not stored_otp or not otp_expiry or datetime.now().timestamp() > otp_expiry:
        flash("OTP expired! Please request a new one.", "error")
        return redirect(url_for("enter_email"))

    if entered_otp.strip() == stored_otp.strip():
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (email) VALUES (%s) ON DUPLICATE KEY UPDATE email=email", (email,))
            conn.commit()
            cursor.execute("SELECT first_name, last_name, personal_email FROM users WHERE email = %s", (email,))
            user_details = cursor.fetchone()
            cursor.close()
            conn.close()

            session["logged_in"] = True
            if user_details and all(user_details):
                return redirect(url_for("business_dashboard"))
            else:
                return redirect(url_for("user_details"))
        except Exception as e:
            flash(f"Database error: {str(e)}", "error")
            return redirect(url_for("enter_email"))
    else:
        flash("Invalid OTP! Try again.", "error")
        return render_template("otp.html")

@app.route("/user_details", methods=["GET", "POST"])
def user_details():
    if not session.get("logged_in"):
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("enter_email"))

    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        personal_email = request.form.get("personal_email")
        email = session.get("email")

        if not first_name or not last_name or not personal_email:
            flash("All fields are required!", "error")
            return render_template("details.html")

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET first_name=%s, last_name=%s, personal_email=%s WHERE email=%s
            """, (first_name, last_name, personal_email, email))
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for("business_dashboard"))
        except Exception as e:
            flash(f"Database error: {str(e)}", "error")
            return render_template("details.html")

    return render_template("details.html")

@app.route('/business_dashboard')
def business_dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("enter_email"))

    email = session.get("email")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    if not user:
        flash("User not found!", "error")
        return redirect(url_for("enter_email"))

    user_id = user["id"]
    cursor.execute("SELECT * FROM agencies WHERE user_id = %s", (user_id,))
    agencies = cursor.fetchall()
    for agency in agencies:
        cursor.execute("SELECT * FROM packages WHERE registration_id = %s", (agency["registration_id"],))
        agency["packages"] = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template("business_dashboard.html", agencies=agencies)

@app.route("/delete_agency/<int:registration_id>")
def delete_agency(registration_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM packages WHERE registration_id = %s", (registration_id,))
        cursor.execute("DELETE FROM agencies WHERE registration_id = %s", (registration_id,))
        conn.commit()
        flash("Agency deleted successfully!", "success")
    except Exception as e:
        flash(f"Error deleting agency: {e}", "error")
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for("business_dashboard"))

@app.route("/delete_package/<int:package_id>")
def delete_package(package_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM packages WHERE package_id = %s", (package_id,))
        conn.commit()
        flash("Package deleted successfully!", "success")
    except Exception as e:
        flash(f"Error deleting package: {e}", "error")
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for("business_dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/add_agency", methods=["GET"])
def add_agency_page():
    if not session.get("logged_in"):
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("enter_email"))
    return render_template("add_agency.html")

@app.route("/save_agency", methods=["POST"])
def save_agency():
    if not session.get("logged_in"):
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("enter_email"))

    email = session.get("email")
    agencies_name = request.form.get("agency_name")
    country = request.form.get("country")
    city = request.form.get("city")
    description = request.form.get("description")

    if not agencies_name or not country or not city:
        flash("All fields are required!", "error")
        return redirect(url_for("add_agency_page"))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user:
            flash("User not found in the database.", "error")
            return redirect(url_for("enter_email"))
        user_id = user[0]
        cursor.execute("""
            INSERT INTO agencies (user_id, agencies_name, country, city, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, agencies_name, country, city, description))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Agency added successfully!", "success")
        return redirect(url_for("business_dashboard"))
    except Exception as e:
        flash(f"Error adding agency: {e}", "error")
        return redirect(url_for("add_agency_page"))

if __name__ == "__main__":
    port = 5050
    app.run(host="0.0.0.0", port=port, debug=True)
