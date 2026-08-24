# Natural Language Action Agent

A local LLM-powered service that converts natural-language smart-facility requests into structured actions, validates them against a known device/metric registry, and executes supported actions against a deterministic mock backend.

The project is designed to run completely locally using Ollama and Llama 3.2, so no paid LLM API is required.

---

## 1. Problem Statement

Smart-facility systems expose structured operations such as:

- creating alert rules
- querying device status
- listing existing alert rules

However, users naturally describe these requests in plain language.

For example:

> "Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes."

The system needs to understand the request, convert it into a structured action, validate the referenced device and metric, and then execute the action safely.

This project implements that pipeline using a local LLM, Pydantic models, a validation layer, and a mock in-memory backend.

---

## 2. Objective

The objective is to build a small natural-language action agent that can:

1. Understand a user's natural-language request.
2. Identify the intended operation.
3. Extract the relevant parameters.
4. Convert the request into a typed action.
5. Validate devices and metrics against a known registry.
6. Reject unsupported or invalid requests safely.
7. Execute supported actions against deterministic mock data.
8. Expose the functionality through a FastAPI HTTP API.

---

## 3. Architecture

```text
                     User
                      |
                      v
              +---------------+
              |    FastAPI    |
              |  /command     |
              |  /rules       |
              +-------+-------+
                      |
                      v
              +---------------+
              | Intent Router |
              +-------+-------+
                      |
                      v
              +---------------+
              | Ollama /      |
              | Llama 3.2     |
              +-------+-------+
                      |
                      v
              +---------------+
              | Pydantic      |
              | Action Models  |
              +-------+-------+
                      |
                      v
              +---------------+
              |   Validator   |
              +-------+-------+
                      |
             +--------+--------+
             |                 |
             v                 v
       Valid Action       Invalid Action
             |                 |
             v                 v
       +-----------+       HTTP 422
       | Executor  |
       +-----+-----+
             |
             v
       In-memory Store
       / Mock Sensors