"""
AgentLens Demo — Simulated agent that populates the dashboard with realistic data.
No API keys needed! Just run this after starting the backend.

Usage:
    1. cd backend && pip install -r requirements.txt && uvicorn main:app --port 8340
    2. python examples/demo_agent.py
    3. Open http://localhost:8340/dashboard
"""

import sys
import os
import time
import random

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from agentlens import AgentLens, tool, step

# ─── Initialize AgentLens ────────────────────────────────────
lens = AgentLens(
    server_url="http://localhost:8340",
    project="default",
    api_key="al_default_key",
    verbose=True,
    flush_interval=1.0,
)

# ─── Simulated Tools ────────────────────────────────────────
@tool("web-search")
def search_web(query: str) -> dict:
    """Simulate a web search."""
    time.sleep(random.uniform(0.1, 0.5))
    results = [
        {"title": f"Result {i+1} for '{query}'", "url": f"https://example.com/{i}", "snippet": f"This is about {query}..."}
        for i in range(random.randint(3, 8))
    ]
    return {"results": results, "total": len(results)}

@tool("database-query")
def query_database(sql: str) -> list:
    """Simulate a database query."""
    time.sleep(random.uniform(0.05, 0.2))
    if "error" in sql.lower():
        raise Exception("SQL syntax error near 'error'")
    return [{"id": i, "value": random.randint(100, 999)} for i in range(random.randint(1, 5))]

@tool("send-email")
def send_email(to: str, subject: str, body: str) -> dict:
    """Simulate sending an email."""
    time.sleep(random.uniform(0.1, 0.3))
    return {"status": "sent", "message_id": f"msg_{random.randint(1000, 9999)}"}

@tool("calculator")
def calculate(expression: str) -> float:
    """Simulate a calculation."""
    time.sleep(0.05)
    return round(random.uniform(1, 1000), 2)

# ─── Simulated LLM Calls ────────────────────────────────────
MODELS = ["gpt-4o-mini", "gpt-4o", "claude-3.5-sonnet", "gpt-3.5-turbo"]

def simulate_llm_call(prompt: str, model: str = None):
    """Simulate an LLM call with realistic token counts and latency."""
    model = model or random.choice(MODELS)
    latency = random.uniform(200, 2000)
    time.sleep(latency / 1000)

    input_tokens = len(prompt.split()) * 2 + random.randint(50, 200)
    output_tokens = random.randint(50, 500)

    responses = [
        "Based on my analysis, the key factors are: market size, competition, and timing.",
        "I'll search for relevant information and compile a comprehensive report.",
        "The data suggests a 23% increase in efficiency when using the automated approach.",
        "I recommend proceeding with option B as it offers better cost-efficiency.",
        "Here's a summary of the findings: 1) Revenue up 15% 2) Costs down 8% 3) Customer satisfaction at 92%",
        "I need to gather more data before making a recommendation. Let me check the database.",
        "The analysis is complete. The optimal strategy involves three phases of implementation.",
    ]

    completion = random.choice(responses)

    lens.record_llm_call(
        model=model,
        prompt=prompt,
        completion=completion,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency,
        provider="openai" if "gpt" in model else "anthropic",
    )

    return completion

# ─── Agent Scenarios ─────────────────────────────────────────
@lens.monitor("research-agent", tags={"type": "research"})
def research_agent(topic: str):
    """Simulate a multi-step research agent."""

    # Step 1: Understand the query
    lens.record_step(1, thought=f"User wants to research: {topic}", decision="search_web")
    analysis = simulate_llm_call(f"Analyze this research request: {topic}")

    # Step 2: Search for information
    lens.record_step(2, thought="Need to gather data from the web", decision="web_search")
    results = search_web(topic)

    # Step 3: Analyze results
    lens.record_step(3, thought=f"Got {results['total']} results, analyzing...", decision="synthesize")
    synthesis = simulate_llm_call(f"Synthesize these search results about {topic}: {results}")

    # Step 4: Generate report
    lens.record_step(4, thought="Compiling final report", decision="generate_report")
    report = simulate_llm_call(f"Write a comprehensive report about {topic} based on: {synthesis}")

    return report


