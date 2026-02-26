/**
 * 聊天状态管理：支持 SSE 流式问答、引用管理与会话恢复。
 */
import { onMounted, ref } from "vue";

/**
 * 对话消息。
 */
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isClarification?: boolean;
}

/**
 * 引用对象，与后端 citation 协议保持一致。
 */
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

/**
 * 问答过滤条件。
 */
export interface ChatFilters {
  book_id?: string;
  book_title?: string;
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
}

interface ConversationCreateResponse {
  conversation_id: string;
}

const STORAGE_KEY = "readmatrix_conversation_id";

/**
 * 组合式函数：提供对话提交、恢复、清理和新建会话能力。
 */
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

  /**
   * 生成前端临时消息 ID。
   */
  const generateId = () => Math.random().toString(36).slice(2);

  /**
   * 持久化当前会话 ID 到浏览器。
   */
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

  /**
   * 更新会话 ID 状态并同步本地存储。
   */
  function setConversationId(id: string | null) {
    conversationId.value = id;
    persistConversationId(id);
  }

  /**
   * 创建后端会话。
   */
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

  /**
   * 确保存在可用会话，不存在时自动创建。
   */
  async function ensureConversation(): Promise<string> {
    if (conversationId.value) {
      return conversationId.value;
    }
    return createConversation();
  }

  /**
   * 从后端恢复历史会话消息。
   */
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
    } catch (e) {
      error.value = e instanceof Error ? e.message : "恢复会话失败";
    }
  }

  /**
   * 提交用户消息并处理 SSE 响应。
   */
  async function submit() {
    if (!input.value.trim() || isLoading.value) {
      return;
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

    try {
      const activeConversationId = await ensureConversation();

      const response = await fetch(`${apiUrl}/api/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          query,
          filters: filters.value,
          conversation_id: activeConversationId,
          use_context: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
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
            } else if (currentEvent === "delta") {
              const currentMessage = messages.value[assistantIndex];
              messages.value[assistantIndex] = {
                ...currentMessage,
                content: currentMessage.content + (data.content || ""),
                isClarification,
              };
            } else if (currentEvent === "citations") {
              const currentMessage = messages.value[assistantIndex];
              const noInfo = currentMessage.content.includes(
                "根据你的笔记，我没有找到相关信息",
              );
              const citations =
                noInfo || isClarification || !Array.isArray(data) ? [] : data;

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
    }
  }

  /**
   * 仅清空当前页面消息，不删除后端会话。
   */
  function clear() {
    messages.value = [];
    currentCitations.value = [];
    selectedCitation.value = null;
    error.value = null;
  }

  /**
   * 开启新对话：清空界面并创建新会话。
   */
  async function startNewConversation() {
    clear();
    setConversationId(null);
    try {
      await createConversation();
    } catch (e) {
      error.value = e instanceof Error ? e.message : "创建新对话失败";
    }
  }

  /**
   * 选择侧栏展示的引用。
   */
  function selectCitation(citation: Citation) {
    selectedCitation.value = citation;
  }

  /**
   * 在 Obsidian 中打开引用。
   */
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
    submit,
    clear,
    startNewConversation,
    selectCitation,
    openInObsidian,
  };
}
