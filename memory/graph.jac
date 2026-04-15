node User {
    has user_id: str;
}

node Fact {
    has content: str;
    has topic: str;
    has source_msg_id: int;
}

node Topic {
    has label: str;
}

node Article {
    has title: str;
    has url: str;
    has snippet: str;
}

edge RelatesTo {
    has kind: str;
    has weight: float = 1.0;
}

edge Mentions { }
