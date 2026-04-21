node User {
    has user_id: str;
}

node Subject {
    has name: str;
    has summary: str;
    has description: str;
    has subject_type: str;
    has created_at: str;
    has updated_at: str;
}

edge Relates {
    has kind: str;
    has created_at: str;
    has updated_at: str;
    has weight: float = 1.0;
}
