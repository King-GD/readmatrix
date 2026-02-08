<script setup lang="ts">
import { Trash2, Settings } from "lucide-vue-next";
</script>

<template>
  <div class="flex h-screen flex-col bg-background">
    <!-- Header -->
    <header class="flex items-center justify-between border-b px-4 py-3">
      <UiLogo :size="28" show-text />
      <div class="flex items-center gap-2">
        <button
          class="inline-flex items-center justify-center h-9 w-9 rounded-md hover:bg-muted transition-colors"
          title="设置"
        >
          <Settings class="h-4 w-4" />
        </button>
      </div>
    </header>

    <!-- Main content -->
    <main class="flex-1 flex overflow-hidden">
      <slot />
    </main>
  </div>
</template>
