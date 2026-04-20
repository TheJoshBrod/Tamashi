## Retrieval Baseline (Phase 2)

| Fixture | P@k | R@k | MRR | Forbid |
| --- | --- | --- | --- | --- |
| retr_lexical_match_pet | 0.200 | 1.000 | 1.000 | 0.000 |
| retr_graphrag_expand_owner_pet | 0.400 | 1.000 | 0.750 | 0.000 |
| retr_semantic_pet_synonym | 0.200 | 1.000 | 1.000 | 1.000 |
| retr_preference_food | 0.200 | 1.000 | 1.000 | 1.000 |
| retr_location_recall | 0.200 | 1.000 | 1.000 | 0.000 |
| retr_goal_recall | 0.200 | 1.000 | 1.000 | 1.000 |
| retr_inbound_neighbor_baseline | 0.400 | 1.000 | 0.750 | 0.000 |
| retr_chain_person_pet_vet | 0.400 | 1.000 | 0.750 | 0.000 |
| retr_negative_off_topic | 0.000 | 1.000 | 1.000 | 0.000 |
| retr_disambiguate_two_people | 0.200 | 1.000 | 1.000 | 0.000 |

**Aggregate (macro):**
- precision_at_k: 0.240
- recall_at_k: 1.000
- mrr: 0.925
- forbidden_hit_rate: 0.300
- n_fixtures: 10