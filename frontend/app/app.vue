<template>
  <div class="min-h-screen">
    <header class="border-b border-zinc-800">
      <div class="mx-auto max-w-4xl px-4 py-4 flex items-center gap-3">
        <NuxtLink to="/create" class="text-lg font-bold tracking-tight">
          🎬 Story Automation
        </NuxtLink>
        <span class="text-xs text-zinc-500">AI cinematic storytelling videos</span>
      </div>
    </header>
    <main class="mx-auto max-w-4xl px-4 py-8">
      <NuxtPage />
    </main>
  </div>
</template>
