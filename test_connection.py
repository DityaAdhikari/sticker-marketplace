import pymysql

try:
    conn = pymysql.connect(
        host="127.0.0.1",
        user="root",
        password="",
        database="stickernest",
        port=3307
    )

    print("✅ Connected successfully!")
    print(conn.get_server_info())

    conn.close()

except Exception as e:
    print("❌ Error:")
    print(e)