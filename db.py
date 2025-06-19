import sqlite3


def initialize():
    db = sqlite3.connect("spo.db")
    db.execute(
        "CREATE TABLE playlists (id INTEGER PRIMARY KEY, name TEXT, public BOOLEAN, url TEXT)"
    )
    db.commit()
    db.close()
