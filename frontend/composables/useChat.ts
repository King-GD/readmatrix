/**
 * Chat state management: supports SSE streaming, citations, conversation restore,
 * and debate mode.
 */
import { computed, onMounted, ref } from "vue";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isClarification?: boolean;
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

export type ChatMode = "qa" | "debate";
export type DebateStatus = "idle" | "active" | "ended";
export type DebateJudgeMode = "none" | "winner";

export interface DebateConfig {
  topic: string;
  userStance: string;
  judgeMode: DebateJudgeMode;
}

interface DebateStatePayload {
  topic?: string;
  user_stance?: string;
  judge_mode?: DebateJudgeMode;
  status?: "active" | "ended";
}

interface ConversationListResponse {
  conversation_id: string;
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    citations?: Citation[];
    is_clarification?: boolean;
  }>;
  limit: number;
  offset: number;
  total: number;
  debate_state?: DebateStatePayload | null;
}

interface ConversationCreateResponse {
  conversation_id: string;
}

const STORAGE_KEY = "readmatrix_conversation_id";

export function useChat(options?: { apiUrl?: string }) {
  const config = useRuntimeConfig();
  const apiUrl = options?.apiUrl || config.public.apiUrl;

  const messages = ref<Message[]>([]);
  const input = ref("");
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  const currentCitations = ref<Citation[]>([]);
  const filters = ref<ChatFilters>({});
  const selectedCitation = ref<Citation | null>(null);
  const conversationId = ref<string | null>(null);

  const mode = ref<ChatMode>("qa");
  const debateConfig = ref<DebateConfig | null>(null);
  const debateStatus = ref<DebateStatus>("idle");
  const isDebateMode = computed(() => mode.value === "debate");

  const generateId = () => Math.random().toString(36).slice(2);

  function persistConversationId(id: string | null) {
    if (typeof window === "undefined") {
      return;
    }
    if (!id) {
      localStorage.removeItem(STORAGE_KEY);
      return;
    }
    localStorage.setItem(STORAGE_KEY, id);
  }

  function setConversationId(id: string | null) {
    conversationId.value = id;
    persistConversationId(id);
  }

  function normalizeDebateConfig(raw?: Partial<DebateConfig> | DebateStatePayload | null): DebateConfig | null {
    if (!raw) {
      return null;
    }

    const source = raw as Record<string, unknown>;
    const topic = String(source.topic || "").trim();
    const userStance = String(source.userStance || source.user_stance || "").trim();
    const judgeMode = String(source.judgeMode || source.judge_mode || "none");

    if (!topic || !userStance) {
      return null;
    }

    return {
      topic,
      userStance,
      judgeMode: judgeMode === "winner" ? "winner" : "none",
    };
  }

  function applyDebateState(state?: DebateStatePayload | null) {
    const cfg = normalizeDebateConfig(state);
    if (!cfg) {
      mode.value = "qa";
      debateConfig.value = null;
      debateStatus.value = "idle";
      return;
    }

    if (state?.status === "active") {
      mode.value = "debate";
      debateConfig.value = cfg;
      debateStatus.value = "active";
      return;
    }

    mode.value = "qa";
    debateConfig.value = null;
    debateStatus.value = "ended";
  }

  function startDebate(configInput: DebateConfig) {
    const cfg = normalizeDebateConfig(configInput);
    if (!cfg) {
      error.value = "请先填写完整的辩题和你的立场";
      return;
    }
    mode.value = "debate";
    debateConfig.value = cfg;
    debateStatus.value = "active";
    error.value = null;
  }

  function exitDebateMode() {
    mode.value = "qa";
    debateConfig.value = null;
    debateStatus.value = "idle";
  }

  function resetDebateState() {
    mode.value = "qa";
    debateConfig.value = null;
    debateStatus.value = "idle";
  }

  async function createConversation(): Promise<string> {
    const response = await fetch(`${apiUrl}/api/conversations`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });

    if (!response.ok) {
      throw new Error(`创建会话失败: ${response.status}`);
    }

    const payload = (await response.json()) as ConversationCreateResponse;
    if (!payload.conversation_id) {
      throw new Error("创建会话失败: 响应缺少 conversation_id");
    }

    setConversationId(payload.conversation_id);
    return payload.conversation_id;
  }

  async function ensureConversation(): Promise<string> {
    if (conversationId.value) {
      return conversationId.value;
    }
    return createConversation();
  }

  async function restoreConversationMessages() {
    if (typeof window === "undefined") {
      return;
    }

    const savedConversationId = localStorage.getItem(STORAGE_KEY);
    if (!savedConversationId) {
      return;
    }

    try {
      const response = await fetch(
        `${apiUrl}/api/conversations/${savedConversationId}/messages?limit=60&offset=0`,
      );

      if (response.status === 404) {
        setConversationId(null);
        resetDebateState();
        return;
      }

      if (!response.ok) {
        throw new Error(`加载历史会话失败: ${response.status}`);
      }

      const payload = (await response.json()) as ConversationListResponse;
      setConversationId(payload.conversation_id);
      messages.value = payload.messages.map((item) => ({
        id: item.id,
        role: item.role,
        content: item.content,
        citations: item.citations || [],
        isClarification: Boolean(item.is_clarification),
      }));

      const lastAssistant = [...messages.value]
        .reverse()
        .find((item) => item.role === "assistant" && item.citations?.length);
      if (lastAssistant?.citations) {
        currentCitations.value = lastAssistant.citations;
        selectedCitation.value = lastAssistant.citations[0] || null;
      }

      applyDebateState(payload.debate_state || null);
    } catch (e) {
      error.value = e instanceof Error ? e.message : "恢复会话失败";
    }
  }

  async function submit() {
    if (!input.value.trim() || isLoading.value) {
      return;
    }

    if (mode.value === "debate") {
      if (debateStatus.value !== "active" || !debateConfig.value) {
        error.value = "请先完成辩题和立场配置，再开始辩论";
        return;
      }
    }

    const query = input.value.trim();
    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: query,
    };

    messages.value.push(userMessage);
    input.value = "";
    isLoading.value = true;
    error.value = null;
    currentCitations.value = [];

    const assistantMessage: Message = {
      id: generateId(),
      role: "assistant",
      content: "",
      citations: [],
      isClarification: false,
    };
    messages.value.push(assistantMessage);
    const assistantIndex = messages.value.length - 1;

    let isClarification = false;
    let shouldExitDebateAfterDone = false;

    try {
      const activeConversationId = await ensureConversation();

      const body: Record<string, unknown> = {
        query,
        filters: filters.value,
        conversation_id: activeConversationId,
        use_context: true,
        mode: mode.value,
      };

      if (mode.value === "debate" && debateConfig.value) {
        body.debate = {
          topic: debateConfig.value.topic,
          user_stance: debateConfig.value.userStance,
          judge_mode: debateConfig.value.judgeMode,
        };
      }

      const response = await fetch(`${apiUrl}/api/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`API error: ${response.status} ${detail}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        let currentData = "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7);
          } else if (line.startsWith("data: ")) {
            currentData = line.slice(6);

            if (!currentEvent || !currentData) {
              continue;
            }

            const data = JSON.parse(currentData);

            if (currentEvent === "meta") {
              if (data.conversation_id) {
                setConversationId(data.conversation_id);
              }
              isClarification = Boolean(data.needs_clarification);

              if (data.mode === "debate") {
                mode.value = "debate";
              }

              if (data.debate_status === "active") {
                debateStatus.value = "active";
              }

              if (data.debate_status === "ended") {
                debateStatus.value = "ended";
                shouldExitDebateAfterDone = true;
              }
            } else if (currentEvent === "delta") {
              const currentMessage = messages.value[assistantIndex];
              messages.value[assistantIndex] = {
                ...currentMessage,
                content: currentMessage.content + (data.content || ""),
                isClarification,
              };
            } else if (currentEvent === "citations") {
              const currentMessage = messages.value[assistantIndex];
              const citations =
                isClarification || !Array.isArray(data) ? [] : data;

              currentCitations.value = citations;
              messages.value[assistantIndex] = {
                ...currentMessage,
                citations,
                isClarification,
              };
            }

            currentEvent = "";
            currentData = "";
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
      if (shouldExitDebateAfterDone) {
        mode.value = "qa";
        debateConfig.value = null;
      }
    }
  }

  function clear() {
    messages.value = [];
    currentCitations.value = [];
    selectedCitation.value = null;
    error.value = null;
  }

  async function startNewConversation() {
    clear();
    setConversationId(null);
    resetDebateState();
    try {
      await createConversation();
    } catch (e) {
      error.value = e instanceof Error ? e.message : "创建新对话失败";
    }
  }

  function selectCitation(citation: Citation) {
    selectedCitation.value = citation;
  }

  function openInObsidian(citation: Citation) {
    if (citation.obsidian_uri) {
      window.open(citation.obsidian_uri, "_blank");
    }
  }

  onMounted(() => {
    restoreConversationMessages();
  });

  return {
    messages,
    input,
    isLoading,
    error,
    currentCitations,
    selectedCitation,
    filters,
    conversationId,
    mode,
    isDebateMode,
    debateConfig,
    debateStatus,
    submit,
    clear,
    startNewConversation,
    startDebate,
    exitDebateMode,
    selectCitation,
    openInObsidian,
  };
}
