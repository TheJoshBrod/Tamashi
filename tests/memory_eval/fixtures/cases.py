"""Hand-authored eval fixtures for Phase 2 baseline.

Two separate lists with deliberately different schemas — retrieval measures
whether the read path surfaces the right Subjects, extractor measures whether
the write path produces the right Subjects + relations.

Retrieval fixture:
    {
        "id": str,
        "description": str,
        "seeded_subjects": [{"name","summary","description_delta","subject_type"}, ...],
        "seeded_relations": [{"source","kind","target"}, ...],
        "query": str,
        "expected_top_k_names": [str, ...],   # names that MUST appear in top-k
        "forbidden_names": [str, ...],         # names that MUST NOT appear
        "k": int,                              # scoring cutoff
    }

Extractor fixture:
    {
        "id": str,
        "description": str,
        "messages": [{"role","content"}, ...],
        "vocabulary": [{"name","summary","subject_type"}, ...],
        "expected_subjects": [str, ...],       # names (case-insensitive match)
        "expected_relations": [(src, kind, tgt), ...],  # triples
        "is_negative": bool,                   # True → expect empty extraction
    }

Kinds are restricted to settings.allowed_relation_kinds:
    is_a, has_a, part_of, enjoys, avoids, wants, knows, located_in,
    works_at, causes, opposite_of, related_to, mentions
"""
from __future__ import annotations


