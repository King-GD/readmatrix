<script setup lang="ts">
interface Props {
  size?: number;
  showText?: boolean;
}

withDefaults(defineProps<Props>(), {
  size: 32,
  showText: false,
});
</script>

<template>
  <div class="flex items-center gap-2">
    <!-- ReadMatrix Logo: Book + Matrix Grid -->
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <!-- Book shape -->
      <path
        d="M4 6C4 4.89543 4.89543 4 6 4H14C15.1046 4 16 4.89543 16 6V26C16 27.1046 15.1046 28 14 28H6C4.89543 28 4 27.1046 4 26V6Z"
        class="fill-primary"
      />
      <path
        d="M16 6C16 4.89543 16.8954 4 18 4H26C27.1046 4 28 4.89543 28 6V26C28 27.1046 27.1046 28 26 28H18C16.8954 28 16 27.1046 16 26V6Z"
        class="fill-primary/80"
      />
      <!-- Matrix dots -->
      <circle cx="8" cy="10" r="1.5" class="fill-primary-foreground" />
      <circle cx="12" cy="10" r="1.5" class="fill-primary-foreground" />
      <circle cx="8" cy="14" r="1.5" class="fill-primary-foreground" />
      <circle cx="12" cy="14" r="1.5" class="fill-primary-foreground" />
      <circle cx="8" cy="18" r="1.5" class="fill-primary-foreground" />
      <circle cx="12" cy="18" r="1.5" class="fill-primary-foreground" />
      <!-- Right page lines -->
      <rect x="19" y="10" width="6" height="1.5" rx="0.75" class="fill-primary-foreground/60" />
      <rect x="19" y="14" width="6" height="1.5" rx="0.75" class="fill-primary-foreground/60" />
      <rect x="19" y="18" width="4" height="1.5" rx="0.75" class="fill-primary-foreground/60" />
    </svg>
    <span v-if="showText" class="text-lg font-semibold">ReadMatrix</span>
  </div>
</template>
