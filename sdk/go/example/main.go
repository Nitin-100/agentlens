package main

import (
	"fmt"
	agentlens "agentlens-sdk"
)

func main() {
	// 1. Initialize
	lens := agentlens.New(
		"http://localhost:8340",
		"al_your_api_key",
		agentlens.WithAgentName("my-go-agent"),
	)
	defer lens.Shutdown()

	// 2. Start session
	sess := lens.StartSession("my-go-agent")
	fmt.Printf("Session started: %s\n", sess)

	// 3. Track LLM call
	lens.TrackLLMCall(agentlens.LLMEvent{
		Model:        "gpt-4o",
		Provider:     "openai",
		Prompt:       "What is the capital of France?",
		Completion:   "The capital of France is Paris.",
		InputTokens:  12,
		OutputTokens: 8,
		CostUSD:      0.0003,
		LatencyMs:    450,
	})

	// 4. Track tool call
	lens.TrackToolCall(agentlens.ToolEvent{
		ToolName:   "web_search",
		ToolArgs:   map[string]interface{}{"query": "Paris population"},
		ToolResult: "2.1 million",
		Success:    true,
		DurationMs: 320,
	})

	// 5. Track reasoning step
	lens.TrackStep(1, "User asked about France", "Search for more details")

	// 6. End session
	lens.EndSession(sess, true, map[string]interface{}{
		"total_cost":   0.0003,
		"total_tokens": 20,
	})

	fmt.Println("Done! Check dashboard at http://localhost:5173")
}
