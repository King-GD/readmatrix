/**
 * Chat composable using Vercel AI SDK
 * Handles SSE streaming and citation management
 */
import { ref, computed } from "vue";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

export interface Citation {
  id: number;
  chunk_id: string;
  block_id: string;
  source_path: string;
  title_path: string[];
  snippet: string;
  book_id: string;
  book_title: string;
  author?: string;
  highlight_time?: string;
  obsidian_uri?: string;
}

export interface ChatFilters {
  book_id?: string;
  book_title?: string;
}

export function useChat(options?: { apiUrl?: string }) {
  const config = useRuntimeConfig();
  const apiUrl = options?.apiUrl || config.public.apiUrl;

  const messages = ref<Message[]>([]);
  const input = ref("");
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  const currentCitations = ref<Citation[]>([]);
  const filters = ref<ChatFilters>({});

  // Currently selected citation for sidebar display
  const selectedCitation = ref<Citation | null>(null);

  // Generate unique ID
  const generateId = () => Math.random().toString(36).substring(7);

  // Submit a message
  async function submit() {
    if (!input.value.trim() || isLoading.value) return;

    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: input.value.trim(),
    };

    messages.value.push(userMessage);
    const query = input.value;
    input.value = "";
    isLoading.value = true;
    error.value = null;
    currentCitations.value = [];

    // Create assistant message placeholder
    const assistantMessage: Message = {
      id: generateId(),
      role: "assistant",
      content: "",
    };
    messages.value.push(assistantMessage);

    // Get the index for reactive updates
    const assistantIndex = messages.value.length - 1;

    try {
      const response = await fetch(`${apiUrl}/api/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          query,
          filters: filters.value,
        }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("No response body");
      }

      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        let currentData = "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7);
          } else if (line.startsWith("data: ")) {
            currentData = line.slice(6);

            if (currentEvent && currentData) {
              const data = JSON.parse(currentData);

              if (currentEvent === "delta") {
                // Trigger reactive update by replacing the message object
                const currentMessage = messages.value[assistantIndex];
                messages.value[assistantIndex] = {
                  ...currentMessage,
                  content: currentMessage.content + data.content,
                };
              } else if (currentEvent === "citations") {
                // Store citations
                const currentMessage = messages.value[assistantIndex];
                const noInfo = currentMessage.content.includes(
                  "根据你的笔记，我没有找到相关信息",
                );
                const citations = noInfo ? [] : data;
                currentCitations.value = citations;
                messages.value[assistantIndex] = {
                  ...currentMessage,
                  citations,
                };
              } else if (currentEvent === "done") {
                // Stream finished
              }

              currentEvent = "";
              currentData = "";
            }
          }
        }
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Unknown error";
      messages.value[assistantIndex] = {
        ...messages.value[assistantIndex],
        content: "抱歉，发生了错误。请稍后再试。",
      };
    } finally {
      isLoading.value = false;
    }
  }

  // Clear messages
  function clear() {
    messages.value = [];
    currentCitations.value = [];
    selectedCitation.value = null;
    error.value = null;
  }

  // Select a citation to show in sidebar
  function selectCitation(citation: Citation) {
    selectedCitation.value = citation;
  }

  // Open citation in Obsidian
  function openInObsidian(citation: Citation) {
    if (citation.obsidian_uri) {
      window.open(citation.obsidian_uri, "_blank");
    }
  }

  return {
    messages,
    input,
    isLoading,
    error,
    currentCitations,
    selectedCitation,
    filters,
    submit,
    clear,
    selectCitation,
    openInObsidian,
  };
}
