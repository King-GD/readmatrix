<script setup lang="ts">
import { useChat } from "@/composables/useChat";
import { MessageSquarePlus, Scale, Swords, Trash2, X } from "lucide-vue-next";

const {
  messages,
  input,
  isLoading,
  error,
  currentCitations,
  selectedCitation,
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
} = useChat();

const showCitationPanel = computed(() => currentCitations.value.length > 0);

const showDebateSetup = ref(false);
const debateTopic = ref("");
const debateUserStance = ref("");
const debateJudgeMode = ref<"none" | "winner">("none");

const canConfirmDebate = computed(
  () => debateTopic.value.trim().length > 0 && debateUserStance.value.trim().length > 0,
);

const inputDisabled = computed(
  () => isDebateMode.value && debateStatus.value !== "active",
);

const inputPlaceholder = computed(() => {
  if (isDebateMode.value) {
    return "输入你的辩论观点，发送“结束”生成总结";
  }
  return "输入你的问题...";
});

const inputFooterText = computed(() => {
  if (isDebateMode.value) {
    return "辩论模式：AI 默认站在你的对立面，可补充通用知识并标注【非笔记依据】。";
  }
  return "基于你的读书笔记回答，所有结论可追溯到原文。";
});

watch(
  debateConfig,
  (value: typeof debateConfig.value) => {
    if (!value) {
      return;
    }
    debateTopic.value = value.topic;
    debateUserStance.value = value.userStance;
    debateJudgeMode.value = value.judgeMode;
  },
  { immediate: true },
);

function handleExampleClick(example: string) {
  input.value = example;
  submit();
}

function handleCitationClick(citationId: number) {
  const citation = currentCitations.value.find((c) => c.id === citationId);
  if (citation) {
    selectCitation(citation);
  }
}

function handleMessageClick(message: typeof messages.value[number]) {
  if (message.citations && message.citations.length > 0) {
    currentCitations.value = message.citations;
    selectCitation(message.citations[0]);
  } else {
    currentCitations.value = [];
  }
}

function toggleDebateMode() {
  if (isDebateMode.value) {
    exitDebateMode();
    showDebateSetup.value = false;
    return;
  }
  showDebateSetup.value = true;
}

function confirmDebateSetup() {
  if (!canConfirmDebate.value) {
    return;
  }

  startDebate({
    topic: debateTopic.value,
    userStance: debateUserStance.value,
    judgeMode: debateJudgeMode.value,
  });
  showDebateSetup.value = false;
}

function cancelDebateSetup() {
  showDebateSetup.value = false;
}
</script>

<template>
  <div class="flex flex-1 overflow-hidden">
    <div class="flex min-w-0 flex-1 flex-col">
      <div class="flex justify-end gap-2 border-b p-2">
        <button
          class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          @click="toggleDebateMode"
        >
          <Swords class="h-3 w-3" />
          {{ isDebateMode ? "退出辩论" : "辩论模式" }}
        </button>
        <button
          class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          @click="startNewConversation"
        >
          <MessageSquarePlus class="h-3 w-3" />
          新对话
        </button>
        <button
          v-if="messages.length > 0"
          class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          @click="clear"
        >
          <Trash2 class="h-3 w-3" />
          清空当前页
        </button>
      </div>

      <div v-if="showDebateSetup" class="border-b bg-muted/30 px-4 py-3">
        <div class="mx-auto max-w-3xl space-y-3">
          <div class="flex items-center justify-between">
            <div class="inline-flex items-center gap-2 text-sm font-medium">
              <Scale class="h-4 w-4" />
              辩论开场配置
            </div>
            <UiButton variant="ghost" size="sm" @click="cancelDebateSetup">
              <X class="h-4 w-4" />
            </UiButton>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="space-y-1">
              <label class="text-xs text-muted-foreground">辩题（必填）</label>
              <UiInput v-model="debateTopic" placeholder="例如：深阅读是否过时" />
            </div>
            <div class="space-y-1">
              <label class="text-xs text-muted-foreground">你的立场（必填）</label>
              <UiInput v-model="debateUserStance" placeholder="例如：深阅读不过时" />
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-xs text-muted-foreground">总结是否判胜负</label>
            <div class="flex gap-2">
              <UiButton
                size="sm"
                :variant="debateJudgeMode === 'none' ? 'default' : 'outline'"
                @click="debateJudgeMode = 'none'"
              >
                中立总结（默认）
              </UiButton>
              <UiButton
                size="sm"
                :variant="debateJudgeMode === 'winner' ? 'default' : 'outline'"
                @click="debateJudgeMode = 'winner'"
              >
                给出胜负判断
              </UiButton>
            </div>
          </div>

          <div class="flex justify-end gap-2">
            <UiButton variant="outline" size="sm" @click="cancelDebateSetup">
              取消
            </UiButton>
            <UiButton size="sm" :disabled="!canConfirmDebate" @click="confirmDebateSetup">
              开始辩论
            </UiButton>
          </div>
        </div>
      </div>

      <div v-if="isDebateMode && debateConfig" class="border-b bg-primary/5 px-4 py-2">
        <div class="mx-auto flex max-w-3xl flex-wrap items-center gap-2 text-xs text-foreground">
          <span class="rounded bg-primary/15 px-2 py-0.5 font-medium">辩论中</span>
          <span>辩题：{{ debateConfig.topic }}</span>
          <span>你的立场：{{ debateConfig.userStance }}</span>
          <span class="text-muted-foreground">发送“结束”可生成总结</span>
        </div>
      </div>

      <ChatPanel
        :messages="messages"
        :loading="isLoading"
        :show-inline-citations="!showCitationPanel"
        @citation-click="handleCitationClick"
        @example-click="handleExampleClick"
        @message-click="handleMessageClick"
      />

      <div v-if="error" class="px-4 pb-2">
        <div class="rounded-lg bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {{ error }}
        </div>
      </div>

      <ChatInput
        v-model="input"
        :loading="isLoading"
        :disabled="inputDisabled"
        :placeholder="inputPlaceholder"
        :footer-text="inputFooterText"
        @submit="submit"
      />
    </div>

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
