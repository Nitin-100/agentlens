// Package agentlens provides a Go SDK for AgentLens — AI Agent Observability.
//
// Usage:
//
//	lens := agentlens.New("http://localhost:8340", "al_your_api_key")
//	defer lens.Shutdown()
//
//	sess := lens.StartSession("my-go-agent")
//	lens.TrackLLMCall(agentlens.LLMEvent{
//	    Model: "gpt-4o", Prompt: "Hello", Completion: "Hi!", LatencyMs: 120,
//	})
//	lens.EndSession(sess, true, nil)
package agentlens

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"sync"
	"time"
)

// Client is the main AgentLens SDK client.
type Client struct {
	serverURL     string
	apiKey        string
	projectID     string
	agentName     string
	batchSize     int
	flushInterval time.Duration

	buffer    []map[string]interface{}
	mu        sync.Mutex
	sessionID string
	client    *http.Client
	done      chan struct{}
}

// Option configures the client.
type Option func(*Client)

func WithProjectID(id string) Option   { return func(c *Client) { c.projectID = id } }
func WithAgentName(name string) Option  { return func(c *Client) { c.agentName = name } }
func WithBatchSize(n int) Option        { return func(c *Client) { c.batchSize = n } }
func WithFlushInterval(d time.Duration) Option {
	return func(c *Client) { c.flushInterval = d }
}

// New creates a new AgentLens client.
func New(serverURL, apiKey string, opts ...Option) *Client {
	c := &Client{
		serverURL:     serverURL,
		apiKey:        apiKey,
		projectID:     "default",
		agentName:     "default",
		batchSize:     50,
		flushInterval: 5 * time.Second,
		buffer:        make([]map[string]interface{}, 0, 64),
		client:        &http.Client{Timeout: 10 * time.Second},
		done:          make(chan struct{}),
	}
	for _, o := range opts {
		o(c)
	}
	go c.autoFlush()
	return c
}

// StartSession begins a new monitoring session.
func (c *Client) StartSession(agentName string) string {
	if agentName == "" {
		agentName = c.agentName
	}
	c.mu.Lock()
	c.sessionID = fmt.Sprintf("sess_%d_%s", time.Now().UnixMilli(), randStr(8))
	sid := c.sessionID
	c.mu.Unlock()

	c.addEvent(map[string]interface{}{
		"event_type": "session.start",
		"session_id": sid,
		"agent_name": agentName,
	})
	return sid
}

// EndSession ends the current session.
func (c *Client) EndSession(sessionID string, success bool, meta map[string]interface{}) {
	if meta == nil {
		meta = map[string]interface{}{}
	}
	c.addEvent(map[string]interface{}{
		"event_type": "session.end",
		"session_id": sessionID,
		"success":    success,
		"meta":       meta,
	})
	c.mu.Lock()
	c.sessionID = ""
	c.mu.Unlock()
	c.Flush()
}

// LLMEvent represents an LLM call to track.
type LLMEvent struct {
	Model        string  `json:"model"`
	Provider     string  `json:"provider"`
	Prompt       string  `json:"prompt"`
	Completion   string  `json:"completion"`
	InputTokens  int     `json:"input_tokens"`
	OutputTokens int     `json:"output_tokens"`
	CostUSD      float64 `json:"cost_usd"`
	LatencyMs    float64 `json:"latency_ms"`
}

// TrackLLMCall records an LLM call event.
func (c *Client) TrackLLMCall(e LLMEvent) {
	c.addEvent(map[string]interface{}{
		"event_type":   "llm.response",
		"model":        e.Model,
		"provider":     e.Provider,
		"prompt":       e.Prompt,
		"completion":   e.Completion,
		"input_tokens": e.InputTokens,
		"output_tokens": e.OutputTokens,
		"total_tokens":  e.InputTokens + e.OutputTokens,
		"cost_usd":     e.CostUSD,
		"latency_ms":   e.LatencyMs,
	})
}

// ToolEvent represents a tool call to track.
type ToolEvent struct {
	ToolName   string                 `json:"tool_name"`
	ToolArgs   map[string]interface{} `json:"tool_args"`
	ToolResult string                 `json:"tool_result"`
	Success    bool                   `json:"success"`
	DurationMs float64               `json:"duration_ms"`
}

// TrackToolCall records a tool call event.
func (c *Client) TrackToolCall(e ToolEvent) {
	eventType := "tool.result"
	if !e.Success {
		eventType = "tool.error"
	}
	c.addEvent(map[string]interface{}{
		"event_type":  eventType,
		"tool_name":   e.ToolName,
		"tool_args":   e.ToolArgs,
		"tool_result": e.ToolResult,
		"success":     e.Success,
		"duration_ms": e.DurationMs,
	})
}

// TrackError records an error event.
func (c *Client) TrackError(errorType, errorMsg, stackTrace string) {
	c.addEvent(map[string]interface{}{
		"event_type":    "error",
		"error_type":    errorType,
		"error_message": errorMsg,
		"stack_trace":   stackTrace,
		"success":       false,
	})
}

// TrackStep records an agent reasoning step.
func (c *Client) TrackStep(stepNumber int, thought, decision string) {
	c.addEvent(map[string]interface{}{
		"event_type":  "agent.step",
		"step_number": stepNumber,
		"thought":     thought,
		"decision":    decision,
	})
}

func (c *Client) addEvent(event map[string]interface{}) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if _, ok := event["timestamp"]; !ok {
		event["timestamp"] = float64(time.Now().UnixMilli()) / 1000.0
	}
	if _, ok := event["session_id"]; !ok {
		event["session_id"] = c.sessionID
	}
	if _, ok := event["agent_name"]; !ok {
		event["agent_name"] = c.agentName
	}
	event["event_id"] = fmt.Sprintf("evt_%d_%s", time.Now().UnixMilli(), randStr(6))

	c.buffer = append(c.buffer, event)
	if len(c.buffer) >= c.batchSize {
		go c.Flush()
	}
}

// Flush sends all buffered events to the server.
func (c *Client) Flush() error {
	c.mu.Lock()
	if len(c.buffer) == 0 {
		c.mu.Unlock()
		return nil
	}
	events := c.buffer
	c.buffer = make([]map[string]interface{}, 0, 64)
	c.mu.Unlock()

	body := map[string]interface{}{"events": events}
	data, err := json.Marshal(body)
	if err != nil {
		// Re-add to buffer
		c.mu.Lock()
		c.buffer = append(events, c.buffer...)
		c.mu.Unlock()
		return fmt.Errorf("marshal error: %w", err)
	}

	req, err := http.NewRequest("POST", c.serverURL+"/api/v1/events", bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
	if c.projectID != "" {
		req.Header.Set("X-Project", c.projectID)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		c.mu.Lock()
		c.buffer = append(events, c.buffer...)
		c.mu.Unlock()
		return fmt.Errorf("send error: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return fmt.Errorf("server returned %d", resp.StatusCode)
	}
	return nil
}

// Shutdown flushes remaining events and stops the background goroutine.
func (c *Client) Shutdown() {
	close(c.done)
	c.Flush()
}

func (c *Client) autoFlush() {
	ticker := time.NewTicker(c.flushInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			c.Flush()
		case <-c.done:
			return
		}
	}
}

func randStr(n int) string {
	const letters = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, n)
	for i := range b {
		b[i] = letters[rand.Intn(len(letters))]
	}
	return string(b)
}
