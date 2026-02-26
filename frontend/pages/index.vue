<script setup lang="ts">
import { useChat } from "@/composables/useChat";
import { MessageSquarePlus, Trash2 } from "lucide-vue-next";

const {
  messages,
  input,
  isLoading,
  error,
  currentCitations,
  selectedCitation,
  submit,
  clear,
  startNewConversation,
  selectCitation,
  openInObsidian,
} = useChat();

// Show citation panel when we have citations
const showCitationPanel = computed(() => currentCitations.value.length > 0);

// Handle example click from empty state
function handleExampleClick(example: string) {
  input.value = example;
  submit();
}

// Handle citation click from message
function handleCitationClick(citationId: number) {
  const citation = currentCitations.value.find((c) => c.id === citationId);
  if (citation) {
    selectCitation(citation);
  }
}

// 点击消息时打开对应引用栏
function handleMessageClick(message: typeof messages.value[number]) {
  if (message.citations && message.citations.length > 0) {
    currentCitations.value = message.citations;
    selectCitation(message.citations[0]);
  } else {
    currentCitations.value = [];
  }
}
</script>

<template>
  <div class="flex-1 flex overflow-hidden">
    <!-- Chat area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Toolbar -->
      <div class="flex justify-end gap-2 p-2 border-b">
        <button
          class="inline-flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground rounded hover:bg-muted transition-colors"
          @click="startNewConversation"
        >
          <MessageSquarePlus class="h-3 w-3" />
          新对话
        </button>
        <button
          v-if="messages.length > 0"
          class="inline-flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground rounded hover:bg-muted transition-colors"
          @click="clear"
        >
          <Trash2 class="h-3 w-3" />
          清空当前页
        </button>
      </div>

      <!-- Messages -->
      <ChatPanel
        :messages="messages"
        :loading="isLoading"
        :show-inline-citations="!showCitationPanel"
        @citation-click="handleCitationClick"
        @example-click="handleExampleClick"
        @message-click="handleMessageClick"
      />

      <!-- Error -->
      <div v-if="error" class="px-4 pb-2">
        <div
          class="rounded-lg bg-destructive/10 text-destructive px-4 py-2 text-sm"
        >
          {{ error }}
        </div>
      </div>

      <!-- Input -->
      <ChatInput v-model="input" :loading="isLoading" @submit="submit" />
    </div>

    <!-- Citation sidebar -->
    <CitationPanel
      v-if="showCitationPanel"
      :citation="selectedCitation"
      :citations="currentCitations"
      @close="currentCitations = []"
      @select="selectCitation"
      @open-obsidian="openInObsidian"
    />
  </div>
</template>
