<script setup lang="ts">
import { MessageSquarePlus, Trash2, MessageCircle } from "lucide-vue-next";
import type { ConversationItem } from "@/composables/useChat";

const props = defineProps<{
  conversations: ConversationItem[];
  activeId: string | null;
}>();

const emit = defineEmits<{
  (e: "select", id: string): void;
  (e: "delete", id: string): void;
  (e: "new"): void;
}>();

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin}分钟前`;
  if (diffHour < 24) return `${diffHour}小时前`;
  if (diffDay < 7) return `${diffDay}天前`;
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

function displayTitle(item: ConversationItem): string {
  return item.title || "新对话";
}

function handleDelete(e: Event, id: string) {
  e.stopPropagation();
  if (confirm("删除后无法恢复，确认吗？")) {
    emit("delete", id);
  }
}
</script>

<template>
  <aside class="flex h-full w-60 flex-col border-r bg-muted/30">
    <div class="flex items-center justify-between border-b px-3 py-2">
      <span class="text-xs font-medium text-muted-foreground">对话历史</span>
      <button
        class="inline-flex items-center justify-center rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        title="新对话"
        @click="emit('new')"
      >
        <MessageSquarePlus class="h-4 w-4" />
      </button>
    </div>

    <div class="flex-1 overflow-y-auto">
      <div
        v-if="conversations.length === 0"
        class="flex flex-col items-center gap-2 px-4 py-8 text-center text-xs text-muted-foreground"
      >
        <MessageCircle class="h-8 w-8 opacity-40" />
        <span>还没有对话记录</span>
        <span>开始提问吧</span>
      </div>

      <button
        v-for="item in conversations"
        :key="item.id"
        class="group flex w-full items-start gap-2 border-b px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60"
        :class="{ 'bg-muted': item.id === activeId }"
        @click="emit('select', item.id)"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate font-medium leading-tight" :title="displayTitle(item)">
            {{ displayTitle(item) }}
          </div>
          <div class="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
            <span>{{ formatRelativeTime(item.updated_at) }}</span>
            <span v-if="item.message_count > 0">· {{ item.message_count }}条</span>
          </div>
        </div>
        <button
          class="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
          title="删除对话"
          @click="handleDelete($event, item.id)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </button>
      </button>
    </div>
  </aside>
</template>
