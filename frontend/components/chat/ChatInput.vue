<script setup lang="ts">
import { Send, Loader2 } from "lucide-vue-next";

interface Props {
  modelValue: string;
  loading?: boolean;
  placeholder?: string;
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  placeholder: "输入你的问题...",
});

const emit = defineEmits<{
  "update:modelValue": [value: string];
  submit: [];
}>();

const textareaRef = ref<HTMLTextAreaElement | null>(null);

function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement;
  emit("update:modelValue", target.value);
  autoResize(target);
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    emit("submit");
  }
}

function autoResize(element: HTMLTextAreaElement) {
  element.style.height = "auto";
  element.style.height = Math.min(element.scrollHeight, 200) + "px";
}
</script>

<template>
  <div class="border-t bg-background p-4">
    <div class="mx-auto max-w-3xl">
      <div class="flex gap-2">
        <div class="relative flex-1">
          <textarea
            ref="textareaRef"
            :value="modelValue"
            :placeholder="placeholder"
            :disabled="loading"
            rows="1"
            class="flex w-full resize-none rounded-md border border-input bg-background px-4 py-3 pr-12 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            @input="handleInput"
            @keydown="handleKeydown"
          />
          <UiButton
            :disabled="loading || !modelValue.trim()"
            size="icon"
            class="absolute bottom-2 right-2 h-8 w-8"
            @click="emit('submit')"
          >
            <Loader2 v-if="loading" class="h-4 w-4 animate-spin" />
            <Send v-else class="h-4 w-4" />
          </UiButton>
        </div>
      </div>
      <p class="mt-2 text-xs text-muted-foreground text-center">
        基于你的读书笔记回答，所有结论可追溯到原文
      </p>
    </div>
  </div>
</template>
