<script setup lang="ts">
import { X, ExternalLink, Book, User, Clock } from "lucide-vue-next";
import type { Citation } from "@/composables/useChat";
import { cn } from "@/lib/utils";

interface Props {
  citation: Citation | null;
  citations: Citation[];
}

const props = defineProps<Props>();

const emit = defineEmits<{
  close: [];
  select: [citation: Citation];
  "open-obsidian": [citation: Citation];
}>();
</script>

<template>
  <div class="w-80 border-l bg-background flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center justify-between border-b p-4">
      <h3 class="font-semibold">引用来源</h3>
      <UiButton
        variant="ghost"
        size="icon"
        class="h-6 w-6"
        @click="emit('close')"
      >
        <X class="h-4 w-4" />
      </UiButton>
    </div>

    <!-- Citation list -->
    <div class="flex-1 p-2 overflow-y-auto">
      <div
        v-if="citations.length === 0"
        class="p-4 text-center text-muted-foreground text-sm"
      >
        暂无引用
      </div>

      <div
        v-for="cit in citations"
        :key="cit.id"
        :class="
          cn(
            'mb-2 cursor-pointer rounded-lg border p-3 transition-colors',
            citation?.id === cit.id
              ? 'border-primary bg-primary/5'
              : 'hover:bg-muted',
          )
        "
        @click="emit('select', cit)"
      >
        <div class="flex items-start justify-between gap-2">
          <span
            class="inline-flex items-center justify-center h-5 w-5 rounded-full bg-primary text-primary-foreground text-xs font-medium shrink-0"
          >
            {{ cit.id }}
          </span>
          <UiButton
            v-if="cit.obsidian_uri"
            variant="ghost"
            size="icon"
            class="shrink-0 h-6 w-6"
            title="在 Obsidian 中打开"
            @click.stop="emit('open-obsidian', cit)"
          >
            <ExternalLink class="h-3 w-3" />
          </UiButton>
        </div>

        <h4 class="mt-2 text-sm font-medium line-clamp-1">
          {{ cit.book_title }}
        </h4>

        <div class="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
          <span v-if="cit.author" class="flex items-center gap-1">
            <User class="h-3 w-3" />
            {{ cit.author }}
          </span>
          <span
            v-if="cit.title_path.length > 0"
            class="flex items-center gap-1"
          >
            <Book class="h-3 w-3" />
            {{ cit.title_path.join(" / ") }}
          </span>
        </div>

        <p class="mt-2 text-xs text-muted-foreground line-clamp-3">
          {{ cit.snippet }}
        </p>

        <div
          v-if="cit.highlight_time"
          class="mt-2 flex items-center gap-1 text-xs text-muted-foreground"
        >
          <Clock class="h-3 w-3" />
          {{ cit.highlight_time }}
        </div>
      </div>
    </div>

    <!-- Selected citation detail -->
    <UiCard
      v-if="citation"
      class="border-t rounded-none border-x-0 max-h-[40%] overflow-y-auto"
    >
      <UiCardHeader class="p-4 pb-2">
        <UiCardTitle class="text-base">{{ citation.book_title }}</UiCardTitle>
        <p
          v-if="citation.title_path.length > 0"
          class="text-sm text-muted-foreground"
        >
          📍 {{ citation.title_path.join(" › ") }}
        </p>
      </UiCardHeader>
      <UiCardContent class="p-4 pt-0">
        <div class="bg-muted rounded-lg p-3 text-sm">
          {{ citation.snippet }}
        </div>
        <UiButton
          v-if="citation.obsidian_uri"
          class="mt-3 w-full"
          @click="emit('open-obsidian', citation)"
        >
          <ExternalLink class="h-4 w-4 mr-2" />
          在 Obsidian 中打开
        </UiButton>
      </UiCardContent>
    </UiCard>
  </div>
</template>
