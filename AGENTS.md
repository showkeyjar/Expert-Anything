# AGENTS.md

# Project: Personal Learning OS

## Vision
Build an AI-powered personal learning system.

The system transforms books, papers, documents and courses into interactive,
adaptive learning experiences.

It is not an AI reader.
It is a Knowledge Runtime that helps users understand, practice, evaluate and improve.

## MVP User Case

User uploads a book (EPUB/PDF).

System:
1. Extracts knowledge structure
2. Builds a knowledge model
3. Creates an interactive learning agent
4. Generates multimodal explanations

Outputs:
- Text explanations
- Knowledge graphs
- Diagrams
- Images
- Animations
- Examples
- Exercises
- Assessments

## Core Principle

Optimize for:
"Does the user learn?"

Not:
"Can the AI answer?"

## Architecture

User
 |
Personal Learning Agent
 |
+ Knowledge Engine
+ Learner Model
+ Experience Engine
 |
Interactive Learning Experience

## Modules

### Knowledge Ingestion
Convert EPUB/PDF/Markdown/Web documents into structured knowledge.

Extract:
- Concepts
- Relations
- Examples
- Frameworks
- References

### Knowledge Graph
Represent concepts and dependencies.

### Learning Agent
Functions:
- Explain
- Question
- Practice
- Evaluate

### Multimodal Experience
Generate:
- Mermaid diagrams
- SVG
- Images
- Animations
- Simulations

### Learner Model
Track:
- Knowledge mastery
- Learning history
- Weak areas
- Skill growth

### Agent Roles

Librarian Agent:
Parse and organize knowledge

Teacher Agent:
Explain concepts

Visualization Agent:
Create visual learning materials

Coach Agent:
Design learning paths

Reviewer Agent:
Evaluate understanding

## Roadmap

Phase 1:
Interactive Book Prototype

- Upload EPUB/PDF
- Extract knowledge
- Generate knowledge map
- Chat with book
- Generate diagrams and questions

Phase 2:
Learning System

- User model
- Progress tracking
- Personalized learning

Phase 3:
Personal Learning OS

- Multiple knowledge sources
- Long-term memory
- Personal knowledge graph

## Engineering Rules

- Modular architecture
- Data model first
- Clear agent responsibilities
- Preserve source attribution
- Do not build a simple RAG chatbot

## Long Term Vision

Books become knowledge seeds.
AI becomes learning companion.
Humans become continuous learners.