RETRIEVAL_FIXTURES: list[dict] = [
    # --- single-subject lexical recall --------------------------------------
    {
        "id": "retr_lexical_match_pet",
        "description": "Exact name match surfaces the subject.",
        "seeded_subjects": [
            {"name": "Koda", "summary": "User's golden retriever", "description_delta": "Koda is a golden retriever", "subject_type": "object"},
            {"name": "Saturn", "summary": "The planet Saturn", "description_delta": "Saturn has rings", "subject_type": "concept"},
        ],
        "seeded_relations": [],
        "query": "Is Koda due for a vet visit?",
        "expected_top_k_names": ["Koda"],
        "forbidden_names": [],
        "k": 5,
    },
    # --- multi-subject with 1-hop expansion ---------------------------------
    {
        "id": "retr_graphrag_expand_owner_pet",
        "description": "Query about owner surfaces pet via has_a 1-hop edge.",
        "seeded_subjects": [
            {"name": "Alice", "summary": "Software engineer who owns a dog", "description_delta": "Alice owns Koda", "subject_type": "person"},
            {"name": "Koda", "summary": "Alice's golden retriever", "description_delta": "Koda is Alice's dog", "subject_type": "object"},
        ],
        "seeded_relations": [
            {"source": "Alice", "kind": "has_a", "target": "Koda"},
        ],
        "query": "Tell me about Alice",
        "expected_top_k_names": ["Alice", "Koda"],
        "forbidden_names": [],
        "k": 5,
    },
    # --- semantic (non-lexical) recall --------------------------------------
    {
        "id": "retr_semantic_pet_synonym",
        "description": "'dog' query should recall the pet Subject even though the name is 'Koda'.",
        "seeded_subjects": [
            {"name": "Koda", "summary": "User's pet dog, a golden retriever", "description_delta": "Koda is a dog", "subject_type": "object"},
            {"name": "Python", "summary": "Programming language user knows", "description_delta": "user writes python", "subject_type": "concept"},
        ],
        "seeded_relations": [],
        "query": "I'm looking for dog training tips",
        "expected_top_k_names": ["Koda"],
        "forbidden_names": ["Python"],
        "k": 5,
    },
    # --- preference recall --------------------------------------------------
    {
        "id": "retr_preference_food",
        "description": "Query about food should recall the pizza preference.",
        "seeded_subjects": [
            {"name": "Pizza", "summary": "User's favorite food, especially pepperoni", "description_delta": "user loves pizza", "subject_type": "concept"},
            {"name": "Seattle", "summary": "City where user lives", "description_delta": "user lives in Seattle", "subject_type": "place"},
        ],
        "seeded_relations": [],
        "query": "What should I order for dinner?",
        "expected_top_k_names": ["Pizza"],
        "forbidden_names": ["Seattle"],
        "k": 5,
    },
    # --- location recall ----------------------------------------------------
    {
        "id": "retr_location_recall",
        "description": "'where do I live' should surface the user's city.",
        "seeded_subjects": [
            {"name": "Seattle", "summary": "City where the user lives", "description_delta": "user lives in Seattle", "subject_type": "place"},
            {"name": "Pizza", "summary": "User's favorite food", "description_delta": "loves pizza", "subject_type": "concept"},
        ],
        "seeded_relations": [],
        "query": "Remind me what city I'm based in",
        "expected_top_k_names": ["Seattle"],
        "forbidden_names": [],
        "k": 5,
    },
    # --- goal recall --------------------------------------------------------
    {
        "id": "retr_goal_recall",
        "description": "Query about running should surface the marathon goal.",
        "seeded_subjects": [
            {"name": "Marathon Training", "summary": "User is training for a marathon in six months", "description_delta": "training for marathon", "subject_type": "goal"},
            {"name": "Guitar", "summary": "User plays acoustic guitar", "description_delta": "plays guitar", "subject_type": "object"},
        ],
        "seeded_relations": [],
        "query": "How far should I run this week?",
        "expected_top_k_names": ["Marathon Training"],
        "forbidden_names": ["Guitar"],
        "k": 5,
    },
    # --- bidirectional traversal (2-hop via inbound) ------------------------
    #   Currently Phase 1 graph is 1-hop outbound only; this fixture baselines
    #   the "miss" so Phase 3's bidirectional flip shows a measurable delta.
    {
        "id": "retr_inbound_neighbor_baseline",
        "description": "Inbound-only seed: Phase 3 bidirectional should lift recall here.",
        "seeded_subjects": [
            {"name": "ACME Corp", "summary": "User's employer", "description_delta": "company", "subject_type": "place"},
            {"name": "Alice", "summary": "User's name", "description_delta": "works at ACME", "subject_type": "person"},
        ],
        "seeded_relations": [
            {"source": "Alice", "kind": "works_at", "target": "ACME Corp"},
        ],
        "query": "What's happening at ACME this week?",
        "expected_top_k_names": ["ACME Corp", "Alice"],
        "forbidden_names": [],
        "k": 5,
    },
    # --- multi-hop chain ----------------------------------------------------
    {
        "id": "retr_chain_person_pet_vet",
        "description": "Seed Alice, expand to Koda; vet is 2-hop away (out of scope today).",
        "seeded_subjects": [
            {"name": "Alice", "summary": "Golden retriever owner", "description_delta": "owns Koda", "subject_type": "person"},
            {"name": "Koda", "summary": "Alice's dog", "description_delta": "golden retriever", "subject_type": "object"},
            {"name": "Dr. Stevens", "summary": "The family vet", "description_delta": "vet", "subject_type": "person"},
        ],
        "seeded_relations": [
            {"source": "Alice", "kind": "has_a", "target": "Koda"},
            {"source": "Koda", "kind": "knows", "target": "Dr. Stevens"},
        ],
        "query": "Tell me about Alice",
        "expected_top_k_names": ["Alice", "Koda"],
        "forbidden_names": [],
        "k": 5,
    },
    # --- negative: off-topic query should not surface seeded subjects -------
    {
        "id": "retr_negative_off_topic",
        "description": "Off-topic query: forbidden names should stay below top-k.",
        "seeded_subjects": [
            {"name": "Koda", "summary": "A pet dog", "description_delta": "dog", "subject_type": "object"},
        ],
        "seeded_relations": [],
        "query": "What's the capital of France?",
        "expected_top_k_names": [],
        "forbidden_names": [],  # only one subject seeded; cannot strictly forbid it given cosine floor
        "k": 5,
    },
    # --- disambiguation: two subjects, query picks the right one -----------
    {
        "id": "retr_disambiguate_two_people",
        "description": "Two Alices present; role-specific query should prefer the right one.",
        "seeded_subjects": [
            {"name": "Alice Johnson", "summary": "User's sister who lives in Boston", "description_delta": "sister in Boston", "subject_type": "person"},
            {"name": "Alice Chen", "summary": "User's coworker at ACME", "description_delta": "coworker", "subject_type": "person"},
        ],
        "seeded_relations": [],
        "query": "Remind me about my coworker",
        "expected_top_k_names": ["Alice Chen"],
        "forbidden_names": [],
        "k": 5,
    },
]