@lens.monitor("data-agent", tags={"type": "analytics"})
def data_analysis_agent(question: str):
    """Simulate a data analysis agent."""

    # Step 1: Parse question
    lens.record_step(1, thought=f"Understanding: {question}", decision="parse_query")
    parsed = simulate_llm_call(f"Convert this question to SQL: {question}")

    # Step 2: Query database
    lens.record_step(2, thought="Querying the database", decision="run_sql")
    try:
        data = query_database(f"SELECT * FROM metrics WHERE topic = '{question}'")
    except Exception as e:
        lens.record_error(e, context="Database query failed")
        data = []

    # Step 3: Calculate metrics
    lens.record_step(3, thought="Running calculations", decision="calculate")
    result = calculate(f"sum({[d['value'] for d in data]})")

    # Step 4: Generate insight
    lens.record_step(4, thought="Generating human-readable insight", decision="explain")
    insight = simulate_llm_call(f"Explain this data analysis result: {result} for question: {question}")

    return insight


@lens.monitor("email-agent", tags={"type": "communication"})
def email_agent(task: str):
    """Simulate an email drafting + sending agent."""

    # Step 1: Understand task
    lens.record_step(1, thought=f"Email task: {task}", decision="draft")
    draft = simulate_llm_call(f"Draft an email for: {task}")

    # Step 2: Review
    lens.record_step(2, thought="Reviewing draft for tone and accuracy", decision="review")
    review = simulate_llm_call(f"Review this email draft and improve: {draft}")

    # Step 3: Send
    lens.record_step(3, thought="Draft approved, sending", decision="send")
    result = send_email(
        to="team@company.com",
        subject=f"Re: {task[:30]}",
        body=review,
    )

    return result


@lens.monitor("failing-agent", tags={"type": "test"})
def failing_agent(task: str):
    """An agent that sometimes fails — to demonstrate error tracking."""

    lens.record_step(1, thought="This might fail...", decision="risky_operation")
    simulate_llm_call(f"Attempt: {task}", model="gpt-4o-mini")

    if random.random() < 0.6:
        # Force an error
        lens.record_step(2, thought="Something went wrong!", decision="error_recovery")
        try:
            query_database("SELECT error FROM bad_table")
        except Exception as e:
            lens.record_error(e, context="Database error in failing agent")

        raise Exception(f"Agent failed on task: {task}")

    lens.record_step(2, thought="Lucky! It worked.", decision="complete")
    return "Survived!"


# ─── Run Demo ────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  🔍 AgentLens Demo — Generating sample data")
    print("=" * 60)
    print()

    topics = [
        "AI agent market size 2026",
        "Best vector databases comparison",
        "How to price SaaS products",
        "RAG architecture best practices",
        "Competitor analysis for observability tools",
    ]

    questions = [
        "What's the average revenue per user this quarter?",
        "How many active agents ran last week?",
        "What's the error rate trend over 30 days?",
    ]

    email_tasks = [
        "Weekly status update to the team",
        "Follow up with client about POC deployment",
        "Onboarding instructions for new developer",
    ]

    # Run research agents
    print("🔬 Running research agents...")
    for topic in topics:
        try:
            research_agent(topic)
            print(f"  ✅ Research: {topic[:50]}")
        except Exception as e:
            print(f"  ❌ Research failed: {e}")
        time.sleep(0.5)

    # Run data agents
    print("\n📊 Running data analysis agents...")
    for q in questions:
        try:
            data_analysis_agent(q)
            print(f"  ✅ Analysis: {q[:50]}")
        except Exception as e:
            print(f"  ❌ Analysis failed: {e}")
        time.sleep(0.5)

    # Run email agents
    print("\n📧 Running email agents...")
    for task in email_tasks:
        try:
            email_agent(task)
            print(f"  ✅ Email: {task[:50]}")
        except Exception as e:
            print(f"  ❌ Email failed: {e}")
        time.sleep(0.5)

    # Run some failing agents
    print("\n💥 Running agents that might fail...")
    for i in range(5):
        try:
            failing_agent(f"risky task #{i+1}")
            print(f"  ✅ Risky task #{i+1} survived")
        except Exception as e:
            print(f"  ❌ Risky task #{i+1} failed: {e}")
        time.sleep(0.3)

    # Final flush
    lens.flush()
    time.sleep(1)

    print()
    print("=" * 60)
    print("  ✅ Demo complete! Open the dashboard:")
    print("  👉 http://localhost:8340/dashboard")
    print("=" * 60)


if __name__ == "__main__":
    main()
