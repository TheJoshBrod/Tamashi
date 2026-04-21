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
# Each subject dict has: name, summary, description_delta, subject_type.
# bridge.py merges intra-batch duplicates before calling this walker.
# Reports {jid, name, is_new} for each subject processed.
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

            existing = [-->][?:Subject, name==tname];
            if existing {
                sub = existing[0];
                sub.updated_at = self.now;
                report {
                    "jid": jid(sub),
                    "name": tname,
                    "is_new": False
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
                    "is_new": True
                };
            }
        }

        for r in self.relations {
            rsrc: str = str(r["source"]);
            rtgt: str = str(r["target"]);
            rkind: str = str(r["kind"]);
            rweight: float = float(r["weight"]);

            src_nodes = [-->][?:Subject, name==rsrc];
            tgt_nodes = [-->][?:Subject, name==rtgt];
            if src_nodes {
                if tgt_nodes {
                    src = src_nodes[0];
                    tgt = tgt_nodes[0];
                    tgt_jid: str = jid(tgt);
                    connected = [src ->:Relates:kind==rkind:->];
                    already_exists: bool = False;
                    for n in connected {
                        if jid(n) == tgt_jid {
                            already_exists = True;
                        }
                    }
                    if not already_exists {
                        src +>: Relates(
                            kind=rkind,
                            weight=rweight,
                            created_at=self.now,
                            updated_at=self.now
                        ) :+> tgt;
                    }
                }
            }
        }
    }
}

# Reload subjects + relations from SQLite into the Jac graph on startup or
# cache miss. Skips subjects/edges that are already present (idempotent).
walker LoadSubjects {
    has subjects: list;
    has relations: list;

    can load with User entry {
        for s in self.subjects {
            tname: str = str(s["name"]);
            tsummary: str = str(s["summary"]);
            tdesc: str = str(s["description"]);
            ttype: str = str(s["subject_type"]);
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
                    updated_at=tupdated
                );
            }
        }

        for r in self.relations {
            rsrc: str = str(r["src_name"]);
            rtgt: str = str(r["tgt_name"]);
            rkind: str = str(r["kind"]);
            rweight: float = float(r["weight"]);
            rcreated: str = str(r["created_at"]);
            rupdated: str = str(r["updated_at"]);

            src_nodes = [-->][?:Subject, name==rsrc];
            tgt_nodes = [-->][?:Subject, name==rtgt];
            if src_nodes {
                if tgt_nodes {
                    src = src_nodes[0];
                    tgt = tgt_nodes[0];
                    tgt_jid: str = jid(tgt);
                    connected = [src ->:Relates:kind==rkind:->];
                    already_exists: bool = False;
                    for n in connected {
                        if jid(n) == tgt_jid {
                            already_exists = True;
                        }
                    }
                    if not already_exists {
                        src +>: Relates(
                            kind=rkind,
                            weight=rweight,
                            created_at=rcreated,
                            updated_at=rupdated
                        ) :+> tgt;
                    }
                }
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

# Retrieve full context for a subject: its data + 1-hop inbound and outbound neighbors.
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
                        "subject_type": nbr.subject_type,
                        "direction": "outbound"
                    });
                }
                for nbr in [sub<--][?:Subject] {
                    neighbors.append({
                        "name": nbr.name,
                        "summary": nbr.summary,
                        "subject_type": nbr.subject_type,
                        "direction": "inbound"
                    });
                }
                report {
                    "jid": jid(sub),
                    "name": sub.name,
                    "summary": sub.summary,
                    "description": sub.description,
                    "subject_type": sub.subject_type,
                    "neighbors": neighbors
                };
                disengage;
            }
        }
    }
}

# Write new summary/description for a subject after a rewrite.
# WAL consumption happens in SQLite (bridge → subject_store.delete_events_by_ids).
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
                sub.updated_at = self.now;
                report {"status": "success", "jid": jid(sub)};
                disengage;
            }
        }
        report {"status": "not_found"};
    }
}

# Delete a specific Relates edge by source name, kind, and target name.
# keep_edges: [{kind, weight}] for edges between src->tgt that should survive.
# Strategy: delete all src->tgt edges then re-add the surviving ones with their weights.
walker DeleteRelates {
    has source_name: str;
    has kind: str;
    has target_name: str;
    has keep_edges: list;
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
                for e in self.keep_edges {
                    src +>: Relates(
                        kind=str(e["kind"]),
                        weight=float(e["weight"]),
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
