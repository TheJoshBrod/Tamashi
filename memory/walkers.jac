import from memory.graph { User, Fact, Topic, RelatesTo, Mentions }

# Get-or-create a User node under the global root.
# In library mode there is one global root(), so we scope all data
# under User child nodes keyed by user_id.
walker GetOrCreateUser {
    has user_id: str;

    can find with Root entry {
        for u in [-->][?:User] {
            if u.user_id == self.user_id {
                report u;
                disengage;
            }
        }
        new_user = here ++> User(user_id=self.user_id);
        report new_user[0];
    }
}

# Write a batch of Fact nodes under a User node.
# Reports jid() of each created Fact for Qdrant mirroring (Phase 3).
walker IngestFacts {
    has facts: list[dict];

    can write with User entry {
        for f in self.facts {
            new_fact = here ++> Fact(
                content=f["content"],
                topic=f["topic"],
                source_msg_id=f["source_msg_id"]
            );
            topic_label = f["topic"];
            existing = [-->][?:Topic, label == topic_label];
            if existing {
                new_fact[0] ++> existing[0];
            } else {
                new_topic = here ++> Topic(label=topic_label);
                new_fact[0] ++> new_topic[0];
            }
            report jid(new_fact[0]);
        }
    }
}

# Retrieve facts for a user — naive most-recent-first (Phase 2 fallback).
walker RetrieveFacts {
    has max_facts: int = 10;

    can collect with User entry {
        facts = [-->][?:Fact];
        count: int = 0;
        for f in facts {
            if count >= self.max_facts {
                disengage;
            }
            report {"content": f.content, "topic": f.topic, "jid": jid(f)};
            count = count + 1;
        }
    }
}

# Phase 3: GraphRAG — expand from seed jids via 1-hop graph traversal.
# seed_jids is a list of jid values (compared directly — no str() cast needed).
# Python bridge handles deduplication of reported facts.
walker RetrieveByJids {
    has seed_jids: list;

    can expand with User entry {
        for f in [-->][?:Fact] {
            if jid(f) in self.seed_jids {
                report {"content": f.content, "topic": f.topic, "jid": jid(f)};
                for neighbor in [f-->][?:Fact] {
                    report {"content": neighbor.content, "topic": neighbor.topic, "jid": jid(neighbor)};
                }
            }
        }
    }
}

# Phase 3: Draw RelatesTo(kind="similar") edges between Facts found by vector search.
# target_jids: list of {jid, weight} dicts from Qdrant nearest-neighbor search.
walker LinkFacts {
    has src_jid: str;
    has target_jids: list;

    can link with User entry {
        for f in [-->][?:Fact] {
            if jid(f) == self.src_jid {
                for t in [-->][?:Fact] {
                    for target in self.target_jids {
                        if jid(t) == target["jid"] {
                            f +>: RelatesTo(kind="similar", weight=float(target["weight"])) :+> t;
                        }
                    }
                }
            }
        }
    }
}
