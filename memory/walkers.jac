import from memory.graph { User, Subject, Relates }

# Get-or-create a User node under the global root.
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

# Write a pre-deduplicated batch of Subject nodes under a User node.
# Each subject dict has: name, summary, description_delta, subject_type, recent_events.
# bridge.py merges intra-batch duplicates before calling this walker.
# Reports {jid, name, is_new, recent_events} for each subject processed.
walker IngestSubjects {
    has subjects: list;
    has relations: list;
    has now: str;

    can write with User entry {
        for s in self.subjects {
            tname: str = str(s["name"]);
            tsummary: str = str(s["summary"]);
            tdelta: str = str(s["description_delta"]);
            ttype: str = str(s["subject_type"]);
            tevents: list = list(s["recent_events"]);

            existing = [-->][?:Subject, name==tname];
            if existing {
                sub = existing[0];
                sub.recent_events = sub.recent_events + tevents;
                sub.updated_at = self.now;
                report {
                    "jid": jid(sub),
                    "name": tname,
                    "is_new": False,
                    "recent_events": sub.recent_events
                };
            } else {
                new_sub = here ++> Subject(
                    name=tname,
                    summary=tsummary,
                    description=tdelta,
                    subject_type=ttype,
                    created_at=self.now,
                    updated_at=self.now
                );
                report {
                    "jid": jid(new_sub[0]),
                    "name": tname,
                    "is_new": True,
                    "recent_events": []
                };
            }
        }

        for r in self.relations {
            rsrc: str = str(r["source"]);
            rtgt: str = str(r["target"]);
            rkind: str = str(r["kind"]);

            src_nodes = [-->][?:Subject, name==rsrc];
            tgt_nodes = [-->][?:Subject, name==rtgt];
            if src_nodes {
                if tgt_nodes {
                    src_nodes[0] +>: Relates(
                        kind=rkind,
                        weight=1.0,
                        created_at=self.now,
                        updated_at=self.now
                    ) :+> tgt_nodes[0];
                }
            }
        }
    }
}

# Reload subjects from SQLite into the Jac graph on startup or cache miss.
# Skips subjects that are already present (idempotent).
walker LoadSubjects {
    has subjects: list;

    can load with User entry {
        for s in self.subjects {
            tname: str = str(s["name"]);
            tsummary: str = str(s["summary"]);
            tdesc: str = str(s["description"]);
            ttype: str = str(s["subject_type"]);
            tevents: list = list(s["recent_events"]);
            tcreated: str = str(s["created_at"]);
            tupdated: str = str(s["updated_at"]);

            existing = [-->][?:Subject, name==tname];
            if existing {
                # already in graph — skip
            } else {
                here ++> Subject(
                    name=tname,
                    summary=tsummary,
                    description=tdesc,
                    subject_type=ttype,
                    created_at=tcreated,
                    updated_at=tupdated,
                    recent_events=tevents
                );
            }
        }
    }
}

# Retrieve subjects — naive fallback (before Phase 4 read path).
walker RetrieveSubjects {
    has max_subjects: int = 10;

    can collect with User entry {
        subjects = [-->][?:Subject];
        count: int = 0;
        for sub in subjects {
            if count >= self.max_subjects {
                disengage;
            }
            report {"name": sub.name, "summary": sub.summary, "jid": jid(sub)};
            count = count + 1;
        }
    }
}

# GraphRAG: expand from seed jids via 1-hop Subject graph traversal.
walker RetrieveBySubjectJids {
    has seed_jids: list;

    can expand with User entry {
        for sub in [-->][?:Subject] {
            if jid(sub) in self.seed_jids {
                report {
                    "name": sub.name,
                    "summary": sub.summary,
                    "description": sub.description,
                    "jid": jid(sub)
                };
                for neighbor in [sub-->][?:Subject] {
                    report {
                        "name": neighbor.name,
                        "summary": neighbor.summary,
                        "description": neighbor.description,
                        "jid": jid(neighbor)
                    };
                }
            }
        }
    }
}
# Retrieve full graph topology for the UI.
walker RetrieveFullGraph {
    can collect with User entry {
        subjects = [-->][?:Subject];
        for sub in subjects {
            report {
                "jid": jid(sub),
                "name": sub.name,
                "summary": sub.summary,
                "description": sub.description,
                "subject_type": sub.subject_type
            };
        }
    }
}

# Update a specific Subject node by JID.
walker UpdateSubject {
    has jid: str;
    has data: dict;
    has now: str;

    can update with User entry {
        subjects = [-->][?:Subject];
        for sub in subjects {
            if jid(sub) == self.jid {
                sub.name = self.data["name"];
                sub.summary = self.data["summary"];
                sub.description = self.data["description"];
                sub.subject_type = self.data["subject_type"];
                sub.updated_at = self.now;
                report {"status": "success"};
                disengage;
            }
        }
        report {"status": "error", "message": "Subject not found"};
    }
}

# Delete a specific Subject node by JID.
walker DeleteSubject {
    has jid: str;

    can delete with User entry {
        subjects = [-->][?:Subject];
        for sub in subjects {
            if jid(sub) == self.jid {
                del sub;
                report {"status": "success"};
                disengage;
            }
        }
        report {"status": "error", "message": "Subject not found"};
    }
}

# Retrieve full context for a subject: its data + 1-hop outbound neighbors.
walker GetSubjectContext {
    has name: str;

    can collect with User entry {
        tname: str = str(self.name);
        subjects = [-->][?:Subject];
        for sub in subjects {
            if sub.name == tname {
                neighbors: list = [];
                for nbr in [sub-->][?:Subject] {
                    neighbors.append({
                        "name": nbr.name,
                        "summary": nbr.summary,
                        "subject_type": nbr.subject_type
                    });
                }
                report {
                    "jid": jid(sub),
                    "name": sub.name,
                    "summary": sub.summary,
                    "description": sub.description,
                    "subject_type": sub.subject_type,
                    "recent_events": sub.recent_events,
                    "neighbors": neighbors
                };
                disengage;
            }
        }
    }
}

# Clear the recent_events WAL for a subject and write new summary/description.
walker ClearSubjectWAL {
    has name: str;
    has new_summary: str;
    has new_description: str;
    has now: str;

    can update with User entry {
        tname: str = str(self.name);
        subjects = [-->][?:Subject];
        for sub in subjects {
            if sub.name == tname {
                sub.summary = self.new_summary;
                sub.description = self.new_description;
                sub.recent_events = [];
                sub.updated_at = self.now;
                report {"status": "success", "jid": jid(sub)};
                disengage;
            }
        }
        report {"status": "not_found"};
    }
}

# Delete a specific Relates edge by source name, kind, and target name.
# keep_kinds: edge kinds between src->tgt that should survive (the rest are deleted).
# Strategy: delete all src->tgt edges then re-add the surviving kinds.
walker DeleteRelates {
    has source_name: str;
    has kind: str;
    has target_name: str;
    has keep_kinds: list;
    has now: str;

    can delete with User entry {
        rsrc: str = str(self.source_name);
        rtgt: str = str(self.target_name);
        src_nodes = [-->][?:Subject, name==rsrc];
        tgt_nodes = [-->][?:Subject, name==rtgt];
        if src_nodes {
            if tgt_nodes {
                src = src_nodes[0];
                tgt = tgt_nodes[0];
                src del --> tgt;
                for k in self.keep_kinds {
                    src +>: Relates(
                        kind=str(k),
                        weight=1.0,
                        created_at=self.now,
                        updated_at=self.now
                    ) :+> tgt;
                }
                report {"status": "success"};
                disengage;
            }
        }
        report {"status": "not_found"};
    }
}
