package io.agentlens;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

/**
 * AgentLens SDK for Java — AI Agent Observability.
 * 
 * Requires Java 11+ (uses java.net.http).
 * Zero external dependencies.
 * 
 * Usage:
 *   AgentLens lens = new AgentLens("http://localhost:8340", "al_your_api_key");
 *   String session = lens.startSession("my-java-agent");
 *   lens.trackLLMCall("gpt-4o", "openai", "Hello", "Hi!", 10, 5, 0.001, 200);
 *   lens.endSession(session, true, Map.of());
 *   lens.shutdown();
 */
public class AgentLens {
    private final String serverUrl;
    private final String apiKey;
    private final String projectId;
    private String agentName;
    private final int batchSize;

    private final List<Map<String, Object>> buffer = Collections.synchronizedList(new ArrayList<>());
    private String sessionId;
    private final HttpClient httpClient;
    private final ScheduledExecutorService scheduler;

    public AgentLens(String serverUrl, String apiKey) {
        this(serverUrl, apiKey, "default", "default", 50, 5000);
    }

    public AgentLens(String serverUrl, String apiKey, String projectId, String agentName, int batchSize, int flushIntervalMs) {
        this.serverUrl = serverUrl.replaceAll("/$", "");
        this.apiKey = apiKey;
        this.projectId = projectId;
        this.agentName = agentName;
        this.batchSize = batchSize;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.scheduler.scheduleAtFixedRate(this::flush, flushIntervalMs, flushIntervalMs, TimeUnit.MILLISECONDS);
    }

    // ─── Session Management ─────────────────────────────────

    public String startSession(String agentName) {
        this.sessionId = "sess_" + System.currentTimeMillis() + "_" + UUID.randomUUID().toString().substring(0, 8);
        addEvent(Map.of(
            "event_type", "session.start",
            "session_id", sessionId,
            "agent_name", agentName != null ? agentName : this.agentName
        ));
        return sessionId;
    }

    public void endSession(String sessionId, boolean success, Map<String, Object> meta) {
        Map<String, Object> event = new HashMap<>();
        event.put("event_type", "session.end");
        event.put("session_id", sessionId);
        event.put("success", success);
        event.put("meta", meta != null ? meta : Map.of());
        addEvent(event);
        this.sessionId = null;
        flush();
    }

    // ─── Event Tracking ─────────────────────────────────────

    public void trackLLMCall(String model, String provider, String prompt, String completion,
                              int inputTokens, int outputTokens, double costUsd, double latencyMs) {
        Map<String, Object> event = new HashMap<>();
        event.put("event_type", "llm.response");
        event.put("model", model);
        event.put("provider", provider);
        event.put("prompt", prompt);
        event.put("completion", completion);
        event.put("input_tokens", inputTokens);
        event.put("output_tokens", outputTokens);
        event.put("total_tokens", inputTokens + outputTokens);
        event.put("cost_usd", costUsd);
        event.put("latency_ms", latencyMs);
        addEvent(event);
    }

    public void trackToolCall(String toolName, Map<String, Object> toolArgs, String toolResult,
                               boolean success, double durationMs) {
        Map<String, Object> event = new HashMap<>();
        event.put("event_type", success ? "tool.result" : "tool.error");
        event.put("tool_name", toolName);
        event.put("tool_args", toolArgs);
        event.put("tool_result", toolResult);
        event.put("success", success);
        event.put("duration_ms", durationMs);
        addEvent(event);
    }

    public void trackStep(int stepNumber, String thought, String decision) {
        addEvent(Map.of(
            "event_type", "agent.step",
            "step_number", stepNumber,
            "thought", thought,
            "decision", decision
        ));
    }

    public void trackError(String errorType, String errorMessage, String stackTrace) {
        Map<String, Object> event = new HashMap<>();
        event.put("event_type", "error");
        event.put("error_type", errorType);
        event.put("error_message", errorMessage);
        event.put("stack_trace", stackTrace);
        event.put("success", false);
        addEvent(event);
    }

    // ─── Internal ───────────────────────────────────────────

    private void addEvent(Map<String, Object> event) {
        Map<String, Object> e = new HashMap<>(event);
        e.putIfAbsent("timestamp", System.currentTimeMillis() / 1000.0);
        e.putIfAbsent("session_id", sessionId != null ? sessionId : "");
        e.putIfAbsent("agent_name", agentName);
        e.put("event_id", "evt_" + System.currentTimeMillis() + "_" + UUID.randomUUID().toString().substring(0, 6));
        buffer.add(e);

        if (buffer.size() >= batchSize) {
            flush();
        }
    }

    public synchronized void flush() {
        if (buffer.isEmpty()) return;

        List<Map<String, Object>> events = new ArrayList<>(buffer);
        buffer.clear();

        try {
            String json = toJson(Map.of("events", events));
            HttpRequest.Builder reqBuilder = HttpRequest.newBuilder()
                .uri(URI.create(serverUrl + "/api/v1/events"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json));

            if (apiKey != null && !apiKey.isEmpty()) {
                reqBuilder.header("Authorization", "Bearer " + apiKey);
            }
            if (projectId != null) {
                reqBuilder.header("X-Project", projectId);
            }

            HttpResponse<String> resp = httpClient.send(reqBuilder.build(), HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                System.err.println("[AgentLens] Flush failed (" + resp.statusCode() + "): " + resp.body());
                buffer.addAll(0, events); // Retry
            }
        } catch (Exception e) {
            System.err.println("[AgentLens] Flush error: " + e.getMessage());
            buffer.addAll(0, events);
        }
    }

    public void shutdown() {
        scheduler.shutdown();
        flush();
        try {
            scheduler.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {}
    }

    // Simple JSON serializer (no dependencies)
    private String toJson(Object obj) {
        if (obj == null) return "null";
        if (obj instanceof String) return "\"" + ((String) obj).replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\"";
        if (obj instanceof Number || obj instanceof Boolean) return obj.toString();
        if (obj instanceof Map) {
            Map<?, ?> map = (Map<?, ?>) obj;
            StringBuilder sb = new StringBuilder("{");
            boolean first = true;
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!first) sb.append(",");
                sb.append("\"").append(entry.getKey()).append("\":").append(toJson(entry.getValue()));
                first = false;
            }
            return sb.append("}").toString();
        }
        if (obj instanceof List) {
            List<?> list = (List<?>) obj;
            StringBuilder sb = new StringBuilder("[");
            for (int i = 0; i < list.size(); i++) {
                if (i > 0) sb.append(",");
                sb.append(toJson(list.get(i)));
            }
            return sb.append("]").toString();
        }
        return "\"" + obj.toString() + "\"";
    }
}
