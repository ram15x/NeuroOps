import psycopg2

passwords_to_try = [
    "postgres",
    "postgre123", 
    "postgres123",
    "password",
    "admin",
    "root",
    "",
    "neuroops",
    "neuroops123"
]

for pwd in passwords_to_try:
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5433,
            user="postgres",
            password=pwd,
            database="postgres",
            connect_timeout=3
        )
        print(f"✅ SUCCESS! Password is: '{pwd}'")
        conn.close()
        break
    except Exception as e:
        print(f"❌ Failed with '{pwd}': {str(e)[:50]}")
