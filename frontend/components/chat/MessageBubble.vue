<script setup lang="ts">
import { cn } from "@/lib/utils";
import { marked } from "marked";
import type { Message } from "@/composables/useChat";

interface Props {
  message: Message;
  isTyping?: boolean;
  showCitations?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  isTyping: false,
  showCitations: true,
});

const emit = defineEmits<{
  "citation-click": [citationId: number];
  "message-click": [message: Message];
}>();

// Configure marked options
marked.setOptions({
  breaks: true, // Convert \n to <br>
  gfm: true, // GitHub Flavored Markdown
});

// Parse markdown and citation references in content
function parseContent(content: string) {
  // First parse Markdown to HTML
  let html = marked.parse(content) as string;
  // Then replace citation references with clickable spans
  html = html.replace(/\[(\d+)\]/g, (match, num) => {
    return `<span class="citation-ref" data-citation="${num}">[${num}]</span>`;
  });
  return html;
}

// Handle click on citation reference
function handleClick(event: MouseEvent) {
  const target = event.target as HTMLElement;
  if (target.classList.contains("citation-ref")) {
    const citationId = parseInt(target.dataset.citation || "0");
    if (citationId > 0) {
      event.stopPropagation();
      emit("citation-click", citationId);
    }
  }
}
</script>

<template>
  <!-- User message: keep bubble style, centered like AI -->
  <div
    v-if="message.role === 'user'"
    class="px-4 py-3"
    @click="emit('message-click', message)"
  >
    <div class="flex justify-end max-w-4xl mx-auto">
      <div class="max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-white">
        <div class="text-sm leading-relaxed">
          {{ message.content }}
        </div>
      </div>
    </div>
  </div>

  <!-- AI message: clean style like ChatGPT -->
  <div
    v-else
    class="px-4 py-6"
    @click="emit('message-click', message)"
  >
    <div class="flex gap-4 max-w-4xl mx-auto">
      <!-- Avatar -->
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 overflow-hidden"
      >
        <UiLogo :size="24" />
      </div>

      <!-- Content -->
      <div class="flex-1 min-w-0">
        <div
          v-if="message.content"
          class="ai-message-content"
          @click="handleClick"
          v-html="parseContent(message.content)"
        />
        <div v-else-if="isTyping" class="flex gap-1.5 py-2">
          <span
            class="h-2 w-2 rounded-full bg-primary/40 animate-bounce"
            style="animation-delay: 0ms"
          />
          <span
            class="h-2 w-2 rounded-full bg-primary/40 animate-bounce"
            style="animation-delay: 150ms"
          />
          <span
            class="h-2 w-2 rounded-full bg-primary/40 animate-bounce"
            style="animation-delay: 300ms"
          />
        </div>

        <!-- Citation badges -->
        <div
          v-if="
            showCitations &&
            message.citations &&
            message.citations.length > 0
          "
          class="mt-4 flex flex-wrap gap-1.5"
        >
          <UiButton
            v-for="citation in message.citations"
            :key="citation.id"
            variant="outline"
            size="sm"
            class="h-7 px-2.5 text-xs rounded-full"
            @click="emit('citation-click', citation.id)"
          >
            [{{ citation.id }}] {{ citation.book_title.slice(0, 15) }}...
          </UiButton>
        </div>
      </div>
    </div>
  </div>
</template>
