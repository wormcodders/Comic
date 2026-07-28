import sqlite3

def add_episode_column():
    conn = sqlite3.connect('e:/Comic/instance/comics.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE comic ADD COLUMN episode VARCHAR(100)")
        print("Column 'episode' added successfully.")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("Column 'episode' already exists.")
        else:
            print(f"Error: {e}")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_episode_column()
