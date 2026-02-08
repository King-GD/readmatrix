<script setup lang="ts">
import type { Message } from "@/composables/useChat";

interface Props {
  messages: Message[];
  loading?: boolean;
  showInlineCitations?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  showInlineCitations: true,
});

const emit = defineEmits<{
  "citation-click": [citationId: number];
  "example-click": [example: string];
  "message-click": [message: Message];
}>();

const scrollRef = ref<HTMLElement | null>(null);

// Auto-scroll to bottom when new messages arrive
watch(
  () => props.messages.length,
  () => {
    nextTick(() => {
      if (scrollRef.value) {
        scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
      }
    });
  },
);

const examples = [
  "乔布斯怎么看产品设计？",
  "关于习惯养成的观点有哪些？",
  "认知觉醒这本书的核心观点是什么？",
];
</script>

<template>
  <div class="flex-1 overflow-y-auto">
    <div ref="scrollRef" class="h-full">
      <!-- Empty state -->
      <div
        v-if="messages.length === 0"
        class="flex h-full flex-col items-center justify-center p-8"
      >
        <img src="/favicon.svg" alt="ReadMatrix" class="mb-4 w-16 h-16" />
        <h2 class="mb-2 text-xl font-semibold">欢迎使用 ReadMatrix</h2>
        <p class="text-center text-muted-foreground max-w-md">
          向我提问关于你读书笔记中的任何内容。<br />
          我会基于你的划线和笔记给出可追溯的回答。
        </p>
        <div class="mt-6 flex flex-wrap justify-center gap-2">
          <UiButton
            v-for="example in examples"
            :key="example"
            variant="outline"
            size="sm"
            @click="emit('example-click', example)"
          >
            {{ example }}
          </UiButton>
        </div>
      </div>

      <!-- Messages -->
      <div v-else class="py-4">
        <ChatMessageBubble
          v-for="(message, index) in messages"
          :key="message.id"
          :message="message"
          :show-citations="showInlineCitations"
          :is-typing="
            loading &&
            index === messages.length - 1 &&
            message.role === 'assistant' &&
            !message.content
          "
          @citation-click="emit('citation-click', $event)"
          @message-click="emit('message-click', $event)"
        />
      </div>
    </div>
  </div>
</template>
