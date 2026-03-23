<script setup lang="ts">
import { ref } from "vue";
import { MessageSquarePlus, Trash2, MessageCircle } from "lucide-vue-next";
import type { ConversationItem } from "@/composables/useChat";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

const props = defineProps<{
  conversations: ConversationItem[];
  activeId: string | null;
}>();

const emit = defineEmits<{
  (e: "select", id: string): void;
  (e: "delete", id: string): void;
  (e: "new"): void;
}>();

const showDeleteAlert = ref(false);
const itemToDelete = ref<string | null>(null);

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

function requestDelete(e: Event, id: string) {
  e.stopPropagation();
  itemToDelete.value = id;
  showDeleteAlert.value = true;
}

function confirmDelete() {
  if (itemToDelete.value) {
    emit("delete", itemToDelete.value);
  }
  showDeleteAlert.value = false;
  itemToDelete.value = null;
}
</script>

<template>
  <aside class="flex h-full w-64 flex-col border-r bg-background/50">
    <div class="flex h-14 shrink-0 items-center justify-between border-b px-4">
      <span class="text-sm font-semibold text-foreground">对话历史</span>
      <button
        class="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        title="新对话"
        @click="emit('new')"
      >
        <MessageSquarePlus class="h-4 w-4" />
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-3">
      <div
        v-if="conversations.length === 0"
        class="mt-10 flex flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground"
      >
        <MessageCircle class="h-10 w-10 opacity-20 mb-2" />
        <p>还没有对话记录</p>
        <p class="text-xs">开始提问吧</p>
      </div>

      <div v-else class="flex flex-col gap-1.5">
        <button
          v-for="item in conversations"
          :key="item.id"
          class="group relative flex w-full flex-col items-start rounded-lg px-3 py-2.5 text-left transition-all hover:bg-muted/80"
          :class="item.id === activeId ? 'bg-muted shadow-sm' : 'bg-transparent'"
          @click="emit('select', item.id)"
        >
          <div class="flex w-full items-center justify-between gap-4 pr-6">
            <span 
              class="truncate text-sm font-medium leading-relaxed" 
              :class="item.id === activeId ? 'text-foreground' : 'text-foreground/80 group-hover:text-foreground'"
              :title="displayTitle(item)"
            >
              {{ displayTitle(item) }}
            </span>
          </div>
          <div class="mt-1 flex w-full items-center justify-between">
            <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span>{{ formatRelativeTime(item.updated_at) }}</span>
              <span v-if="item.message_count > 0">· {{ item.message_count }}条</span>
            </div>
          </div>
          
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground opacity-0 transition-all hover:bg-background hover:text-destructive group-hover:opacity-100"
            title="删除对话"
            @click="requestDelete($event, item.id)"
          >
            <Trash2 class="h-4 w-4" />
          </button>
        </button>
      </div>
    </div>
  </aside>

  <AlertDialog :open="showDeleteAlert" @update:open="showDeleteAlert = $event">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>确认删除对话吗？</AlertDialogTitle>
        <AlertDialogDescription>
          此操作无法撤销。这将永久删除该对话的所有历史记录。
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="showDeleteAlert = false">取消</AlertDialogCancel>
        <AlertDialogAction class="bg-destructive text-destructive-foreground hover:bg-destructive/90" @click="confirmDelete">确认删除</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
