<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="mx-auto max-w-4xl px-4 py-8">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div>
        <router-link
          to="/"
          class="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400"
        >
          &larr; Back to Upload
        </router-link>
        <h1 class="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">
          Processing History
        </h1>
        <p class="mt-1 text-sm text-gray-500">
          Recent document extractions and record creations.
        </p>
      </div>
    </div>

    <!-- Placeholder for history list -->
    <div
      class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 p-12 text-center dark:border-gray-600"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="1.5"
        stroke="currentColor"
        class="mx-auto mb-4 h-12 w-12 text-gray-400"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
        />
      </svg>
      <p class="text-gray-500">
        Processing history will be available once the IDP Log DocType is
        created (Phase 11).
      </p>
      <router-link
        to="/"
        class="mt-4 text-sm text-blue-600 hover:text-blue-800"
      >
        Go to Upload
      </router-link>
    </div>
  </div>
</template>
