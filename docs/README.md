# Tamashi Documentation

Welcome to the technical documentation for Tamashi. This guide is split into several specialized documents to help you understand, configure, and extend the system. Treat this as a wiki to quickly look up how things work on a systems level, how to configure the tool, and how to extend it.  

### [Configuration](configuration.md)
How to change the model, set per-subagent models, and configure environment variables.

### [Implementation Details](implementation.md)
A deep dive into the core architecture of Tamashi. This covers the event-driven system, the `EmotionManager` policy layer, and how the system guarantees smooth UI transitions through minimum hold times.

### [Messaging Interfaces](interfaces.md)
Instructions on how to connect Tamashi to the outside world. This includes detailed setup for Twilio WhatsApp and instructions on how to implement new communication channels like Discord or Slack.

### [Extending Tamashi](extending_tamashi.md)
A practical guide for adding new capabilities. Learn how to register global tools, create specialized subagents, and build custom emotional UI states for new features.

### [Display & Dashboard](display.md)
The web dashboard at `/display/`. Covers the emotion avatar UI and the memory graph editor — how to navigate, create/edit subjects and relations, and the REST API backing the graph view.

### [Memory Architecture](memory.md)
How the hybrid dual-store memory system works: FIFO working buffer, Jac graph long-term store, Qdrant vector index, GraphRAG retrieval, and the continuous event-driven Subject Rewriter agent.

---
[← Back to Project Home](../README.md)
