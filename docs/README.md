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

### [Display & Dashboard](display/README.md)
The web dashboard interfaces. Contains documentation for the Emotion Dashboard avatar UI, the Memory Graph cartography editor, and the topology testing scripts.

### [Memory Architecture](memory/README.md)
How the hybrid dual-store memory system works. Covers the Jac graph topology schemas, the consolidation and async memory maintainer workflows, and the vector-seeded GraphRAG retrieval pipelines.

---
[← Back to Project Home](../README.md)