EXTRACTOR_FIXTURES: list[dict] = [
    # --- single subject -----------------------------------------------------
    {
        "id": "extr_single_subject_pet",
        "description": "One new subject: the user's dog.",
        "messages": [
            {"role": "user", "content": "My golden retriever Koda turned three today."},
        ],
        "vocabulary": [],
        "expected_subjects": ["Koda"],
        "expected_relations": [],
        "is_negative": False,
    },
    # --- multi-subject + relation ------------------------------------------
    {
        "id": "extr_multi_subject_relation",
        "description": "Owner + pet + has_a relation.",
        "messages": [
            {"role": "user", "content": "Hi, I'm Alice. My dog Koda is a golden retriever."},
        ],
        "vocabulary": [],
        "expected_subjects": ["Alice", "Koda"],
        "expected_relations": [("Alice", "has_a", "Koda")],
        "is_negative": False,
    },
    # --- preference --------------------------------------------------------
    {
        "id": "extr_preference_enjoys",
        "description": "Preference should yield an enjoys relation when the user is represented.",
        "messages": [
            {"role": "user", "content": "I love pepperoni pizza — it's my favorite food."},
        ],
        "vocabulary": [
            {"name": "User", "summary": "The speaker", "subject_type": "person"},
        ],
        "expected_subjects": ["Pizza"],
        "expected_relations": [],  # relation target name style varies; don't over-specify
        "is_negative": False,
    },
    # --- location ----------------------------------------------------------
    {
        "id": "extr_location_located_in",
        "description": "Place extraction.",
        "messages": [
            {"role": "user", "content": "I just moved to Seattle last month."},
        ],
        "vocabulary": [],
        "expected_subjects": ["Seattle"],
        "expected_relations": [],
        "is_negative": False,
    },
    # --- goal --------------------------------------------------------------
    {
        "id": "extr_goal_subject",
        "description": "Durable goal extraction.",
        "messages": [
            {"role": "user", "content": "I'm training for the NYC Marathon next November."},
        ],
        "vocabulary": [],
        "expected_subjects": ["NYC Marathon"],
        "expected_relations": [],
        "is_negative": False,
    },
    # --- vocabulary reuse --------------------------------------------------
    {
        "id": "extr_vocabulary_reuse",
        "description": "Existing subject in vocab should NOT spawn a near-duplicate.",
        "messages": [
            {"role": "user", "content": "Koda had a great walk this morning."},
        ],
        "vocabulary": [
            {"name": "Koda", "summary": "User's golden retriever dog", "subject_type": "object"},
        ],
        "expected_subjects": ["Koda"],
        "expected_relations": [],
        "is_negative": False,
    },
    # --- employer ----------------------------------------------------------
    {
        "id": "extr_works_at",
        "description": "Person + employer + works_at relation.",
        "messages": [
            {"role": "user", "content": "I'm Alice and I work at ACME Corp as an engineer."},
        ],
        "vocabulary": [],
        "expected_subjects": ["Alice", "ACME Corp"],
        "expected_relations": [("Alice", "works_at", "ACME Corp")],
        "is_negative": False,
    },
    # --- multi-turn --------------------------------------------------------
    {
        "id": "extr_multiturn_pet_vet",
        "description": "Two turns surface pet + vet plus a knows/has_a edge.",
        "messages": [
            {"role": "user", "content": "My dog Koda has been limping."},
            {"role": "assistant", "content": "Have you seen a vet?"},
            {"role": "user", "content": "Yes, Dr. Stevens is our vet."},
        ],
        "vocabulary": [],
        "expected_subjects": ["Koda", "Dr. Stevens"],
        "expected_relations": [],  # (Koda, knows, Dr. Stevens) is plausible but not canonical
        "is_negative": False,
    },
    # --- negative: pure small talk -----------------------------------------
    {
        "id": "extr_negative_small_talk",
        "description": "Small talk produces no durable subjects.",
        "messages": [
            {"role": "user", "content": "Hey, how's it going?"},
            {"role": "assistant", "content": "Good, thanks!"},
            {"role": "user", "content": "Cool cool."},
        ],
        "vocabulary": [],
        "expected_subjects": [],
        "expected_relations": [],
        "is_negative": True,
    },
    # --- negative: weather, ephemeral --------------------------------------
    {
        "id": "extr_negative_ephemeral",
        "description": "Ephemeral weather comment — no durable memory.",
        "messages": [
            {"role": "user", "content": "It's raining outside right now."},
        ],
        "vocabulary": [],
        "expected_subjects": [],
        "expected_relations": [],
        "is_negative": True,
    },
]
