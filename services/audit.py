def log(conn, table, record_id, action, old=None, new=None, user_id=None):
    """Write one audit row: who did what, to which record, and when."""
    conn.execute(
        "INSERT INTO audit_log (table_name, record_id, action, old_value, new_value, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (table, record_id, action,
         None if old is None else str(old),
         None if new is None else str(new),
         user_id),
    )