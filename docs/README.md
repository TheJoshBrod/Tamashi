# Tamashi Documentation

Welcome to the technical documentation for Tamashi. This guide is split into several specialized documents to help you understand, configure, and extend the system.

### [Configuration](configuration.md)
How to change the model, set per-subagent models, and configure environment variables.

### [Implementation Details](implementation.md)
A deep dive into the core architecture of Tamashi. This covers the event-driven system, the `EmotionManager` policy layer, and how the system guarantees smooth UI transitions through minimum hold times.

### [Messaging Interfaces](interfaces.md)
Instructions on how to connect Tamashi to the outside world. This includes detailed setup for Twilio WhatsApp and instructions on how to implement new communication channels like Discord or Slack.

### [Extending Tamashi](extending_tamashi.md)
A practical guide for adding new capabilities. Learn how to register global tools, create specialized subagents, and build custom emotional UI states for new features.

---
[← Back to Project Home](../README.md)
